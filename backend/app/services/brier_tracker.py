"""
Brier Score Tracker — measures prediction accuracy over time.

The Brier score is the gold standard for evaluating probabilistic predictions:
- Score of 0.0 = perfect prediction
- Score of 0.25 = no better than coin flip
- Score of 0.086 = superforecaster benchmark (top human forecasters)
- Score of 0.15 = good automated system

Without tracking Brier scores against resolved outcomes, we have no way
to know if the simulation is actually useful or just producing plausible-
sounding guesses.

Usage:
1. After each prediction, save the forecast
2. When outcome is known, resolve it
3. Track running Brier score to see if system improves
"""

import json
import logging
import os
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger('fors8.brier')

BRIER_FILE = os.path.join(os.path.dirname(__file__), '../../data/brier_scores.json')


@dataclass
class Forecast:
    """A single probabilistic forecast to be scored later."""
    forecast_id: str
    prediction_id: str
    question: str
    timestamp: str

    # Predicted probabilities for each outcome
    probabilities: Dict[str, float] = field(default_factory=dict)

    # Resolution (filled in when outcome is known)
    resolved: bool = False
    actual_outcome: str = ""
    resolution_timestamp: str = ""

    # Brier score (calculated on resolution)
    brier_score: Optional[float] = None

    # Context
    model_name: str = ""
    num_agents: int = 0
    num_runs: int = 0
    grounding_score: float = 0.0

    # Polymarket comparison (if available)
    polymarket_odds: Dict[str, float] = field(default_factory=dict)
    polymarket_brier: Optional[float] = None  # Brier score if we had used Polymarket odds


def calculate_brier_score(probabilities: Dict[str, float], actual_outcome: str) -> float:
    """Calculate the Brier score for a probabilistic forecast.

    Brier score = (1/N) * sum((forecast_i - outcome_i)^2)

    Where outcome_i = 1 if outcome occurred, 0 otherwise.
    Lower is better. 0 = perfect, 0.25 = random guessing.
    """
    n = len(probabilities)
    if n == 0:
        return 0.25  # No prediction = random

    score = 0.0
    for outcome, prob in probabilities.items():
        actual = 1.0 if outcome == actual_outcome else 0.0
        score += (prob - actual) ** 2

    return score / n


def save_forecast(
    prediction_id: str,
    question: str,
    probabilities: Dict[str, float],
    model_name: str = "",
    num_agents: int = 0,
    num_runs: int = 0,
    grounding_score: float = 0.0,
    polymarket_odds: Optional[Dict[str, float]] = None,
) -> Forecast:
    """Save a forecast for later Brier score evaluation.

    Call this after every prediction. When the outcome is known,
    call resolve_forecast() to calculate the Brier score.
    """
    forecast = Forecast(
        forecast_id=f"fc_{prediction_id}_{int(time.time())}",
        prediction_id=prediction_id,
        question=question,
        timestamp=datetime.now().isoformat(),
        probabilities=probabilities,
        model_name=model_name,
        num_agents=num_agents,
        num_runs=num_runs,
        grounding_score=grounding_score,
        polymarket_odds=polymarket_odds or {},
    )

    # Load existing forecasts
    forecasts = _load_forecasts()
    forecasts.append(asdict(forecast))
    _save_forecasts(forecasts)

    logger.info("Saved forecast %s: %s", forecast.forecast_id,
                json.dumps(probabilities))
    return forecast


