"""
Prediction Engine — Aggregates parallel simulation runs into probability distributions
and answers strategic prediction questions.

Core questions this engine answers:
1. Who will win the war and how?
2. How long will it last?
3. How will the winner achieve victory?
4. How will the losers lose — what breaks first?
5. What will it cost each side in political power, economy, infrastructure?
6. What happens to proxy groups?
7. What is the probability of nuclear escalation?
8. What does the post-war order look like?

Architecture:
- Runs N parallel simulations (different random seeds/temperatures)
- Aggregates end-states into probability distributions
- Uses LLM to synthesize narrative answers from the distributions
"""

import json
import logging
import statistics
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger('mirofish.prediction_engine')


@dataclass
class RunOutcome:
    """End-state of a single simulation run."""
    run_id: int
    seed: int = 0
    final_round: int = 0
    termination_reason: str = ""
    final_escalation: int = 0
    final_phase: str = ""
    oil_price: float = 0.0
    hormuz_open: bool = False
    mandeb_open: bool = True
    suez_open: bool = True
    actor_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    key_events: List[str] = field(default_factory=list)
    total_events: int = 0


@dataclass
class PredictionResult:
    """Aggregated prediction across all runs."""
    total_runs: int = 0
    timestamp: str = ""

    # War outcome distribution
    outcome_probabilities: Dict[str, float] = field(default_factory=dict)
    # e.g., {"us_israel_victory": 0.4, "negotiated_settlement": 0.3, "stalemate": 0.2, "iran_resilience": 0.1}

    # Duration
    avg_duration_rounds: float = 0
    min_duration: int = 0
    max_duration: int = 0

    # Escalation
    avg_final_escalation: float = 0
    nuclear_escalation_probability: float = 0
    max_escalation_reached: int = 0

    # Economic
    avg_oil_price: float = 0
    hormuz_open_probability: float = 0

    # Per-actor summaries
    actor_predictions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Narrative answers (LLM-generated)
    answers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "timestamp": self.timestamp,
            "outcome_probabilities": self.outcome_probabilities,
            "duration": {
                "avg_rounds": self.avg_duration_rounds,
                "min": self.min_duration,
                "max": self.max_duration,
            },
            "escalation": {
                "avg_final": self.avg_final_escalation,
                "nuclear_probability": self.nuclear_escalation_probability,
                "max_reached": self.max_escalation_reached,
            },
            "economic": {
                "avg_oil_price": self.avg_oil_price,
                "hormuz_open_probability": self.hormuz_open_probability,
            },
            "actor_predictions": self.actor_predictions,
            "answers": self.answers,
        }


PREDICTION_QUESTIONS = [
    ("winner", "Who will win the war? What does 'winning' look like for each side?"),
    ("duration", "How long will the war last? What are the key inflection points?"),
    ("how_winner_wins", "How does the winner achieve victory — through military dominance, economic pressure, diplomatic deal, or exhaustion?"),
    ("how_loser_loses", "How do the losers lose? What breaks first — military capability, economy, domestic support, or alliance cohesion?"),
    ("political_cost", "What does it cost each side in political power — domestic approval, international standing, alliance relationships?"),
    ("economic_cost", "What does it cost economically — GDP impact, oil prices, sanctions damage, infrastructure reconstruction costs?"),
    ("infrastructure", "What infrastructure is destroyed and what are the long-term repair timelines?"),
    ("proxy_groups", "What happens to Hezbollah, Houthis, Hamas, and Iraqi PMF? Do they survive, fragment, or strengthen?"),
    ("nuclear_risk", "What is the probability of nuclear escalation? What conditions would trigger it?"),
    ("post_war", "What does the post-war Middle East look like? New alliances, power shifts, reconstruction?"),
]


