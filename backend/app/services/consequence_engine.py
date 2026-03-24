"""
Consequence Engine for Geopolitical Conflict Simulation.

Resolves actor actions into world state changes. Configurable via JSON rules
for tuning without code changes. Handles:
- Direct effects (strike → reduce force_strength, increase casualties)
- Cascading effects (oil disruption → price spike → economic pressure)
- Asymmetric weapons economics (cheap missiles vs expensive interceptors)
- Escalation mechanics with guardrails
"""

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

from .world_state import (
    ActionType,
    ActionDomain,
    ACTION_DOMAIN_MAP,
    ESCALATORY_ACTIONS,
    DE_ESCALATORY_ACTIONS,
    ActorState,
    WorldState,
    GeopoliticalEvent,
)


@dataclass
class ActionResolution:
    """Result of resolving an action through the consequence engine."""
    success: bool = True
    consequence_summary: str = ""
    escalation_delta: int = 0
    state_changes: Dict[str, Any] = None  # actor_id -> {field: delta}
    global_changes: Dict[str, Any] = None
    cascading_effects: List[str] = None

    def __post_init__(self):
        if self.state_changes is None:
            self.state_changes = {}
        if self.global_changes is None:
            self.global_changes = {}
        if self.cascading_effects is None:
            self.cascading_effects = []


# Default consequence rules — can be overridden by JSON config
DEFAULT_RULES = {
    "strike_damage": {
        "base_force_reduction": 5.0,      # % force_strength reduced per strike
        "base_casualties": 200,            # base casualties per strike
        "equipment_degradation": 0.05,     # equipment_status reduction
        "escalation_increase": 2,          # escalation_level increase
    },
    "missile_launch": {
        "base_force_reduction": 3.0,
        "base_casualties": 100,
        "interceptor_cost_per_missile": 0.02,  # interceptor_inventory reduction per missile
        "missiles_per_salvo": 50,
        "interception_rate_base": 0.85,        # base interception rate
        "interception_rate_depleted": 0.40,    # rate when interceptors low
        "escalation_increase": 2,
        "attacker_missile_cost": 0.01,         # missile_inventory reduction per salvo
    },
    "sanctions": {
        "sanctions_pressure_increase": 0.15,
        "gdp_impact_per_round": -0.5,          # % GDP change per round under sanctions
        "delay_rounds": 3,                      # rounds before full economic impact
        "escalation_increase": 0,
    },
    "blockade": {
        "trade_disruption_increase": 0.3,
        "oil_price_spike_pct": 15.0,            # % increase in oil price
        "escalation_increase": 2,
    },
    "proxy_attack": {
        "base_force_reduction": 2.0,
        "base_casualties": 50,
        "escalation_increase": 1,               # lower than direct attack
        "patron_deniability": 0.5,               # how much blame falls on patron
    },
    "negotiation": {
        "escalation_decrease": 1,
        "domestic_approval_change": -0.02,       # slight domestic cost of appearing weak
        "international_support_change": 0.05,
    },
    "propaganda": {
        "narrative_control_boost": 0.1,
        "target_domestic_approval_change": -0.05,
        "escalation_increase": 0,
    },
    "asymmetric_economics": {
        "missile_cost_ratio": 0.01,              # cost of missile relative to interceptor
        "interceptor_depletion_threshold": 0.2,  # below this, interception rate degrades fast
    },
    "casualty_thresholds": {
        "western_casualty_sensitivity": 0.003,    # domestic_approval loss per casualty (USA/Israel)
        "ideological_casualty_sensitivity": 0.001, # domestic_approval loss per casualty (Iran/proxies)
    },
    "escalation": {
        "max_level": 10,
        "nuclear_threshold": 9,
        "cost_multiplier_per_level": 1.5,         # each escalation level makes escalation harder
        "de_escalation_injection_interval": 5,     # inject de-escalation opportunity every N rounds
    },
}


