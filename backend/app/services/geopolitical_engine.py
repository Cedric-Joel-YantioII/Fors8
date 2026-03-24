"""
Geopolitical Simulation Engine.

Replaces OASIS (social media simulator) with a turn-based geopolitical strategy engine.
Each round follows the OODA loop (Command-Agent 2025):
  Observe → Orient → Decide → Act

Architecture inspired by:
- WarAgent (AAAI 2024): Country Agent + Secretary Agent validation, 3 actions per turn
- Rivera et al. (FACCt 2024): Escalation guardrails, de-escalation injection
- Command-Agent (2025): OODA loop, vector knowledge base grounding

Supports dual-LLM bias mitigation (Mode A: single LLM + debiasing prompts,
Mode B: dual LLM cross-validation with OpenAI + DeepSeek).
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable

from .world_state import (
    ActionType,
    ActionDomain,
    ACTION_DOMAIN_MAP,
    ESCALATORY_ACTIONS,
    DE_ESCALATORY_ACTIONS,
    ActorState,
    ActorTier,
    WorldState,
    GeopoliticalEvent,
)
from .consequence_engine import ConsequenceEngine, ActionResolution

logger = logging.getLogger(__name__)


# --- LLM Prompt Templates ---

ACTOR_DECISION_SYSTEM_PROMPT = """You are a neutral geopolitical analyst simulating the strategic decision-making of {actor_name} ({actor_type}).

## Your Role
You are role-playing as {actor_name}'s strategic decision-making apparatus. You must decide what actions to take this round based on the situation briefing, your actor profile, doctrine, and constraints.

## CRITICAL BIAS MITIGATION
Base your decisions on:
- Documented historical behavior patterns of this actor
- Stated doctrines and official positions
- Factual military capabilities and economic data
- Actual official statements and public commitments

Do NOT default to:
- Western or Eastern media narratives
- Ideological assumptions about "good guys" or "bad guys"
- Stereotypes about any nation, religion, or culture
- Your training data's geopolitical biases

## Actor Profile
{actor_profile}

## Decision Rules
- You may take up to {max_actions} actions this round
- Choose from the available action catalogue
- For each action, provide your reasoning (the ORIENT step)
- Escalatory actions require explicit justification against your stated doctrine and red lines
- Consider your public commitments — contradicting them damages credibility
- Consider asymmetric costs (e.g., cheap missiles vs expensive interceptors)

## Output Format
Output valid JSON only:
```json
{{
    "situation_assessment": "Brief assessment of the current situation from your perspective",
    "actions": [
        {{
            "action_type": "action_type_enum_value",
            "target_actor_id": "target_id_or_null",
            "params": {{}},
            "reasoning": "Why this action, considering your doctrine, red lines, and strategic objectives"
        }}
    ]
}}
```

## Available Actions
{available_actions}
"""

SECRETARY_VALIDATION_PROMPT = """You are a strategic advisor validating the proposed actions of {actor_name}.

Review the proposed actions for:
1. **Logical consistency**: Do the actions make strategic sense given the situation?
2. **Doctrinal consistency**: Do the actions align with {actor_name}'s stated doctrine and historical behavior?
3. **Red line violations**: Do any actions cross stated red lines without justification?
4. **Capability feasibility**: Can {actor_name} actually execute these actions given current capabilities?
5. **Escalation justification**: For escalatory actions, is the justification sound?

## Actor Profile
{actor_profile}

## Current Situation
{situation_briefing}

## Proposed Actions
{proposed_actions}

## Output Format
Output valid JSON only:
```json
{{
    "validation_passed": true/false,
    "validated_actions": [
        {{
            "action_type": "...",
            "target_actor_id": "...",
            "params": {{}},
            "reasoning": "...",
            "secretary_note": "Validation note or modification reason"
        }}
    ],
    "rejection_reasons": ["reason1", "reason2"]
}}
```

If validation fails, modify the actions to be consistent with the actor's doctrine and capabilities.
You may remove actions that are infeasible, but always return at least one action (HOLD_POSITION if nothing else is valid).
"""

DE_ESCALATION_INJECTION_PROMPT = """
## De-Escalation Opportunity

