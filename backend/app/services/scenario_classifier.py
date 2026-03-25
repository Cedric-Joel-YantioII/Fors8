"""
Scenario Classifier — analyzes a user's question to determine scenario type
and returns appropriate simulation parameters (actions, phases, defaults).

Used by predict_pipeline.py to dynamically configure simulations instead of
hardcoding Iran conflict parameters.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger('fors8.scenario')


@dataclass
class ScenarioConfig:
    """Configuration derived from analyzing the user's question."""
    scenario_type: str  # "military_conflict", "economic", "political", "election", "diplomatic", "hybrid"
    scenario_name: str  # Brief description

    # Available actions for agents in simulation
    available_actions: List[str] = field(default_factory=list)

    # Phase definitions: list of (max_escalation, phase_name) tuples, checked in order
    phase_thresholds: List[tuple] = field(default_factory=list)

    # Default initial conditions when graph extraction fails
    default_initial_conditions: Dict[str, Any] = field(default_factory=dict)

    # Base simulation date (today by default)
    base_date: datetime = field(default_factory=datetime.now)

    # Data directory for scenario-specific static data (if any exists)
    static_data_dir: Optional[str] = None

    # Keywords for OSINT search refinement
    osint_keywords: List[str] = field(default_factory=list)

    # Relevant market data categories
    market_categories: List[str] = field(default_factory=list)


# Action sets by scenario type
MILITARY_ACTIONS = [
    "launch_strike", "missile_launch", "air_strike", "deploy_forces",
    "defend_position", "propose_negotiation", "issue_ultimatum",
    "public_statement", "hold_position", "backchannel_communication",
    "blockade", "impose_sanctions", "arm_proxy", "direct_proxy_attack",
    "cyber_attack", "naval_interdiction", "humanitarian_corridor",
    "ceasefire_proposal",
]

ECONOMIC_ACTIONS = [
    "impose_sanctions", "lift_sanctions", "trade_embargo", "currency_intervention",
    "tariff_adjustment", "foreign_aid", "debt_restructuring", "market_intervention",
    "public_statement", "propose_negotiation", "backchannel_communication",
    "regulatory_action", "investment_deal", "hold_position",
    "economic_alliance", "resource_nationalization",
]

POLITICAL_ACTIONS = [
    "public_statement", "propose_negotiation", "issue_ultimatum",
    "backchannel_communication", "diplomatic_summit", "alliance_formation",
    "treaty_proposal", "vote_resolution", "impose_sanctions", "lift_sanctions",
    "intelligence_operation", "public_campaign", "hold_position",
    "diplomatic_protest", "expel_diplomats", "recognize_government",
]

ELECTION_ACTIONS = [
    "public_statement", "campaign_rally", "policy_announcement",
    "attack_ad", "coalition_building", "voter_outreach",
    "media_appearance", "debate_challenge", "endorsement_seek",
    "opposition_research", "fundraising_push", "hold_position",
    "concession", "legal_challenge", "alliance_formation",
]

DIPLOMATIC_ACTIONS = [
    "propose_negotiation", "backchannel_communication", "diplomatic_summit",
    "treaty_proposal", "alliance_formation", "issue_ultimatum",
    "public_statement", "vote_resolution", "impose_sanctions",
    "lift_sanctions", "recognize_government", "expel_diplomats",
    "humanitarian_corridor", "hold_position", "mediation_offer",
    "confidence_building_measure",
]

# Phase thresholds by scenario type
MILITARY_PHASES = [(2, "de-escalation"), (4, "tensions"), (6, "crisis"), (8, "conflict"), (10, "escalation-critical")]
ECONOMIC_PHASES = [(2, "stable"), (4, "volatility"), (6, "downturn"), (8, "crisis"), (10, "collapse")]
POLITICAL_PHASES = [(2, "calm"), (4, "tensions"), (6, "polarization"), (8, "crisis"), (10, "breakdown")]
ELECTION_PHASES = [(2, "early_campaign"), (4, "primary_season"), (6, "general_election"), (8, "contested"), (10, "crisis")]
DIPLOMATIC_PHASES = [(2, "cooperation"), (4, "friction"), (6, "standoff"), (8, "confrontation"), (10, "rupture")]


