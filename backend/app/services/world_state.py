"""
World State Model for Geopolitical Conflict Simulation.

Defines ActorState (per-actor) and WorldState (global) dataclasses
following the WarAgent Board+Stick architecture:
- WorldState (Board) = international relationships + global conditions
- ActorState (Stick) = each actor's internal record
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
import json
import copy


class ActionType(str, Enum):
    """~30 discrete geopolitical actions, following WarAgent's catalogue approach."""

    # Military (8)
    DEPLOY_FORCES = "deploy_forces"
    LAUNCH_STRIKE = "launch_strike"
    DEFEND_POSITION = "defend_position"
    BLOCKADE = "blockade"
    CYBER_ATTACK = "cyber_attack"
    MISSILE_LAUNCH = "missile_launch"
    AIR_STRIKE = "air_strike"
    NAVAL_OPERATION = "naval_operation"

    # Diplomatic (6)
    PROPOSE_NEGOTIATION = "propose_negotiation"
    ISSUE_ULTIMATUM = "issue_ultimatum"
    SIGN_TREATY = "sign_treaty"
    BREAK_ALLIANCE = "break_alliance"
    REQUEST_MEDIATION = "request_mediation"
    UN_VOTE = "un_vote"

    # Economic (4)
    IMPOSE_SANCTIONS = "impose_sanctions"
    CUT_TRADE = "cut_trade"
    FREEZE_ASSETS = "freeze_assets"
    OIL_EMBARGO = "oil_embargo"

    # Intelligence (3)
    GATHER_INTEL = "gather_intel"
    COVERT_OPERATION = "covert_operation"
    CYBER_ESPIONAGE = "cyber_espionage"

    # Proxy (3)
    ARM_PROXY = "arm_proxy"
    DIRECT_PROXY_ATTACK = "direct_proxy_attack"
    PROXY_CEASEFIRE = "proxy_ceasefire"

    # Information (3)
    PUBLIC_STATEMENT = "public_statement"
    PROPAGANDA_CAMPAIGN = "propaganda_campaign"
    DISINFORMATION_CAMPAIGN = "disinformation_campaign"

    # Passive (3)
    HOLD_POSITION = "hold_position"
    ASSESS_SITUATION = "assess_situation"
    BACKCHANNEL_COMMUNICATION = "backchannel_communication"


class ActionDomain(str, Enum):
    """Domain classification for actions."""
    MILITARY = "military"
    DIPLOMATIC = "diplomatic"
    ECONOMIC = "economic"
    INTELLIGENCE = "intelligence"
    PROXY = "proxy"
    INFORMATION = "information"
    PASSIVE = "passive"


# Map action types to their domain
ACTION_DOMAIN_MAP: Dict[ActionType, ActionDomain] = {
    ActionType.DEPLOY_FORCES: ActionDomain.MILITARY,
    ActionType.LAUNCH_STRIKE: ActionDomain.MILITARY,
    ActionType.DEFEND_POSITION: ActionDomain.MILITARY,
    ActionType.BLOCKADE: ActionDomain.MILITARY,
    ActionType.CYBER_ATTACK: ActionDomain.MILITARY,
    ActionType.MISSILE_LAUNCH: ActionDomain.MILITARY,
    ActionType.AIR_STRIKE: ActionDomain.MILITARY,
    ActionType.NAVAL_OPERATION: ActionDomain.MILITARY,
    ActionType.PROPOSE_NEGOTIATION: ActionDomain.DIPLOMATIC,
    ActionType.ISSUE_ULTIMATUM: ActionDomain.DIPLOMATIC,
    ActionType.SIGN_TREATY: ActionDomain.DIPLOMATIC,
    ActionType.BREAK_ALLIANCE: ActionDomain.DIPLOMATIC,
    ActionType.REQUEST_MEDIATION: ActionDomain.DIPLOMATIC,
    ActionType.UN_VOTE: ActionDomain.DIPLOMATIC,
    ActionType.IMPOSE_SANCTIONS: ActionDomain.ECONOMIC,
    ActionType.CUT_TRADE: ActionDomain.ECONOMIC,
    ActionType.FREEZE_ASSETS: ActionDomain.ECONOMIC,
    ActionType.OIL_EMBARGO: ActionDomain.ECONOMIC,
    ActionType.GATHER_INTEL: ActionDomain.INTELLIGENCE,
    ActionType.COVERT_OPERATION: ActionDomain.INTELLIGENCE,
    ActionType.CYBER_ESPIONAGE: ActionDomain.INTELLIGENCE,
    ActionType.ARM_PROXY: ActionDomain.PROXY,
    ActionType.DIRECT_PROXY_ATTACK: ActionDomain.PROXY,
    ActionType.PROXY_CEASEFIRE: ActionDomain.PROXY,
    ActionType.PUBLIC_STATEMENT: ActionDomain.INFORMATION,
    ActionType.PROPAGANDA_CAMPAIGN: ActionDomain.INFORMATION,
    ActionType.DISINFORMATION_CAMPAIGN: ActionDomain.INFORMATION,
    ActionType.HOLD_POSITION: ActionDomain.PASSIVE,
    ActionType.ASSESS_SITUATION: ActionDomain.PASSIVE,
    ActionType.BACKCHANNEL_COMMUNICATION: ActionDomain.PASSIVE,
}