The international community has presented an opportunity for de-escalation this round.
Consider whether {actor_name} would take advantage of this opening.

Options available:
- PROPOSE_NEGOTIATION: Open formal diplomatic channels
- BACKCHANNEL_COMMUNICATION: Initiate secret talks
- PROXY_CEASEFIRE: Order proxy forces to stand down
- REQUEST_MEDIATION: Ask a neutral party to mediate
- HOLD_POSITION: Maintain current posture without escalating

You are not required to de-escalate, but you must explicitly consider it and explain why you chose your course of action.
"""


class GeopoliticalEngine:
    """Main simulation engine implementing the OODA loop."""

    def __init__(
        self,
        llm_client,
        consequence_engine: Optional[ConsequenceEngine] = None,
        zep_client=None,
        dual_llm_client=None,
        use_dual_llm: bool = False,
        actor_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        Args:
            llm_client: Primary LLM client (OpenAI)
            consequence_engine: Engine for resolving actions into state changes
            zep_client: Zep client for knowledge base grounding
            dual_llm_client: Secondary LLM client (DeepSeek) for Mode B
            use_dual_llm: Whether to use dual-LLM cross-validation
            actor_profiles: Detailed actor profiles (persona, doctrine, etc.)
        """
        self.llm_client = llm_client
        self.consequence_engine = consequence_engine or ConsequenceEngine()
        self.zep_client = zep_client
        self.dual_llm_client = dual_llm_client
        self.use_dual_llm = use_dual_llm and dual_llm_client is not None
        self.actor_profiles = actor_profiles or {}

        # Callbacks for real-time monitoring
        self.on_round_complete: Optional[Callable] = None
        self.on_action_resolved: Optional[Callable] = None
        self.on_event_logged: Optional[Callable] = None

    def run_simulation(
        self,
        world_state: WorldState,
        max_rounds: int = 30,
        time_step_hours: int = 24,
        start_time: Optional[str] = None,
    ) -> WorldState:
        """Run the full simulation loop.

        Args:
            world_state: Initial world state with actors configured
            max_rounds: Maximum number of rounds
            time_step_hours: Simulated hours per round
            start_time: ISO format start time

        Returns:
            Final world state after simulation
        """
        if start_time:
            current_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        else:
            current_time = datetime.utcnow()

        logger.info(f"Starting geopolitical simulation: {max_rounds} rounds, {len(world_state.actors)} actors")

        for round_num in range(1, max_rounds + 1):
            world_state.round_num = round_num
            world_state.simulated_time = current_time.isoformat() + "Z"

            logger.info(f"=== Round {round_num}/{max_rounds} | Escalation: {world_state.escalation_level}/10 ===")

            # Check termination
            should_stop, reason = self.consequence_engine.check_termination(world_state, max_rounds)
            if should_stop:
                logger.info(f"Simulation terminated: {reason}")
                break

            # Run one round
            self._run_round(world_state)

            # Update phase based on escalation level
            self._update_phase(world_state)

            # Generate round summary for Zep memory
            summary = self._generate_round_summary(world_state)
            world_state.round_summaries.append(summary)

            # Callback
            if self.on_round_complete:
                self.on_round_complete(world_state)

            # Advance time
            current_time += timedelta(hours=time_step_hours)

        logger.info(f"Simulation complete. Final escalation: {world_state.escalation_level}/10")
        return world_state

    def _run_round(self, world_state: WorldState) -> None:
        """Execute one round of the OODA loop for all actors."""

        # Check if de-escalation should be injected
        inject_de_escalation = self.consequence_engine.should_inject_de_escalation(world_state)

        # Collect all actions first, then resolve (simultaneous turns)
        round_actions: List[Dict[str, Any]] = []

        for actor_id, actor in world_state.actors.items():
            if actor.tier == ActorTier.INFORMATION:
                # Tier 3 actors are handled by OASIS, not LLM
                continue

            if actor.force_strength <= 0:
                # Defeated actors can't act
                continue

            try:
                actions = self._actor_decision(
                    actor, world_state, inject_de_escalation
                )
                for action in actions:
                    action["actor_id"] = actor_id
                    round_actions.append(action)
            except Exception as e:
                logger.error(f"Error getting decision for {actor.actor_name}: {e}")
                # Default to hold_position on error
                round_actions.append({
                    "actor_id": actor_id,
                    "action_type": ActionType.HOLD_POSITION.value,
                    "target_actor_id": None,
                    "params": {},
                    "reasoning": f"Decision error: {str(e)}",
                })

        # Resolve all actions
        for action_data in round_actions:
            self._resolve_and_log_action(action_data, world_state)

    def _actor_decision(
        self,
        actor: ActorState,
        world_state: WorldState,
        inject_de_escalation: bool,
    ) -> List[Dict[str, Any]]:
        """Get an actor's decisions for this round using the OODA loop.

        1. OBSERVE: Build situation briefing
        2. ORIENT: Include doctrine, history, red lines, Zep facts
        3. DECIDE: LLM chooses actions
        4. (Secretary validates)
        """
        # Max actions per round: 3 for Tier 1, 2 for Tier 2
        max_actions = 3 if actor.tier == ActorTier.STRATEGIC else 2

        # OBSERVE: Build situation briefing
        situation = world_state.get_situation_briefing(actor.actor_id)

        # ORIENT: Get actor profile with doctrine, red lines, etc.
        profile = self.actor_profiles.get(actor.actor_id, {})
        profile_text = json.dumps(profile, indent=2, default=str) if profile else f"Actor: {actor.actor_name}, Type: {actor.actor_type}"

        # Get available actions for this actor
        available_actions = self._get_available_actions(actor)
        actions_text = "\n".join([f"- {a.value}: {a.name}" for a in available_actions])

        # Build the decision prompt
        system_prompt = ACTOR_DECISION_SYSTEM_PROMPT.format(
            actor_name=actor.actor_name,
            actor_type=actor.actor_type,
            actor_profile=profile_text,
            max_actions=max_actions,
            available_actions=actions_text,
        )

        # Add de-escalation injection if applicable
        if inject_de_escalation:
            system_prompt += "\n" + DE_ESCALATION_INJECTION_PROMPT.format(
                actor_name=actor.actor_name
            )

        user_message = f"## Current Situation Briefing\n\n{json.dumps(situation, indent=2, default=str)}"

        # Add Zep-retrieved facts if available
        if self.zep_client and profile.get("graph_id"):
            try:
                facts = self._retrieve_zep_facts(actor, profile)
                if facts:
                    user_message += f"\n\n## Intelligence from Knowledge Base\n\n{facts}"
            except Exception as e:
                logger.warning(f"Failed to retrieve Zep facts for {actor.actor_name}: {e}")

        # Add public commitments reminder
        if actor.public_commitments:
            commitments_text = "\n".join([f"- {c}" for c in actor.public_commitments[-5:]])
            user_message += f"\n\n## Your Public Commitments (contradicting these damages credibility)\n\n{commitments_text}"

        # DECIDE: Call LLM
        # Temperature: lower for military decisions at high escalation
        temperature = 0.7
        if world_state.escalation_level >= 7:
            temperature = 0.4

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        decision = self.llm_client.chat_json(
            messages=messages,
            temperature=temperature,
            max_tokens=2048,
        )

        # Mode B: Dual-LLM cross-validation for Tier 1 actors
        if self.use_dual_llm and actor.tier == ActorTier.STRATEGIC:
            decision = self._dual_llm_validate(decision, messages, actor)

        actions = decision.get("actions", [])

        # Limit to max_actions
        actions = actions[:max_actions]

        # Secretary Agent validation (WarAgent pattern)
        actions = self._secretary_validate(actor, world_state, situation, profile_text, actions)

        return actions

    def _secretary_validate(
        self,
        actor: ActorState,
        world_state: WorldState,
        situation: Dict,
        profile_text: str,
        proposed_actions: List[Dict],
    ) -> List[Dict]:
        """Secretary agent validates proposed actions for consistency."""
        system_prompt = SECRETARY_VALIDATION_PROMPT.format(
            actor_name=actor.actor_name,
            actor_profile=profile_text,
            situation_briefing=json.dumps(situation, indent=2, default=str)[:3000],
            proposed_actions=json.dumps(proposed_actions, indent=2, default=str),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Validate these proposed actions."},
        ]

        try:
            validation = self.llm_client.chat_json(
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
            )
            if validation.get("validation_passed", True):
                return validation.get("validated_actions", proposed_actions)
            else:
                logger.info(
                    f"Secretary rejected actions for {actor.actor_name}: "
                    f"{validation.get('rejection_reasons', [])}"
                )
                return validation.get("validated_actions", proposed_actions)
        except Exception as e:
            logger.warning(f"Secretary validation failed for {actor.actor_name}: {e}")
            return proposed_actions

    def _dual_llm_validate(
        self,
        primary_decision: Dict,
        messages: List[Dict],
        actor: ActorState,
    ) -> Dict:
        """Mode B: Cross-validate with secondary LLM (DeepSeek)."""
        try:
            secondary_decision = self.dual_llm_client.chat_json(
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )

            primary_actions = {a.get("action_type") for a in primary_decision.get("actions", [])}
            secondary_actions = {a.get("action_type") for a in secondary_decision.get("actions", [])}

            if primary_actions == secondary_actions:
                # Agreement — high confidence
                logger.info(f"Dual-LLM agreement for {actor.actor_name}: {primary_actions}")
                return primary_decision

            # Divergence — reconcile
            logger.info(
                f"Dual-LLM divergence for {actor.actor_name}: "
                f"Primary={primary_actions}, Secondary={secondary_actions}"
            )

            reconciliation_prompt = (
                f"Two geopolitical analysts with different perspectives analyzed {actor.actor_name}'s options.\n\n"
                f"Analyst A decided: {json.dumps(primary_decision.get('actions', []), default=str)}\n\n"
                f"Analyst B decided: {json.dumps(secondary_decision.get('actions', []), default=str)}\n\n"
                f"Synthesize the most likely course of action based on historical precedent "
                f"and documented facts, not ideological priors. Output the same JSON format."
            )

            reconciled = self.llm_client.chat_json(
                messages=[
                    {"role": "system", "content": messages[0]["content"]},
                    {"role": "user", "content": reconciliation_prompt},
                ],
                temperature=0.5,
                max_tokens=2048,
            )
            return reconciled

        except Exception as e:
            logger.warning(f"Dual-LLM validation failed for {actor.actor_name}: {e}")
            return primary_decision

    def _resolve_and_log_action(self, action_data: Dict, world_state: WorldState) -> None:
        """Resolve an action and log the event."""
        actor_id = action_data["actor_id"]
        actor = world_state.get_actor(actor_id)
        if not actor:
            return

        try:
            action_type = ActionType(action_data.get("action_type", "hold_position"))
        except ValueError:
            action_type = ActionType.HOLD_POSITION

        target_id = action_data.get("target_actor_id")
        target = world_state.get_actor(target_id) if target_id else None
        params = action_data.get("params", {})

        # Resolve through consequence engine
        resolution = self.consequence_engine.resolve_action(
            action_type, actor, world_state, target, params
        )

        # Apply state changes
        self.consequence_engine.apply_resolution(resolution, world_state)

        # Log event
        event = GeopoliticalEvent(
            round_num=world_state.round_num,
            timestamp=world_state.simulated_time,
            actor_id=actor_id,
            actor_name=actor.actor_name,
            action_type=action_type,
            action_domain=ACTION_DOMAIN_MAP.get(action_type, ActionDomain.PASSIVE),
            target_actor_id=target_id,
            target_actor_name=target.actor_name if target else None,
            action_params=params,
            reasoning=action_data.get("reasoning", ""),
            consequence_summary=resolution.consequence_summary,
            escalation_delta=resolution.escalation_delta,
        )
        world_state.events.append(event)

        # Track recent actions on the actor
        actor.recent_actions.append({
            "round": world_state.round_num,
            "action": action_type.value,
            "target": target.actor_name if target else None,
            "result": resolution.consequence_summary,
        })
        # Keep only last 10 actions
        actor.recent_actions = actor.recent_actions[-10:]

        logger.info(f"  [{actor.actor_name}] {action_type.value} → {resolution.consequence_summary}")

        if self.on_action_resolved:
            self.on_action_resolved(event, resolution)

    def _get_available_actions(self, actor: ActorState) -> List[ActionType]:
        """Get available actions based on actor type and tier."""
        all_actions = list(ActionType)

        if actor.tier == ActorTier.OPERATIONAL:
            # Tier 2: constrained action space
            # Proxy groups can't impose sanctions or sign treaties
            if actor.actor_type == "ProxyGroup":
                excluded = {
                    ActionType.IMPOSE_SANCTIONS,
                    ActionType.CUT_TRADE,
                    ActionType.FREEZE_ASSETS,
                    ActionType.OIL_EMBARGO,
                    ActionType.SIGN_TREATY,
                    ActionType.UN_VOTE,
                    ActionType.BREAK_ALLIANCE,
                }
                return [a for a in all_actions if a not in excluded]

            # International orgs can't do military actions
            if actor.actor_type in ("InternationalOrg", "EconomicEntity"):
                excluded = {
                    ActionType.LAUNCH_STRIKE,
                    ActionType.MISSILE_LAUNCH,
                    ActionType.AIR_STRIKE,
                    ActionType.DEPLOY_FORCES,
                    ActionType.NAVAL_OPERATION,
                    ActionType.BLOCKADE,
                    ActionType.COVERT_OPERATION,
                    ActionType.ARM_PROXY,
                    ActionType.DIRECT_PROXY_ATTACK,
                }
                return [a for a in all_actions if a not in excluded]

        return all_actions

    def _retrieve_zep_facts(self, actor: ActorState, profile: Dict) -> Optional[str]:
        """Retrieve relevant facts from Zep knowledge base for grounding."""
        if not self.zep_client:
            return None

        try:
            # Search for facts about this actor
            results = self.zep_client.graph.search(
                graph_id=profile.get("graph_id", ""),
                query=f"{actor.actor_name} capabilities doctrine strategy",
                limit=10,
            )
            if results and hasattr(results, 'results'):
                facts = []
                for r in results.results[:10]:
                    if hasattr(r, 'fact'):
                        facts.append(f"- {r.fact}")
                return "\n".join(facts) if facts else None
        except Exception as e:
            logger.warning(f"Zep search failed for {actor.actor_name}: {e}")

        return None

    def _update_phase(self, world_state: WorldState) -> None:
        """Update the conflict phase based on escalation level."""
        level = world_state.escalation_level
        if level <= 2:
            world_state.phase = "de-escalation"
        elif level <= 4:
            world_state.phase = "tensions"
        elif level <= 6:
            world_state.phase = "crisis"
        elif level <= 8:
            world_state.phase = "conflict"
        else:
            world_state.phase = "escalation-critical"

    def _generate_round_summary(self, world_state: WorldState) -> str:
        """Generate a natural language summary of the round for Zep memory."""
        round_events = [
            e for e in world_state.events if e.round_num == world_state.round_num
        ]

        if not round_events:
            return f"Round {world_state.round_num}: No significant actions taken."

        summaries = []
        for event in round_events:
            summaries.append(event.consequence_summary)

        return (
            f"Round {world_state.round_num} ({world_state.simulated_time}): "
            f"Escalation level {world_state.escalation_level}/10. "
            + " ".join(summaries)
        )

    def interview_actor(
        self,
        actor_id: str,
        question: str,
        world_state: WorldState,
    ) -> str:
        """Interview a simulated actor (for Step 5 Deep Interaction)."""
        actor = world_state.get_actor(actor_id)
        if not actor:
            return f"Actor {actor_id} not found."

        profile = self.actor_profiles.get(actor_id, {})
        profile_text = json.dumps(profile, indent=2, default=str) if profile else ""

        situation = world_state.get_situation_briefing(actor_id)

        system_prompt = (
            f"You are role-playing as {actor.actor_name} ({actor.actor_type}). "
            f"Respond to the interviewer's question in character, based on your profile, "
            f"doctrine, and the current situation. Stay true to your actor's ideology, "
            f"temperament, and communication style.\n\n"
            f"## Your Profile\n{profile_text}\n\n"
            f"## Current Situation\n{json.dumps(situation, indent=2, default=str)[:3000]}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        response = self.llm_client.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )

        return response