# Keyword patterns for scenario type detection
_MILITARY_KEYWORDS = r'\b(war|conflict|military|invasion|strike|bomb|missile|troops|army|navy|air\s*force|nuclear|weapon|attack|defend|battle|combat|drone|siege|offensive|ceasefire|escalat|proxy|insurgent|terrorism)\b'
_ECONOMIC_KEYWORDS = r'\b(economy|economic|trade|tariff|sanction|market|gdp|inflation|recession|currency|debt|financial|stock|oil\s*price|commodity|supply\s*chain|manufacturing|export|import|fiscal|monetary)\b'
_ELECTION_KEYWORDS = r'\b(election|vote|ballot|candidate|campaign|poll|primary|caucus|swing\s*state|electoral|democrat|republican|party|nominee|president|governor|senator|parliament|coalition)\b'
_DIPLOMATIC_KEYWORDS = r'\b(diplomat|treaty|negotiat|summit|alliance|un\s*resolution|security\s*council|ambassador|bilateral|multilateral|accord|agreement|peace\s*process|mediat)\b'


def classify_scenario(question: str) -> ScenarioConfig:
    """Analyze the user's question and return appropriate scenario configuration.

    Uses keyword matching to determine scenario type, then returns
    the appropriate action set, phase thresholds, and defaults.
    """
    q_lower = question.lower()

    # Count keyword matches for each type
    scores = {
        "military_conflict": len(re.findall(_MILITARY_KEYWORDS, q_lower, re.IGNORECASE)),
        "economic": len(re.findall(_ECONOMIC_KEYWORDS, q_lower, re.IGNORECASE)),
        "election": len(re.findall(_ELECTION_KEYWORDS, q_lower, re.IGNORECASE)),
        "diplomatic": len(re.findall(_DIPLOMATIC_KEYWORDS, q_lower, re.IGNORECASE)),
    }

    # Pick the highest scoring type, default to "hybrid" if no clear winner
    max_score = max(scores.values())
    if max_score == 0:
        scenario_type = "hybrid"
    else:
        # If multiple types tie or are close (within 1), use hybrid
        top_types = [t for t, s in scores.items() if s >= max_score - 1 and s > 0]
        if len(top_types) > 1 and max_score <= 2:
            scenario_type = "hybrid"
        else:
            scenario_type = max(scores, key=scores.get)

    logger.info("Scenario classification: type=%s, scores=%s", scenario_type, scores)

    # Build configuration based on type
    config = _build_config(scenario_type, question)

    return config