# Escalatory actions — these increase escalation_level
ESCALATORY_ACTIONS = {
    ActionType.LAUNCH_STRIKE,
    ActionType.MISSILE_LAUNCH,
    ActionType.AIR_STRIKE,
    ActionType.BLOCKADE,
    ActionType.CYBER_ATTACK,
    ActionType.NAVAL_OPERATION,
    ActionType.ISSUE_ULTIMATUM,
    ActionType.DIRECT_PROXY_ATTACK,
    ActionType.BREAK_ALLIANCE,
}

# De-escalatory actions
DE_ESCALATORY_ACTIONS = {
    ActionType.PROPOSE_NEGOTIATION,
    ActionType.SIGN_TREATY,
    ActionType.REQUEST_MEDIATION,
    ActionType.PROXY_CEASEFIRE,
    ActionType.BACKCHANNEL_COMMUNICATION,
}


class ActorTier(str, Enum):
    """Actor tier determines LLM model and reasoning depth."""
    STRATEGIC = "strategic"       # Tier 1: Full OODA, strong model
    OPERATIONAL = "operational"   # Tier 2: Constrained actions, faster model
    INFORMATION = "information"   # Tier 3: OASIS social media simulation


@dataclass
class ActorState:
    """Per-actor state variables (the 'Stick' in WarAgent terminology)."""

    actor_id: str
    actor_name: str
    actor_type: str  # NationState, ProxyGroup, MilitaryForce, etc.
    tier: ActorTier = ActorTier.OPERATIONAL

    # Military
    force_strength: float = 50.0        # 0-100, relative capability
    readiness: float = 0.8              # 0-1
    casualties: int = 0
    equipment_status: float = 1.0       # 0-1
    supply_lines_intact: float = 1.0    # 0-1
    territorial_control: Dict[str, float] = field(default_factory=dict)  # region -> control%
    interceptor_inventory: float = 1.0  # 0-1, critical for Israel
    missile_inventory: float = 1.0      # 0-1, critical for Iran

    # Economic
    gdp_impact: float = 0.0            # % change from baseline (negative = damage)
    sanctions_pressure: float = 0.0     # 0-1
    oil_production: float = 1.0         # relative to baseline
    trade_disruption: float = 0.0       # 0-1
    currency_stability: float = 1.0     # 0-1

    # Political
    domestic_approval: float = 0.5      # 0-1
    international_support: float = 0.5  # 0-1
    alliance_cohesion: float = 0.8      # 0-1

    # Information
    narrative_control: float = 0.5      # 0-1
    propaganda_effectiveness: float = 0.5  # 0-1

    # Ideology & Temperament (set from profile, rarely changes during sim)
    martyrdom_willingness: float = 0.0  # 0-1, how willing to absorb casualties
    eschatological_factor: float = 0.0  # 0-1, religious/ideological escalation driver
    regime_survival_priority: float = 0.5  # 0-1, self-preservation vs ideology
    risk_tolerance: float = 0.5         # 0-1
    escalation_threshold: float = 0.5   # 0-1, how easily provoked
    casualty_threshold: float = 0.5     # 0-1, how many casualties before de-escalating
    negotiation_willingness: float = 0.5  # 0-1

    # Intelligence
    intel_visibility: Dict[str, float] = field(default_factory=dict)  # actor_id -> 0-1 visibility

    # Action history (last N rounds)
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)

    # Public commitments that constrain future actions
    public_commitments: List[str] = field(default_factory=list)

    def to_briefing_dict(self, observer_visibility: float = 1.0) -> Dict[str, Any]:
        """Generate a state summary filtered by fog-of-war visibility.

        Args:
            observer_visibility: How much the observer can see (0=blind, 1=full)
        """
        if observer_visibility >= 0.8:
            # High visibility — show precise values
            return {
                "actor": self.actor_name,
                "force_strength": round(self.force_strength, 1),
                "readiness": round(self.readiness, 2),
                "casualties": self.casualties,
                "equipment_status": round(self.equipment_status, 2),
                "domestic_approval": round(self.domestic_approval, 2),
                "international_support": round(self.international_support, 2),
                "sanctions_pressure": round(self.sanctions_pressure, 2),
                "oil_production": round(self.oil_production, 2),
                "narrative_control": round(self.narrative_control, 2),
            }
        elif observer_visibility >= 0.4:
            # Medium visibility — show approximate ranges
            def approx(val, noise=0.15):
                import random
                return round(max(0, min(1, val + random.uniform(-noise, noise))), 1)

            return {
                "actor": self.actor_name,
                "force_strength": f"~{round(self.force_strength / 10) * 10}",
                "readiness": "high" if self.readiness > 0.7 else "medium" if self.readiness > 0.4 else "low",
                "casualties": f"~{round(self.casualties / 100) * 100}" if self.casualties > 0 else "minimal",
                "domestic_approval": "high" if self.domestic_approval > 0.6 else "moderate" if self.domestic_approval > 0.3 else "low",
                "sanctions_pressure": "severe" if self.sanctions_pressure > 0.7 else "moderate" if self.sanctions_pressure > 0.3 else "light",
            }
        else:
            # Low visibility — minimal information
            return {
                "actor": self.actor_name,
                "assessment": "limited intelligence available",
                "force_strength": "unknown",
                "readiness": "unknown",
            }