class ConsequenceEngine:
    """Resolves geopolitical actions into world state changes."""

    def __init__(self, rules_path: Optional[str] = None):
        """Initialize with optional custom rules JSON file."""
        self.rules = DEFAULT_RULES.copy()
        if rules_path and os.path.exists(rules_path):
            with open(rules_path, 'r') as f:
                custom_rules = json.load(f)
            # Merge custom rules (deep merge one level)
            for key, value in custom_rules.items():
                if key in self.rules and isinstance(self.rules[key], dict):
                    self.rules[key].update(value)
                else:
                    self.rules[key] = value

    def resolve_action(
        self,
        action_type: ActionType,
        actor: ActorState,
        world_state: WorldState,
        target_actor: Optional[ActorState] = None,
        action_params: Optional[Dict[str, Any]] = None,
    ) -> ActionResolution:
        """Resolve a single action into state changes.

        Args:
            action_type: The action being taken
            actor: The actor taking the action
            world_state: Current world state
            target_actor: Target of the action (if applicable)
            action_params: Additional parameters from LLM decision

        Returns:
            ActionResolution with all state changes to apply
        """
        params = action_params or {}
        resolution = ActionResolution()

        # Dispatch to specific handler
        handler = self._get_handler(action_type)
        if handler:
            resolution = handler(actor, world_state, target_actor, params)

        # Apply escalation guardrails
        resolution = self._apply_escalation_guardrails(
            resolution, action_type, actor, world_state
        )

        return resolution

    def apply_resolution(
        self,
        resolution: ActionResolution,
        world_state: WorldState,
    ) -> None:
        """Apply a resolution's state changes to the world state."""

        # Apply per-actor changes
        for actor_id, changes in resolution.state_changes.items():
            actor = world_state.get_actor(actor_id)
            if not actor:
                continue
            for field_name, delta in changes.items():
                current = getattr(actor, field_name, None)
                if current is not None:
                    if isinstance(current, (int, float)):
                        new_val = current + delta
                        # Clamp to valid ranges
                        if field_name in ('force_strength',):
                            new_val = max(0, min(100, new_val))
                        elif field_name in ('casualties',):
                            new_val = max(0, int(new_val))
                        elif field_name in ('gdp_impact',):
                            # GDP impact can be negative (damage)
                            new_val = max(-100.0, min(100.0, new_val))
                        elif isinstance(current, float):
                            new_val = max(0.0, min(1.0, new_val))
                        setattr(actor, field_name, new_val)

        # Apply global changes
        for field_name, delta in resolution.global_changes.items():
            current = getattr(world_state, field_name, None)
            if current is None:
                continue
            # Check bool BEFORE int/float since bool is a subclass of int in Python
            if isinstance(current, bool):
                setattr(world_state, field_name, bool(delta))
            elif isinstance(current, (int, float)):
                new_val = current + delta
                if field_name == 'escalation_level':
                    new_val = max(1, min(self.rules["escalation"]["max_level"], int(new_val)))
                elif field_name == 'oil_price':
                    new_val = max(20.0, new_val)
                setattr(world_state, field_name, new_val)

        # Apply cascading effects
        self._apply_cascading_effects(resolution, world_state)

    def check_termination(self, world_state: WorldState, max_rounds: int) -> Tuple[bool, str]:
        """Check if the simulation should terminate.

        Returns:
            (should_terminate, reason)
        """
        if world_state.round_num >= max_rounds:
            return True, "max_rounds_reached"

        if world_state.escalation_level >= self.rules["escalation"]["nuclear_threshold"]:
            return True, "nuclear_threshold_breached"

        if world_state.escalation_level <= 1 and world_state.round_num > 5:
            return True, "de_escalation_achieved"

        # Check if any major actor's force_strength is effectively zero
        for actor_id, actor in world_state.actors.items():
            if actor.tier.value == "strategic" and actor.force_strength <= 5:
                return True, f"actor_defeated:{actor.actor_name}"

        return False, ""

    def should_inject_de_escalation(self, world_state: WorldState) -> bool:
        """Check if we should inject a de-escalation opportunity this round."""
        interval = self.rules["escalation"]["de_escalation_injection_interval"]
        return world_state.round_num > 0 and world_state.round_num % interval == 0

    # --- Action Handlers ---

    def _get_handler(self, action_type: ActionType):
        """Get the handler function for an action type."""
        handlers = {
            ActionType.LAUNCH_STRIKE: self._handle_strike,
            ActionType.AIR_STRIKE: self._handle_strike,
            ActionType.MISSILE_LAUNCH: self._handle_missile_launch,
            ActionType.DEPLOY_FORCES: self._handle_deploy,
            ActionType.DEFEND_POSITION: self._handle_defend,
            ActionType.BLOCKADE: self._handle_blockade,
            ActionType.CYBER_ATTACK: self._handle_cyber_attack,
            ActionType.NAVAL_OPERATION: self._handle_naval_operation,
            ActionType.IMPOSE_SANCTIONS: self._handle_sanctions,
            ActionType.CUT_TRADE: self._handle_cut_trade,
            ActionType.OIL_EMBARGO: self._handle_oil_embargo,
            ActionType.FREEZE_ASSETS: self._handle_freeze_assets,
            ActionType.ARM_PROXY: self._handle_arm_proxy,
            ActionType.DIRECT_PROXY_ATTACK: self._handle_proxy_attack,
            ActionType.PROXY_CEASEFIRE: self._handle_proxy_ceasefire,
            ActionType.PROPOSE_NEGOTIATION: self._handle_negotiation,
            ActionType.ISSUE_ULTIMATUM: self._handle_ultimatum,
            ActionType.SIGN_TREATY: self._handle_treaty,
            ActionType.BREAK_ALLIANCE: self._handle_break_alliance,
            ActionType.REQUEST_MEDIATION: self._handle_mediation,
            ActionType.UN_VOTE: self._handle_un_vote,
            ActionType.PUBLIC_STATEMENT: self._handle_public_statement,
            ActionType.PROPAGANDA_CAMPAIGN: self._handle_propaganda,
            ActionType.DISINFORMATION_CAMPAIGN: self._handle_disinfo,
            ActionType.GATHER_INTEL: self._handle_gather_intel,
            ActionType.COVERT_OPERATION: self._handle_covert_op,
            ActionType.CYBER_ESPIONAGE: self._handle_cyber_espionage,
            ActionType.HOLD_POSITION: self._handle_passive,
            ActionType.ASSESS_SITUATION: self._handle_passive,
            ActionType.BACKCHANNEL_COMMUNICATION: self._handle_backchannel,
        }
        return handlers.get(action_type)

    def _handle_strike(self, actor, world_state, target, params):
        r = self.rules["strike_damage"]
        res = ActionResolution()

        if not target:
            res.success = False
            res.consequence_summary = "Strike failed: no target specified"
            return res

        # Damage scales with attacker's force_strength
        damage_mult = actor.force_strength / 50.0  # normalized around 50
        force_reduction = r["base_force_reduction"] * damage_mult
        casualties = int(r["base_casualties"] * damage_mult)

        # Target defense reduces damage
        defense_mult = target.equipment_status * target.readiness
        force_reduction *= (1 - defense_mult * 0.4)
        casualties = int(casualties * (1 - defense_mult * 0.3))

        res.state_changes[target.actor_id] = {
            "force_strength": -force_reduction,
            "casualties": casualties,
            "equipment_status": -r["equipment_degradation"],
        }

        # Attacker costs
        res.state_changes[actor.actor_id] = {
            "readiness": -0.02,
            "equipment_status": -0.01,
        }

        res.escalation_delta = r["escalation_increase"]
        res.global_changes["escalation_level"] = r["escalation_increase"]
        res.consequence_summary = (
            f"{actor.actor_name} launched strike against {target.actor_name}. "
            f"Estimated {casualties} casualties, {force_reduction:.1f}% force reduction."
        )

        # Civilian casualty narrative impact
        if casualties > 100:
            res.state_changes[actor.actor_id]["narrative_control"] = -0.05
            res.state_changes[actor.actor_id]["international_support"] = -0.03
            res.cascading_effects.append("civilian_casualty_narrative_impact")

        return res

    def _handle_missile_launch(self, actor, world_state, target, params):
        r = self.rules["missile_launch"]
        ar = self.rules["asymmetric_economics"]
        res = ActionResolution()

        if not target:
            res.success = False
            res.consequence_summary = "Missile launch failed: no target specified"
            return res

        salvos = params.get("salvos", 1)
        missiles_fired = r["missiles_per_salvo"] * salvos

        # Interception rate depends on target's interceptor inventory
        if target.interceptor_inventory > ar["interceptor_depletion_threshold"]:
            intercept_rate = r["interception_rate_base"]
        else:
            # Degraded — linear interpolation to depleted rate
            ratio = target.interceptor_inventory / ar["interceptor_depletion_threshold"]
            intercept_rate = (
                r["interception_rate_depleted"]
                + ratio * (r["interception_rate_base"] - r["interception_rate_depleted"])
            )

        missiles_through = int(missiles_fired * (1 - intercept_rate))
        damage_mult = missiles_through / r["missiles_per_salvo"]
        force_reduction = r["base_force_reduction"] * damage_mult
        casualties = int(r["base_casualties"] * damage_mult)

        # Target loses interceptors (expensive!)
        interceptor_cost = r["interceptor_cost_per_missile"] * missiles_fired * intercept_rate
        # Attacker loses missiles (cheap)
        missile_cost = r["attacker_missile_cost"] * salvos

        res.state_changes[target.actor_id] = {
            "force_strength": -force_reduction,
            "casualties": casualties,
            "interceptor_inventory": -interceptor_cost,
        }
        res.state_changes[actor.actor_id] = {
            "missile_inventory": -missile_cost,
        }

        res.escalation_delta = r["escalation_increase"]
        res.global_changes["escalation_level"] = r["escalation_increase"]
        res.consequence_summary = (
            f"{actor.actor_name} launched {missiles_fired} missiles at {target.actor_name}. "
            f"{int(intercept_rate * 100)}% intercepted ({missiles_through} hit). "
            f"~{casualties} casualties. Target interceptor inventory: {target.interceptor_inventory - interceptor_cost:.1%}"
        )

        return res

    def _handle_deploy(self, actor, world_state, target, params):
        res = ActionResolution()
        region = params.get("region", "unspecified")
        res.state_changes[actor.actor_id] = {
            "readiness": 0.05,
        }
        res.escalation_delta = 1
        res.global_changes["escalation_level"] = 1
        res.consequence_summary = f"{actor.actor_name} deployed forces to {region}."
        return res

    def _handle_defend(self, actor, world_state, target, params):
        res = ActionResolution()
        res.state_changes[actor.actor_id] = {
            "readiness": 0.03,
            "equipment_status": -0.01,
        }
        res.consequence_summary = f"{actor.actor_name} fortified defensive positions."
        return res

    def _handle_blockade(self, actor, world_state, target, params):
        r = self.rules["blockade"]
        res = ActionResolution()
        target_chokepoint = params.get("chokepoint", "")

        if "hormuz" in target_chokepoint.lower():
            res.global_changes["strait_of_hormuz_open"] = False
            res.global_changes["oil_price"] = world_state.oil_price * r["oil_price_spike_pct"] / 100
        elif "mandeb" in target_chokepoint.lower() or "red_sea" in target_chokepoint.lower():
            res.global_changes["bab_el_mandeb_open"] = False
        elif "suez" in target_chokepoint.lower():
            res.global_changes["suez_canal_open"] = False

        res.escalation_delta = r["escalation_increase"]
        res.global_changes["escalation_level"] = r["escalation_increase"]
        res.consequence_summary = (
            f"{actor.actor_name} imposed blockade on {target_chokepoint or 'maritime routes'}. "
            f"Oil price impact: +{r['oil_price_spike_pct']:.0f}%"
        )
        res.cascading_effects.append("global_shipping_disruption")
        return res

    def _handle_cyber_attack(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {
                "equipment_status": -0.05,
                "readiness": -0.03,
            }
            res.consequence_summary = f"{actor.actor_name} conducted cyber attack against {target.actor_name} infrastructure."
        res.escalation_delta = 1
        res.global_changes["escalation_level"] = 1
        return res

    def _handle_naval_operation(self, actor, world_state, target, params):
        res = ActionResolution()
        res.state_changes[actor.actor_id] = {"readiness": 0.02}
        res.escalation_delta = 1
        res.global_changes["escalation_level"] = 1
        res.consequence_summary = f"{actor.actor_name} conducted naval operations in {params.get('region', 'contested waters')}."
        return res

    def _handle_sanctions(self, actor, world_state, target, params):
        r = self.rules["sanctions"]
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {
                "sanctions_pressure": r["sanctions_pressure_increase"],
                "gdp_impact": r["gdp_impact_per_round"],
                "trade_disruption": 0.1,
            }
            res.consequence_summary = f"{actor.actor_name} imposed sanctions on {target.actor_name}."
            res.state_changes[actor.actor_id] = {"international_support": 0.02}
        return res

    def _handle_cut_trade(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {"trade_disruption": 0.15, "gdp_impact": -0.3}
            res.state_changes[actor.actor_id] = {"trade_disruption": 0.05, "gdp_impact": -0.1}
            res.consequence_summary = f"{actor.actor_name} cut trade relations with {target.actor_name}."
        return res

    def _handle_oil_embargo(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {"oil_production": -0.2, "gdp_impact": -1.0}
            res.global_changes["oil_price"] = world_state.oil_price * 0.1  # +10%
            res.consequence_summary = f"{actor.actor_name} imposed oil embargo on {target.actor_name}."
            res.cascading_effects.append("global_energy_price_shock")
        return res

    def _handle_freeze_assets(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {"currency_stability": -0.1, "gdp_impact": -0.3}
            res.consequence_summary = f"{actor.actor_name} froze {target.actor_name}'s financial assets."
        return res

    def _handle_arm_proxy(self, actor, world_state, target, params):
        res = ActionResolution()
        proxy_id = params.get("proxy_id", target.actor_id if target else None)
        if proxy_id:
            proxy = world_state.get_actor(proxy_id)
            if proxy:
                res.state_changes[proxy_id] = {
                    "force_strength": 3.0,
                    "missile_inventory": 0.05,
                    "equipment_status": 0.05,
                }
                res.state_changes[actor.actor_id] = {"missile_inventory": -0.02}
                res.consequence_summary = f"{actor.actor_name} supplied weapons to {proxy.actor_name}."
                res.escalation_delta = 1
                res.global_changes["escalation_level"] = 1
        return res

    def _handle_proxy_attack(self, actor, world_state, target, params):
        r = self.rules["proxy_attack"]
        res = ActionResolution()
        if target:
            damage_mult = actor.force_strength / 50.0
            res.state_changes[target.actor_id] = {
                "force_strength": -r["base_force_reduction"] * damage_mult,
                "casualties": int(r["base_casualties"] * damage_mult),
            }
            res.escalation_delta = r["escalation_increase"]
            res.global_changes["escalation_level"] = r["escalation_increase"]
            res.consequence_summary = f"{actor.actor_name} launched proxy attack against {target.actor_name}."
        return res

    def _handle_proxy_ceasefire(self, actor, world_state, target, params):
        res = ActionResolution()
        res.escalation_delta = -1
        res.global_changes["escalation_level"] = -1
        res.consequence_summary = f"{actor.actor_name} declared ceasefire in proxy operations."
        res.state_changes[actor.actor_id] = {"international_support": 0.03}
        return res

    def _handle_negotiation(self, actor, world_state, target, params):
        r = self.rules["negotiation"]
        res = ActionResolution()
        res.escalation_delta = -r["escalation_decrease"]
        res.global_changes["escalation_level"] = -r["escalation_decrease"]
        res.state_changes[actor.actor_id] = {
            "domestic_approval": r["domestic_approval_change"],
            "international_support": r["international_support_change"],
        }
        target_name = target.actor_name if target else "opposing parties"
        res.consequence_summary = f"{actor.actor_name} proposed negotiations with {target_name}."
        return res

    def _handle_ultimatum(self, actor, world_state, target, params):
        res = ActionResolution()
        res.escalation_delta = 2
        res.global_changes["escalation_level"] = 2
        res.state_changes[actor.actor_id] = {"domestic_approval": 0.03}
        deadline = params.get("deadline", "unspecified")
        target_name = target.actor_name if target else "opposing parties"
        res.consequence_summary = f"{actor.actor_name} issued ultimatum to {target_name}. Deadline: {deadline}."
        return res

    def _handle_treaty(self, actor, world_state, target, params):
        res = ActionResolution()
        res.escalation_delta = -3
        res.global_changes["escalation_level"] = -3
        res.state_changes[actor.actor_id] = {"international_support": 0.1}
        if target:
            res.state_changes[target.actor_id] = {"international_support": 0.1}
        res.consequence_summary = f"{actor.actor_name} signed treaty/agreement."
        return res

    def _handle_break_alliance(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {"alliance_cohesion": -0.2}
            res.state_changes[actor.actor_id] = {"alliance_cohesion": -0.1}
            res.consequence_summary = f"{actor.actor_name} broke alliance with {target.actor_name}."
        res.escalation_delta = 1
        res.global_changes["escalation_level"] = 1
        return res

    def _handle_mediation(self, actor, world_state, target, params):
        res = ActionResolution()
        res.escalation_delta = -1
        res.global_changes["escalation_level"] = -1
        res.state_changes[actor.actor_id] = {"international_support": 0.05}
        res.consequence_summary = f"{actor.actor_name} requested international mediation."
        return res

    def _handle_un_vote(self, actor, world_state, target, params):
        res = ActionResolution()
        resolution_text = params.get("resolution", "unspecified resolution")
        res.consequence_summary = f"{actor.actor_name} voted on UN resolution: {resolution_text}."
        res.state_changes[actor.actor_id] = {"international_support": 0.02}
        return res

    def _handle_public_statement(self, actor, world_state, target, params):
        res = ActionResolution()
        statement = params.get("statement", "")
        res.state_changes[actor.actor_id] = {"narrative_control": 0.03}
        res.consequence_summary = f"{actor.actor_name} issued public statement: {statement[:100]}"
        # Public commitments constrain future actions
        if statement:
            actor.public_commitments.append(statement[:200])
        return res

    def _handle_propaganda(self, actor, world_state, target, params):
        r = self.rules["propaganda"]
        res = ActionResolution()
        res.state_changes[actor.actor_id] = {
            "narrative_control": r["narrative_control_boost"],
            "propaganda_effectiveness": 0.05,
        }
        if target:
            res.state_changes[target.actor_id] = {
                "domestic_approval": r["target_domestic_approval_change"],
                "narrative_control": -0.03,
            }
        res.consequence_summary = f"{actor.actor_name} launched propaganda campaign."
        return res

    def _handle_disinfo(self, actor, world_state, target, params):
        res = ActionResolution()
        res.state_changes[actor.actor_id] = {"narrative_control": 0.05}
        if target:
            res.state_changes[target.actor_id] = {
                "domestic_approval": -0.03,
                "international_support": -0.02,
            }
        res.consequence_summary = f"{actor.actor_name} launched disinformation campaign."
        return res

    def _handle_gather_intel(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            # Increase visibility of target
            current_vis = actor.intel_visibility.get(target.actor_id, 0.3)
            new_vis = min(1.0, current_vis + 0.15)
            actor.intel_visibility[target.actor_id] = new_vis
            res.consequence_summary = f"{actor.actor_name} gathered intelligence on {target.actor_name}. Visibility: {new_vis:.0%}"
        return res

    def _handle_covert_op(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            res.state_changes[target.actor_id] = {
                "readiness": -0.03,
                "equipment_status": -0.02,
            }
            res.consequence_summary = f"{actor.actor_name} conducted covert operation against {target.actor_name}."
        res.escalation_delta = 1
        res.global_changes["escalation_level"] = 1
        return res

    def _handle_cyber_espionage(self, actor, world_state, target, params):
        res = ActionResolution()
        if target:
            current_vis = actor.intel_visibility.get(target.actor_id, 0.3)
            actor.intel_visibility[target.actor_id] = min(1.0, current_vis + 0.2)
            res.consequence_summary = f"{actor.actor_name} conducted cyber espionage against {target.actor_name}."
        return res

    def _handle_passive(self, actor, world_state, target, params):
        res = ActionResolution()
        res.state_changes[actor.actor_id] = {"readiness": 0.02}
        res.consequence_summary = f"{actor.actor_name} held position and assessed the situation."
        return res

    def _handle_backchannel(self, actor, world_state, target, params):
        res = ActionResolution()
        res.escalation_delta = -1
        res.global_changes["escalation_level"] = -1
        target_name = target.actor_name if target else "parties"
        res.consequence_summary = f"{actor.actor_name} engaged in backchannel communication with {target_name}."
        return res

    # --- Escalation Guardrails ---

    def _apply_escalation_guardrails(
        self,
        resolution: ActionResolution,
        action_type: ActionType,
        actor: ActorState,
        world_state: WorldState,
    ) -> ActionResolution:
        """Apply escalation guardrails (Rivera et al. FACCt 2024 findings).

        Key mitigations:
        - Escalation cost multiplier increases with current escalation level
        - High escalation levels dampen further escalation
        - De-escalation opportunities counteract LLM escalation tendency
        """
        r = self.rules["escalation"]

        if action_type in ESCALATORY_ACTIONS and resolution.escalation_delta > 0:
            # Cost multiplier: harder to escalate when already high
            current_level = world_state.escalation_level
            if current_level >= 7:
                # Dampen escalation at high levels
                resolution.escalation_delta = max(1, resolution.escalation_delta - 1)
                resolution.global_changes["escalation_level"] = resolution.escalation_delta

            # Casualty feedback: high casualties make domestic approval drop
            if actor.actor_type in ("NationState",):
                sensitivity = r.get("cost_multiplier_per_level", 1.5)
                approval_cost = -0.01 * current_level * (1 / max(0.1, actor.martyrdom_willingness + 0.5))
                if actor.actor_id not in resolution.state_changes:
                    resolution.state_changes[actor.actor_id] = {}
                resolution.state_changes[actor.actor_id]["domestic_approval"] = (
                    resolution.state_changes.get(actor.actor_id, {}).get("domestic_approval", 0) + approval_cost
                )

        return resolution

    # --- Cascading Effects ---

    def _apply_cascading_effects(self, resolution: ActionResolution, world_state: WorldState):
        """Apply cascading second-order effects."""
        for effect in resolution.cascading_effects:
            if effect == "global_shipping_disruption":
                # All actors with trade dependencies take economic hit
                for actor in world_state.actors.values():
                    if actor.trade_disruption < 0.8:
                        actor.trade_disruption = min(1.0, actor.trade_disruption + 0.05)
                        actor.gdp_impact -= 0.1

            elif effect == "global_energy_price_shock":
                # Oil importers hurt, oil exporters benefit (short term)
                world_state.global_risk_index = min(1.0, world_state.global_risk_index + 0.1)

            elif effect == "civilian_casualty_narrative_impact":
                # Humanitarian impact increases
                world_state.humanitarian_impact = min(
                    1.0, world_state.humanitarian_impact + 0.05
                )
