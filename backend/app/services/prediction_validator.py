"""
Prediction Validator — ensures predictions are grounded in provided data.

Addresses the core problem: how do we know the LLM used our data vs its training data?

Three mechanisms:
1. Data Provenance: tracks which source data points each claim references
2. Grounding Score: measures % of output that cites provided data vs generic claims
3. Calibration Check: compares past predictions against actual outcomes
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger('fors8.validator')


@dataclass
class GroundingReport:
    """Report on how well-grounded a prediction is in source data."""
    total_claims: int = 0
    grounded_claims: int = 0  # Claims that reference specific data points
    ungrounded_claims: int = 0  # Claims with no data reference
    grounding_score: float = 0.0  # 0-1, higher = better grounded

    cited_data_points: List[str] = field(default_factory=list)
    uncited_claims: List[str] = field(default_factory=list)

    # Suspected training data leakage
    suspicious_claims: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_claims": self.total_claims,
            "grounded_claims": self.grounded_claims,
            "ungrounded_claims": self.ungrounded_claims,
            "grounding_score": round(self.grounding_score, 3),
            "cited_data_points": self.cited_data_points[:20],
            "uncited_claims": self.uncited_claims[:10],
            "suspicious_claims": self.suspicious_claims[:10],
        }


def validate_grounding(
    prediction_text: str,
    source_data: Dict[str, Any],
    simulation_results: Dict[str, Any],
) -> GroundingReport:
    """Analyze a prediction for data grounding quality.

    Checks each factual claim in the prediction against the source data
    (initial conditions, market data, actor profiles, simulation results).

    Args:
        prediction_text: The generated prediction/answer text
        source_data: Dict containing initial_conditions, market_data, actors, etc.
        simulation_results: Outcomes, probabilities, actor results from simulation

    Returns:
        GroundingReport with grounding analysis
    """
    report = GroundingReport()

    if not prediction_text:
        return report

    # Build a set of "known data points" from all source data
    known_values = _extract_known_values(source_data, simulation_results)

    # Extract claims from the prediction text
    claims = _extract_claims(prediction_text)
    report.total_claims = len(claims)

    for claim in claims:
        # Check if claim references known data
        is_grounded, data_point = _check_grounding(claim, known_values)

        if is_grounded:
            report.grounded_claims += 1
            if data_point:
                report.cited_data_points.append(data_point)
        else:
            report.ungrounded_claims += 1
            report.uncited_claims.append(claim[:100])

            # Check if it looks like training data leakage
            if _is_suspicious(claim):
                report.suspicious_claims.append(claim[:100])

    report.grounding_score = (
        report.grounded_claims / max(report.total_claims, 1)
    )

    return report


def _extract_known_values(
    source_data: Dict[str, Any],
    simulation_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a flat dict of all known data points for grounding checks."""
    known = {}

    # Flatten source data
    def flatten(d, prefix=""):
        if isinstance(d, dict):
            for k, v in d.items():
                flatten(v, f"{prefix}{k}.")
        elif isinstance(d, (int, float)):
            known[prefix.rstrip(".")] = d
        elif isinstance(d, str) and len(d) < 200:
            known[prefix.rstrip(".")] = d
        elif isinstance(d, list):
            for i, item in enumerate(d):
                if isinstance(item, str):
                    known[f"{prefix}{i}"] = item
                else:
                    flatten(item, f"{prefix}{i}.")

    flatten(source_data, "source.")
    flatten(simulation_results, "sim.")

    # Also extract raw numbers that appear in the data
    # These are the values we expect to see cited in the prediction
    _extract_numbers(source_data, known, "source")
    _extract_numbers(simulation_results, known, "sim")

    return known


def _extract_numbers(d: Any, known: Dict, prefix: str):
    """Recursively extract all numeric values."""
    if isinstance(d, dict):
        for k, v in d.items():
            _extract_numbers(v, known, f"{prefix}.{k}")
    elif isinstance(d, (int, float)) and d != 0:
        known[f"{prefix}"] = d
    elif isinstance(d, list):
        for i, v in enumerate(d):
            _extract_numbers(v, known, f"{prefix}[{i}]")


def _extract_claims(text: str) -> List[str]:
    """Extract factual claims from prediction text.

    A claim is a sentence that contains a number, percentage, or specific assertion.
    """
    sentences = re.split(r'[.!?]\s+', text)
    claims = []

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue

        # Contains a number, percentage, or specific factual indicator
        has_number = bool(re.search(r'\d+\.?\d*', sentence))
        has_percentage = bool(re.search(r'\d+%', sentence))
        has_assertion = any(word in sentence.lower() for word in [
            "according to", "data shows", "simulation", "probability",
            "escalation", "oil price", "casualties", "force strength",
            "based on", "analysis indicates", "results show",
        ])

        if has_number or has_percentage or has_assertion:
            claims.append(sentence)

    return claims


def _check_grounding(claim: str, known_values: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Check if a claim is grounded in known data points."""
    claim_lower = claim.lower()

    # Extract numbers from the claim
    claim_numbers = set()
    for match in re.finditer(r'(\d+\.?\d*)', claim):
        try:
            num = float(match.group(1))
            claim_numbers.add(num)
            # Also check integer form
            if num == int(num):
                claim_numbers.add(int(num))
        except ValueError:
            pass

    # Check if any known value appears in the claim
    for key, value in known_values.items():
        if isinstance(value, (int, float)):
            if value in claim_numbers:
                return True, f"{key}={value}"
            # Check approximate matches (within 5%)
            for cn in claim_numbers:
                if cn > 0 and abs(cn - value) / max(abs(value), 1) < 0.05:
                    return True, f"{key}\u2248{value}"
        elif isinstance(value, str) and len(value) > 3:
            if value.lower() in claim_lower:
                return True, f"{key}={value}"

    # Check for simulation-specific language (likely grounded)
    grounded_patterns = [
        r'simulation\s+(?:shows?|results?|indicates?|predicts?)',
        r'across\s+\d+\s+runs',
        r'(?:monte\s+carlo|aggregate)',
        r'(?:outcome|probability)\s+(?:distribution|of)',
        r'actor.+(?:force|casualties|approval)',
    ]
    for pattern in grounded_patterns:
        if re.search(pattern, claim_lower):
            return True, "simulation_reference"

    return False, None


def _is_suspicious(claim: str) -> bool:
    """Check if an ungrounded claim might be training data leakage.

    Suspicious indicators:
    - Specific dates not in the source data
    - Named events not mentioned in sources
    - Precise numbers that don't appear in any source
    - Historical references used as current facts
    """
    claim_lower = claim.lower()

    # Suspicious: very specific claims about events/dates not in data
    suspicious_patterns = [
        r'(?:history|historically)\s+(?:shows?|demonstrates?)',
        r'(?:in|since|during)\s+(?:19|20)\d{2}',  # Specific year references
        r'experts?\s+(?:say|believe|argue|suggest)',
        r'(?:it\s+is|widely)\s+(?:known|believed|accepted)',
        r'(?:analysts?|observers?)\s+(?:note|point out|suggest)',
        r'traditionally',
        r'(?:has|have)\s+(?:always|historically|traditionally)',
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, claim_lower):
            return True

    return False


def add_grounding_to_answer(
    answer_text: str,
    grounding_report: GroundingReport,
) -> str:
    """Return answer text unchanged — grounding data is stored separately
    in the prediction record and displayed in its own UI card.
    No longer appends raw data reference paths to the answer text."""
    return answer_text