@dataclass
class GeopoliticalEvent:
    """A single event in the simulation timeline."""
    round_num: int
    timestamp: str  # simulated time
    actor_id: str
    actor_name: str
    action_type: ActionType
    action_domain: ActionDomain
    target_actor_id: Optional[str] = None
    target_actor_name: Optional[str] = None
    action_params: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    consequence_summary: str = ""
    escalation_delta: int = 0  # how much this action changed escalation level


@dataclass
class WorldState:
    """Global state shared across all actors (the 'Board' in WarAgent terminology)."""

    round_num: int = 0
    simulated_time: str = ""  # e.g., "2026-03-23T00:00:00Z"
    phase: str = "tensions"   # tensions / crisis / conflict / de-escalation / ceasefire

    # Global indicators
    escalation_level: int = 5  # 1-10 (current war is ~5-7)
    oil_price: float = 90.0   # USD per barrel
    global_risk_index: float = 0.5  # 0-1
    humanitarian_impact: float = 0.0  # 0-1
    nuclear_threshold_status: str = "warning"  # safe / warning / critical / breached

    # Active situation
    active_conflicts: List[str] = field(default_factory=list)
    active_negotiations: List[str] = field(default_factory=list)
    un_resolutions: List[str] = field(default_factory=list)
    active_blockades: List[str] = field(default_factory=list)

    # Chokepoints
    strait_of_hormuz_open: bool = False
    bab_el_mandeb_open: bool = True  # Houthis holding fire for now
    suez_canal_open: bool = True

    # Actors
    actors: Dict[str, ActorState] = field(default_factory=dict)

    # Event log
    events: List[GeopoliticalEvent] = field(default_factory=list)

    # Round-level summary (for Zep memory updates)
    round_summaries: List[str] = field(default_factory=list)

    def get_actor(self, actor_id: str) -> Optional[ActorState]:
        return self.actors.get(actor_id)

    def get_situation_briefing(self, for_actor_id: str) -> Dict[str, Any]:
        """Build a situation briefing for a specific actor, filtered by their intel visibility."""
        actor = self.actors.get(for_actor_id)
        if not actor:
            return {}

        # Global situation (visible to all)
        briefing = {
            "round": self.round_num,
            "simulated_time": self.simulated_time,
            "phase": self.phase,
            "escalation_level": self.escalation_level,
            "oil_price": self.oil_price,
            "nuclear_threshold_status": self.nuclear_threshold_status,
            "active_conflicts": self.active_conflicts,
            "active_negotiations": self.active_negotiations,
            "chokepoints": {
                "strait_of_hormuz": "open" if self.strait_of_hormuz_open else "closed",
                "bab_el_mandeb": "open" if self.bab_el_mandeb_open else "closed/threatened",
                "suez_canal": "open" if self.suez_canal_open else "closed/disrupted",
            },
            "your_state": actor.to_briefing_dict(observer_visibility=1.0),
            "other_actors": {},
            "recent_events": [],
        }

        # Other actors — filtered by intel visibility
        for other_id, other_state in self.actors.items():
            if other_id == for_actor_id:
                continue
            visibility = actor.intel_visibility.get(other_id, 0.3)
            briefing["other_actors"][other_id] = other_state.to_briefing_dict(visibility)

        # Recent events (last 3 rounds, filtered by what this actor could observe)
        recent_cutoff = max(0, self.round_num - 3)
        for event in self.events:
            if event.round_num >= recent_cutoff:
                # Public actions are visible to all
                if event.action_type in (
                    ActionType.PUBLIC_STATEMENT,
                    ActionType.PROPAGANDA_CAMPAIGN,
                    ActionType.LAUNCH_STRIKE,
                    ActionType.MISSILE_LAUNCH,
                    ActionType.AIR_STRIKE,
                    ActionType.BLOCKADE,
                    ActionType.IMPOSE_SANCTIONS,
                    ActionType.ISSUE_ULTIMATUM,
                    ActionType.SIGN_TREATY,
                    ActionType.PROPOSE_NEGOTIATION,
                    ActionType.UN_VOTE,
                ):
                    briefing["recent_events"].append({
                        "round": event.round_num,
                        "actor": event.actor_name,
                        "action": event.action_type.value,
                        "target": event.target_actor_name,
                        "summary": event.consequence_summary,
                    })
                elif event.actor_id == for_actor_id:
                    # Own actions always visible
                    briefing["recent_events"].append({
                        "round": event.round_num,
                        "actor": event.actor_name,
                        "action": event.action_type.value,
                        "target": event.target_actor_name,
                        "summary": event.consequence_summary,
                    })
                else:
                    # Covert actions only visible with high intel
                    visibility = actor.intel_visibility.get(event.actor_id, 0.3)
                    if visibility > 0.7:
                        briefing["recent_events"].append({
                            "round": event.round_num,
                            "actor": event.actor_name,
                            "action": event.action_type.value,
                            "target": event.target_actor_name,
                            "summary": event.consequence_summary,
                            "confidence": "intelligence suggests",
                        })

        return briefing

    def snapshot(self) -> Dict[str, Any]:
        """Create a serializable snapshot of the world state."""
        return {
            "round_num": self.round_num,
            "simulated_time": self.simulated_time,
            "phase": self.phase,
            "escalation_level": self.escalation_level,
            "oil_price": self.oil_price,
            "global_risk_index": self.global_risk_index,
            "nuclear_threshold_status": self.nuclear_threshold_status,
            "strait_of_hormuz_open": self.strait_of_hormuz_open,
            "bab_el_mandeb_open": self.bab_el_mandeb_open,
            "suez_canal_open": self.suez_canal_open,
            "active_conflicts": self.active_conflicts,
            "active_negotiations": self.active_negotiations,
            "actors": {
                actor_id: {
                    "name": actor.actor_name,
                    "type": actor.actor_type,
                    "force_strength": actor.force_strength,
                    "casualties": actor.casualties,
                    "domestic_approval": actor.domestic_approval,
                    "sanctions_pressure": actor.sanctions_pressure,
                    "narrative_control": actor.narrative_control,
                }
                for actor_id, actor in self.actors.items()
            },
            "total_events": len(self.events),
        }

    def deep_copy(self) -> "WorldState":
        """Create a deep copy for what-if scenario branching."""
        return copy.deepcopy(self)
