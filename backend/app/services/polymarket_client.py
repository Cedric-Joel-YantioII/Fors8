"""
Polymarket Integration — real-time prediction market odds for calibration.

Polymarket's public API provides free, real-time odds for geopolitical events.
These serve as calibration baselines: if our simulation consistently agrees with
Polymarket, it adds no value. If it diverges, we track whether our divergences
are correct more often than not.

API: https://docs.polymarket.com/
No authentication required for read-only market data.
"""

import json
import logging
import time
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('fors8.polymarket')

POLYMARKET_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# Cache to avoid hammering the API
_cache: Dict[str, Any] = {}
_cache_ttl = 300  # 5 minutes


@dataclass
class MarketOdds:
    """Odds from a Polymarket prediction market."""
    question: str
    market_id: str
    outcomes: Dict[str, float]  # outcome_name -> probability (0-1)
    volume_usd: float = 0.0
    liquidity_usd: float = 0.0
    last_updated: str = ""
    url: str = ""


def fetch_relevant_markets(query: str, max_results: int = 10) -> List[MarketOdds]:
    """Search Polymarket for markets relevant to the simulation question.

    Args:
        query: Search query (e.g., "Iran war", "oil price", "ceasefire")
        max_results: Maximum number of markets to return

    Returns:
        List of MarketOdds with current probabilities
    """
    cache_key = f"search_{query}_{max_results}"
    if cache_key in _cache and time.time() - _cache.get(f"{cache_key}_time", 0) < _cache_ttl:
        return _cache[cache_key]

    try:
        import requests

        # Search for relevant markets via Gamma API
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "tag": "geopolitics",
                "limit": max_results,
                "active": True,
                "closed": False,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            logger.warning("Polymarket search failed: %s", resp.status_code)
            return []

        markets_data = resp.json()
        if not isinstance(markets_data, list):
            markets_data = [markets_data] if markets_data else []

        results = []
        query_lower = query.lower()
        query_keywords = set(re.findall(r'\w+', query_lower))

        for market in markets_data:
            question = market.get("question", "")
            description = market.get("description", "")

            # Check relevance to query
            market_text = (question + " " + description).lower()
            overlap = len(query_keywords & set(re.findall(r'\w+', market_text)))

            if overlap < 2:
                continue

            # Parse outcomes
            outcomes = {}
            tokens = market.get("tokens", [])
            for token in tokens:
                outcome_name = token.get("outcome", "Unknown")
                price = float(token.get("price", 0.5))
                outcomes[outcome_name] = price

            # If no tokens, try outcomePrices
            if not outcomes:
                outcome_prices = market.get("outcomePrices", "")
                if outcome_prices:
                    try:
                        prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                        if isinstance(prices, list) and len(prices) >= 2:
                            outcomes = {"Yes": float(prices[0]), "No": float(prices[1])}
                    except (json.JSONDecodeError, ValueError, IndexError):
                        pass

            if not outcomes:
                outcomes = {"Yes": 0.5, "No": 0.5}

            results.append(MarketOdds(
                question=question,
                market_id=market.get("id", market.get("condition_id", "")),
                outcomes=outcomes,
                volume_usd=float(market.get("volume", market.get("volumeNum", 0))),
                liquidity_usd=float(market.get("liquidity", market.get("liquidityNum", 0))),
                last_updated=market.get("updatedAt", market.get("end_date_iso", "")),
                url=f"https://polymarket.com/event/{market.get('slug', market.get('id', ''))}",
            ))

        # Sort by volume (most liquid = most reliable)
        results.sort(key=lambda m: m.volume_usd, reverse=True)
        results = results[:max_results]

        _cache[cache_key] = results
        _cache[f"{cache_key}_time"] = time.time()

        logger.info("Polymarket: found %d relevant markets for '%s'", len(results), query[:50])
        return results

    except ImportError:
        logger.warning("requests not available for Polymarket integration")
        return []
    except Exception as e:
        logger.warning("Polymarket fetch failed: %s", e)
        return []


def get_iran_war_markets() -> List[MarketOdds]:
    """Fetch markets specifically about the Iran-US/Israel conflict."""
    keywords = [
        "Iran war",
        "Iran ceasefire",
        "Hormuz",
        "Iran nuclear",
        "Iran Israel",
        "oil price",
        "Middle East war",
    ]

    all_markets = []
    seen_ids = set()

    for kw in keywords:
        markets = fetch_relevant_markets(kw, max_results=5)
        for m in markets:
            if m.market_id not in seen_ids:
                seen_ids.add(m.market_id)
                all_markets.append(m)

    return all_markets


def format_for_prompt(markets: List[MarketOdds]) -> str:
    """Format Polymarket data for inclusion in LLM prompts."""
    if not markets:
        return ""

    lines = ["PREDICTION MARKET CALIBRATION (Polymarket — real money, real-time odds):"]
    for m in markets[:8]:
        outcomes_str = ", ".join(f"{k}: {v:.0%}" for k, v in m.outcomes.items())
        vol_str = f"${m.volume_usd:,.0f}" if m.volume_usd else "N/A"
        lines.append(f"- {m.question}: {outcomes_str} (volume: {vol_str})")

    lines.append("")
    lines.append("INSTRUCTION: Compare your simulation results against these market odds. If your prediction diverges significantly from market consensus, explain WHY with specific data points.")

    return "\n".join(lines)


def compare_predictions(
    simulation_outcomes: Dict[str, float],
    market_odds: List[MarketOdds],
) -> Dict[str, Any]:
    """Compare simulation predictions against Polymarket odds.

    Returns analysis of where the simulation agrees/diverges from markets.
    """
    comparisons = []

    for market in market_odds:
        # Try to match simulation outcomes to market outcomes
        for sim_key, sim_prob in simulation_outcomes.items():
            for mkt_outcome, mkt_prob in market.outcomes.items():
                # Check for keyword overlap
                sim_words = set(sim_key.lower().split("_"))
                mkt_words = set(mkt_outcome.lower().split())
                if len(sim_words & mkt_words) > 0 or sim_key.lower() in mkt_outcome.lower():
                    divergence = abs(sim_prob - mkt_prob)
                    comparisons.append({
                        "market_question": market.question,
                        "market_outcome": mkt_outcome,
                        "market_probability": round(mkt_prob, 3),
                        "simulation_probability": round(sim_prob, 3),
                        "divergence": round(divergence, 3),
                        "direction": "simulation_higher" if sim_prob > mkt_prob else "simulation_lower",
                        "significant": divergence > 0.15,
                    })

    return {
        "comparisons": comparisons,
        "significant_divergences": [c for c in comparisons if c["significant"]],
        "avg_divergence": sum(c["divergence"] for c in comparisons) / max(len(comparisons), 1),
    }