def resolve_forecast(
    prediction_id: str,
    actual_outcome: str,
) -> Optional[float]:
    """Resolve a forecast and calculate its Brier score.

    Call this when the real-world outcome is known.

    Args:
        prediction_id: The prediction this forecast belongs to
        actual_outcome: The outcome that actually occurred (must match a key in probabilities)

    Returns:
        Brier score (0 = perfect, 0.25 = random)
    """
    forecasts = _load_forecasts()

    resolved_score = None
    for fc in forecasts:
        if fc.get("prediction_id") == prediction_id and not fc.get("resolved"):
            probs = fc.get("probabilities", {})
            brier = calculate_brier_score(probs, actual_outcome)

            fc["resolved"] = True
            fc["actual_outcome"] = actual_outcome
            fc["resolution_timestamp"] = datetime.now().isoformat()
            fc["brier_score"] = round(brier, 6)

            # Also calculate what Polymarket's score would have been
            poly_odds = fc.get("polymarket_odds", {})
            if poly_odds:
                fc["polymarket_brier"] = round(
                    calculate_brier_score(poly_odds, actual_outcome), 6
                )

            resolved_score = brier
            logger.info("Resolved forecast %s: outcome=%s, brier=%.4f",
                       fc["forecast_id"], actual_outcome, brier)

    _save_forecasts(forecasts)
    return resolved_score


def get_performance_summary() -> Dict[str, Any]:
    """Get overall prediction performance statistics."""
    forecasts = _load_forecasts()

    resolved = [fc for fc in forecasts if fc.get("resolved")]
    unresolved = [fc for fc in forecasts if not fc.get("resolved")]

    if not resolved:
        return {
            "total_forecasts": len(forecasts),
            "resolved": 0,
            "unresolved": len(unresolved),
            "avg_brier_score": None,
            "assessment": "No resolved forecasts yet — submit outcomes to start tracking accuracy",
            "benchmarks": {
                "perfect": 0.0,
                "superforecaster": 0.086,
                "good_system": 0.15,
                "random_guessing": 0.25,
            },
        }

    brier_scores = [fc["brier_score"] for fc in resolved if fc.get("brier_score") is not None]
    avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

    poly_scores = [fc["polymarket_brier"] for fc in resolved if fc.get("polymarket_brier") is not None]
    avg_poly = sum(poly_scores) / len(poly_scores) if poly_scores else None

    # Assess quality
    if avg_brier is not None:
        if avg_brier < 0.086:
            assessment = "EXCEPTIONAL — outperforming superforecasters"
        elif avg_brier < 0.15:
            assessment = "GOOD — competitive with professional forecasters"
        elif avg_brier < 0.20:
            assessment = "MODERATE — better than random, room for improvement"
        elif avg_brier < 0.25:
            assessment = "POOR — barely better than coin flip"
        else:
            assessment = "WORSE THAN RANDOM — system is anti-predictive"
    else:
        assessment = "Insufficient data"

    # Compare against Polymarket
    beats_polymarket = None
    if avg_brier is not None and avg_poly is not None:
        beats_polymarket = avg_brier < avg_poly

    return {
        "total_forecasts": len(forecasts),
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "avg_brier_score": round(avg_brier, 4) if avg_brier else None,
        "best_brier": round(min(brier_scores), 4) if brier_scores else None,
        "worst_brier": round(max(brier_scores), 4) if brier_scores else None,
        "assessment": assessment,
        "polymarket_avg_brier": round(avg_poly, 4) if avg_poly else None,
        "beats_polymarket": beats_polymarket,
        "benchmarks": {
            "perfect": 0.0,
            "superforecaster": 0.086,
            "good_system": 0.15,
            "random_guessing": 0.25,
            "our_system": round(avg_brier, 4) if avg_brier else "N/A",
        },
        "recent_forecasts": [
            {
                "question": fc.get("question", "")[:80],
                "brier": fc.get("brier_score"),
                "outcome": fc.get("actual_outcome"),
                "timestamp": fc.get("timestamp"),
            }
            for fc in sorted(resolved, key=lambda x: x.get("resolution_timestamp", ""), reverse=True)[:5]
        ],
    }


def _load_forecasts() -> List[Dict]:
    """Load forecasts from disk."""
    try:
        if os.path.exists(BRIER_FILE):
            with open(BRIER_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_forecasts(forecasts: List[Dict]):
    """Save forecasts to disk."""
    try:
        os.makedirs(os.path.dirname(BRIER_FILE), exist_ok=True)
        with open(BRIER_FILE, 'w') as f:
            json.dump(forecasts, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save forecasts: %s", e)