class PredictionEngine:
    """Aggregates simulation runs and generates strategic predictions."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def aggregate_runs(self, outcomes: List[RunOutcome]) -> PredictionResult:
        """Aggregate multiple simulation run outcomes into predictions."""
        if not outcomes:
            return PredictionResult()

        result = PredictionResult(
            total_runs=len(outcomes),
            timestamp=datetime.now().isoformat(),
        )

        # Duration stats
        durations = [o.final_round for o in outcomes]
        result.avg_duration_rounds = statistics.mean(durations)
        result.min_duration = min(durations)
        result.max_duration = max(durations)

        # Escalation stats
        escalations = [o.final_escalation for o in outcomes]
        result.avg_final_escalation = statistics.mean(escalations)
        result.max_escalation_reached = max(escalations)
        result.nuclear_escalation_probability = sum(
            1 for o in outcomes if o.final_escalation >= 9
        ) / len(outcomes)

        # Economic stats
        oil_prices = [o.oil_price for o in outcomes if o.oil_price > 0]
        if oil_prices:
            result.avg_oil_price = statistics.mean(oil_prices)
        result.hormuz_open_probability = sum(
            1 for o in outcomes if o.hormuz_open
        ) / len(outcomes)

        # Outcome classification
        result.outcome_probabilities = self._classify_outcomes(outcomes)

        # Per-actor aggregation
        result.actor_predictions = self._aggregate_actor_states(outcomes)

        return result

    def generate_answers(
        self, prediction: PredictionResult, outcomes: List[RunOutcome]
    ) -> PredictionResult:
        """Use LLM to generate narrative answers to prediction questions."""
        if not self.llm_client:
            prediction.answers = {q[0]: "LLM not configured" for q in PREDICTION_QUESTIONS}
            return prediction

        # Build context from aggregated data
        context = self._build_answer_context(prediction, outcomes)

        for question_id, question_text in PREDICTION_QUESTIONS:
            try:
                answer = self._answer_question(question_text, context, prediction)
                prediction.answers[question_id] = answer
                logger.info(f"Generated answer for: {question_id}")
            except Exception as e:
                prediction.answers[question_id] = f"Error generating answer: {e}"
                logger.error(f"Failed to answer {question_id}: {e}")

        return prediction

    def answer_custom_question(
        self, question: str, prediction: PredictionResult, outcomes: List[RunOutcome]
    ) -> str:
        """Answer a custom user question based on simulation results."""
        if not self.llm_client:
            return "LLM not configured. Please set up an AI provider in Settings."

        context = self._build_answer_context(prediction, outcomes)
        return self._answer_question(question, context, prediction)

    def _classify_outcomes(self, outcomes: List[RunOutcome]) -> Dict[str, float]:
        """Classify each run's outcome into categories."""
        categories = {
            "us_israel_military_victory": 0,
            "negotiated_settlement": 0,
            "prolonged_stalemate": 0,
            "iran_strategic_resilience": 0,
            "nuclear_crisis": 0,
            "regime_collapse": 0,
        }

        for outcome in outcomes:
            if outcome.termination_reason == "nuclear_threshold_breached":
                categories["nuclear_crisis"] += 1
            elif "actor_defeated" in outcome.termination_reason and "iran" in outcome.termination_reason.lower():
                categories["us_israel_military_victory"] += 1
            elif outcome.final_escalation <= 3:
                categories["negotiated_settlement"] += 1
            elif outcome.final_phase == "de-escalation":
                categories["negotiated_settlement"] += 1
            elif outcome.termination_reason == "de_escalation_achieved":
                categories["negotiated_settlement"] += 1
            elif outcome.termination_reason == "max_rounds_reached" and outcome.final_escalation >= 6:
                categories["prolonged_stalemate"] += 1
            elif outcome.termination_reason == "max_rounds_reached" and outcome.final_escalation < 6:
                categories["iran_strategic_resilience"] += 1
            else:
                # Check if Iran still has significant force
                iran_state = outcome.actor_states.get("iran", {})
                if iran_state.get("force_strength", 0) > 20:
                    categories["iran_strategic_resilience"] += 1
                else:
                    categories["us_israel_military_victory"] += 1

        # Normalize to probabilities
        total = len(outcomes)
        return {k: round(v / total, 3) for k, v in categories.items() if v > 0}

    def _aggregate_actor_states(self, outcomes: List[RunOutcome]) -> Dict[str, Dict[str, Any]]:
        """Aggregate per-actor states across runs."""
        actor_data: Dict[str, List[Dict]] = {}

        for outcome in outcomes:
            for actor_id, state in outcome.actor_states.items():
                if actor_id not in actor_data:
                    actor_data[actor_id] = []
                actor_data[actor_id].append(state)

        result = {}
        for actor_id, states in actor_data.items():
            force_vals = [s.get("force_strength", 50) for s in states]
            casualty_vals = [s.get("casualties", 0) for s in states]
            approval_vals = [s.get("domestic_approval", 0.5) for s in states]

            result[actor_id] = {
                "name": states[0].get("name", actor_id),
                "avg_final_force": round(statistics.mean(force_vals), 1),
                "min_force": round(min(force_vals), 1),
                "max_force": round(max(force_vals), 1),
                "avg_casualties": int(statistics.mean(casualty_vals)),
                "avg_approval": round(statistics.mean(approval_vals), 3),
                "defeated_in_pct": round(
                    sum(1 for f in force_vals if f <= 5) / len(force_vals), 3
                ),
            }

        return result

    def _build_answer_context(
        self, prediction: PredictionResult, outcomes: List[RunOutcome]
    ) -> str:
        """Build context string for LLM answer generation."""
        # Collect notable events across runs
        all_events = []
        for o in outcomes[:5]:  # Sample from first 5 runs
            all_events.extend(o.key_events[:10])

        context = f"""SIMULATION RESULTS SUMMARY ({prediction.total_runs} parallel runs)

OUTCOME PROBABILITIES:
{json.dumps(prediction.outcome_probabilities, indent=2)}

DURATION: Average {prediction.avg_duration_rounds:.0f} rounds (range: {prediction.min_duration}-{prediction.max_duration})

ESCALATION:
- Average final level: {prediction.avg_final_escalation:.1f}/10
- Nuclear escalation probability: {prediction.nuclear_escalation_probability:.1%}
- Maximum reached: {prediction.max_escalation_reached}/10

ECONOMIC:
- Average final oil price: ${prediction.avg_oil_price:.0f}
- Strait of Hormuz reopened: {prediction.hormuz_open_probability:.0%} of runs

ACTOR OUTCOMES:
{json.dumps(prediction.actor_predictions, indent=2)}

SAMPLE KEY EVENTS:
{chr(10).join(f'- {e}' for e in all_events[:20])}
"""
        return context

    def _answer_question(
        self, question: str, context: str, prediction: PredictionResult
    ) -> str:
        """Generate an answer to a specific prediction question."""
        prompt = f"""You are a geopolitical analyst synthesizing results from {prediction.total_runs} parallel war simulations.

Based ONLY on the simulation data below, answer the question directly and specifically.
Include probability percentages and specific numbers from the data.
Be concise — 2-4 paragraphs max.

{context}

QUESTION: {question}

Answer based on the simulation data above:"""

        response = self.llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        return response