def _build_config(scenario_type: str, question: str) -> ScenarioConfig:
    """Build a ScenarioConfig for the given type."""

    action_map = {
        "military_conflict": MILITARY_ACTIONS,
        "economic": ECONOMIC_ACTIONS,
        "election": ELECTION_ACTIONS,
        "diplomatic": DIPLOMATIC_ACTIONS,
        "political": POLITICAL_ACTIONS,
        "hybrid": MILITARY_ACTIONS + [a for a in DIPLOMATIC_ACTIONS if a not in MILITARY_ACTIONS],
    }

    phase_map = {
        "military_conflict": MILITARY_PHASES,
        "economic": ECONOMIC_PHASES,
        "election": ELECTION_PHASES,
        "diplomatic": DIPLOMATIC_PHASES,
        "political": POLITICAL_PHASES,
        "hybrid": MILITARY_PHASES,  # Default to military phases for hybrid
    }

    # Default initial conditions vary by type
    defaults_map = {
        "military_conflict": {
            "phase": "tensions",
            "escalation_level": 5,
            "oil_price": 85.0,
            "global_risk_index": 0.6,
            "strait_of_hormuz_open": True,
            "bab_el_mandeb_open": True,
            "suez_canal_open": True,
            "nuclear_threshold_status": "stable",
            "humanitarian_impact": 0.0,
            "casualty_estimates": {},
            "active_conflicts": [],
            "active_negotiations": [],
        },
        "economic": {
            "phase": "stable",
            "escalation_level": 3,
            "oil_price": 75.0,
            "global_risk_index": 0.4,
            "strait_of_hormuz_open": True,
            "bab_el_mandeb_open": True,
            "suez_canal_open": True,
            "nuclear_threshold_status": "stable",
            "humanitarian_impact": 0.0,
            "casualty_estimates": {},
            "active_conflicts": [],
            "active_negotiations": [],
        },
        "election": {
            "phase": "early_campaign",
            "escalation_level": 2,
            "oil_price": 75.0,
            "global_risk_index": 0.3,
            "strait_of_hormuz_open": True,
            "bab_el_mandeb_open": True,
            "suez_canal_open": True,
            "nuclear_threshold_status": "stable",
            "humanitarian_impact": 0.0,
            "casualty_estimates": {},
            "active_conflicts": [],
            "active_negotiations": [],
        },
        "diplomatic": {
            "phase": "friction",
            "escalation_level": 4,
            "oil_price": 80.0,
            "global_risk_index": 0.5,
            "strait_of_hormuz_open": True,
            "bab_el_mandeb_open": True,
            "suez_canal_open": True,
            "nuclear_threshold_status": "stable",
            "humanitarian_impact": 0.0,
            "casualty_estimates": {},
            "active_conflicts": [],
            "active_negotiations": [],
        },
    }
    defaults_map["political"] = defaults_map["diplomatic"].copy()
    defaults_map["hybrid"] = defaults_map["military_conflict"].copy()

    # Market categories relevant to each type
    market_map = {
        "military_conflict": ["oil", "defense_stocks", "safe_havens", "gcc", "shipping"],
        "economic": ["oil", "safe_havens", "gcc", "shipping"],
        "election": ["safe_havens"],
        "diplomatic": ["oil", "safe_havens", "gcc"],
        "political": ["oil", "safe_havens"],
        "hybrid": ["oil", "defense_stocks", "safe_havens", "gcc", "shipping"],
    }

    # Extract keywords from question for OSINT refinement
    # Remove common stop words and keep substantive terms
    import string
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "will", "would", "could",
                  "should", "do", "does", "did", "what", "who", "how", "when", "where",
                  "why", "which", "that", "this", "these", "those", "in", "on", "at",
                  "to", "for", "of", "with", "by", "from", "and", "or", "but", "not",
                  "if", "then", "than", "can", "may", "might", "shall", "must", "be",
                  "been", "being", "have", "has", "had", "having", "it", "its"}
    words = question.lower().translate(str.maketrans('', '', string.punctuation)).split()
    osint_keywords = [w for w in words if w not in stop_words and len(w) > 2][:10]

    # Check if there's a matching static data directory
    import os
    data_base = os.path.join(os.path.dirname(__file__), '../../data')
    static_data_dir = None
    if os.path.isdir(data_base):
        # Look for directories that match keywords in the question
        for dirname in os.listdir(data_base):
            dirpath = os.path.join(data_base, dirname)
            if os.path.isdir(dirpath):
                # Check if any keyword from the question matches the directory name
                dir_lower = dirname.lower().replace('_', ' ')
                for kw in osint_keywords:
                    if kw in dir_lower:
                        static_data_dir = dirpath
                        break
                if static_data_dir:
                    break

    config = ScenarioConfig(
        scenario_type=scenario_type,
        scenario_name=question[:100],
        available_actions=action_map.get(scenario_type, action_map["hybrid"]),
        phase_thresholds=phase_map.get(scenario_type, phase_map["hybrid"]),
        default_initial_conditions=defaults_map.get(scenario_type, defaults_map["hybrid"]),
        base_date=datetime.now(),
        static_data_dir=static_data_dir,
        osint_keywords=osint_keywords,
        market_categories=market_map.get(scenario_type, market_map["hybrid"]),
    )

    logger.info("Scenario config: type=%s, actions=%d, static_dir=%s",
                config.scenario_type, len(config.available_actions), config.static_data_dir)

    return config
