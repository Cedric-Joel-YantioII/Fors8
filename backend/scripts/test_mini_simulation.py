#!/usr/bin/env python3
"""
Mini simulation test: 3 actors (USA, Israel, Iran), 3 rounds.
Uses OpenRouter free model with rate-limit-aware delays.
Tests the full OODA loop + consequence engine end-to-end.
"""

import os
import sys
import json
import re
import time
import logging

backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

os.environ['LLM_API_KEY'] = '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'
os.environ['LLM_BASE_URL'] = 'https://openrouter.ai/api/v1'
os.environ['LLM_MODEL_NAME'] = 'google/gemma-3-27b-it:free'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('test_sim')

from openai import OpenAI

# Direct import to bypass Flask dependency in app/__init__.py
import importlib.util
import types

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Load world_state directly
ws_mod = load_module('world_state', os.path.join(backend_dir, 'app/services/world_state.py'))

# Load consequence_engine with patched import
ce_source = open(os.path.join(backend_dir, 'app/services/consequence_engine.py')).read()
ce_source = ce_source.replace('from .world_state import', 'from world_state import')
ce_mod = types.ModuleType('consequence_engine')
sys.modules['world_state'] = ws_mod
exec(compile(ce_source, 'consequence_engine.py', 'exec'), ce_mod.__dict__)

ActionType = ws_mod.ActionType
ActorState = ws_mod.ActorState
ActorTier = ws_mod.ActorTier
WorldState = ws_mod.WorldState
GeopoliticalEvent = ws_mod.GeopoliticalEvent
ActionDomain = ws_mod.ActionDomain
ACTION_DOMAIN_MAP = ws_mod.ACTION_DOMAIN_MAP
ConsequenceEngine = ce_mod.ConsequenceEngine


def clean(text):
    if not text:
        return ""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text).strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def call_llm_with_retry(client, model, messages, max_tokens=500, temperature=0.5, retries=5):
    """Call LLM with exponential backoff for rate limits."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content
            if content:
                return clean(content)
            logger.warning(f"Empty response, attempt {attempt+1}/{retries}")
        except Exception as e:
            err = str(e)
            if '429' in err:
                wait = 5 * (attempt + 1)
                logger.info(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"LLM error: {err[:200]}")
                time.sleep(3)
    return None


def get_actor_decision(client, model, actor, world_state, available_actions_str):
    """Get one actor's decision for this round."""
    situation = world_state.get_situation_briefing(actor.actor_id)

    prompt = f"""You are simulating {actor.actor_name}'s strategic decision-making in a war scenario.
Output ONLY valid JSON. No explanation, no markdown.

JSON format:
{{"situation_assessment": "1-2 sentences", "actions": [{{"action_type": "action_name", "target_actor_id": "target_id_or_null", "reasoning": "1 sentence why"}}]}}

You may choose 1-2 actions from: {available_actions_str}

Actor state:
- Force strength: {actor.force_strength:.0f}/100
- Domestic approval: {actor.domestic_approval:.0%}
- Casualties: {actor.casualties}

Current situation:
- Round: {world_state.round_num}
- Escalation: {world_state.escalation_level}/10
- Oil price: ${world_state.oil_price:.0f}
- Hormuz: {'OPEN' if world_state.strait_of_hormuz_open else 'CLOSED'}
- Phase: {world_state.phase}

Other actors visible:
{json.dumps({k: v for k, v in situation.get('other_actors', {}).items()}, indent=2, default=str)}

Recent events:
{json.dumps(situation.get('recent_events', [])[:5], indent=2, default=str)}

What does {actor.actor_name} do? Output JSON only."""

    content = call_llm_with_retry(client, model, [{"role": "user", "content": prompt}], max_tokens=400)
    if not content:
        return [{"action_type": "hold_position", "target_actor_id": None, "reasoning": "LLM unavailable"}]

    try:
        parsed = json.loads(content)
        return parsed.get("actions", [{"action_type": "hold_position", "target_actor_id": None, "reasoning": "parse fallback"}])
    except json.JSONDecodeError:
        logger.warning(f"JSON parse failed for {actor.actor_name}: {content[:200]}")
        return [{"action_type": "hold_position", "target_actor_id": None, "reasoning": "JSON parse fallback"}]


def main():
    client = OpenAI(api_key=os.environ['LLM_API_KEY'], base_url=os.environ['LLM_BASE_URL'])
    model = os.environ['LLM_MODEL_NAME']
    ce = ConsequenceEngine()

    # Build initial world state with 3 actors
    ws = WorldState()
    ws.escalation_level = 7
    ws.oil_price = 119.0
    ws.strait_of_hormuz_open = False
    ws.phase = "conflict"
    ws.active_conflicts = ["US/Israel vs Iran (Operation Epic Fury)"]

    ws.actors["usa"] = ActorState(
        actor_id="usa", actor_name="USA", actor_type="NationState",
        tier=ActorTier.STRATEGIC, force_strength=95, domestic_approval=0.55,
        risk_tolerance=0.6, negotiation_willingness=0.6, casualty_threshold=0.3,
        intel_visibility={"israel": 0.9, "iran": 0.5},
    )
    ws.actors["israel"] = ActorState(
        actor_id="israel", actor_name="Israel", actor_type="NationState",
        tier=ActorTier.STRATEGIC, force_strength=80, domestic_approval=0.55,
        interceptor_inventory=0.15, risk_tolerance=0.7, negotiation_willingness=0.3,
        intel_visibility={"usa": 0.9, "iran": 0.6},
    )
    ws.actors["iran"] = ActorState(
        actor_id="iran", actor_name="Iran", actor_type="NationState",
        tier=ActorTier.STRATEGIC, force_strength=45, domestic_approval=0.5,
        missile_inventory=0.5, martyrdom_willingness=0.8, eschatological_factor=0.7,
        risk_tolerance=0.8, negotiation_willingness=0.3, casualty_threshold=0.8,
        casualties=5300,
        intel_visibility={"usa": 0.4, "israel": 0.5},
    )

    available = "launch_strike, missile_launch, air_strike, deploy_forces, defend_position, propose_negotiation, issue_ultimatum, public_statement, hold_position, backchannel_communication, blockade, impose_sanctions"

    max_rounds = 3
    print(f"\n{'='*60}")
    print(f"MINI SIMULATION: 3 actors, {max_rounds} rounds")
    print(f"Initial state: Escalation {ws.escalation_level}/10, Oil ${ws.oil_price}")
    print(f"{'='*60}\n")

    for round_num in range(1, max_rounds + 1):
        ws.round_num = round_num
        ws.simulated_time = f"2026-03-{22+round_num}T00:00:00Z"

        print(f"\n--- ROUND {round_num} | Escalation: {ws.escalation_level}/10 | Oil: ${ws.oil_price:.0f} | Phase: {ws.phase} ---")

        # Check termination
        should_stop, reason = ce.check_termination(ws, max_rounds)
        if should_stop:
            print(f"  TERMINATED: {reason}")
            break

        # Each actor decides
        for actor_id in ["usa", "israel", "iran"]:
            actor = ws.actors[actor_id]
            print(f"\n  [{actor.actor_name}] Requesting decision...")

            actions = get_actor_decision(client, model, actor, ws, available)

            for action_data in actions[:2]:  # Max 2 actions per actor
                action_type_str = action_data.get("action_type", "hold_position")
                target_id = action_data.get("target_actor_id")
                reasoning = action_data.get("reasoning", "")

                try:
                    action_type = ActionType(action_type_str)
                except ValueError:
                    action_type = ActionType.HOLD_POSITION

                target = ws.actors.get(target_id) if target_id else None

                # Resolve
                resolution = ce.resolve_action(action_type, actor, ws, target)
                ce.apply_resolution(resolution, ws)

                # Log
                event = GeopoliticalEvent(
                    round_num=round_num,
                    timestamp=ws.simulated_time,
                    actor_id=actor_id,
                    actor_name=actor.actor_name,
                    action_type=action_type,
                    action_domain=ACTION_DOMAIN_MAP.get(action_type, ActionDomain.PASSIVE),
                    target_actor_id=target_id,
                    target_actor_name=target.actor_name if target else None,
                    reasoning=reasoning,
                    consequence_summary=resolution.consequence_summary,
                    escalation_delta=resolution.escalation_delta,
                )
                ws.events.append(event)

                esc_indicator = f" [ESC +{resolution.escalation_delta}]" if resolution.escalation_delta > 0 else (f" [ESC {resolution.escalation_delta}]" if resolution.escalation_delta < 0 else "")
                print(f"    -> {action_type.value} {('-> ' + target.actor_name) if target else ''}{esc_indicator}")
                print(f"       Reasoning: {reasoning[:100]}")
                print(f"       Result: {resolution.consequence_summary[:120]}")

            # Rate limit pause between actors
            time.sleep(4)

        # Update phase
        level = ws.escalation_level
        if level <= 2: ws.phase = "de-escalation"
        elif level <= 4: ws.phase = "tensions"
        elif level <= 6: ws.phase = "crisis"
        elif level <= 8: ws.phase = "conflict"
        else: ws.phase = "escalation-critical"

    # Final state
    print(f"\n{'='*60}")
    print(f"SIMULATION COMPLETE")
    print(f"{'='*60}")
    print(f"Final escalation: {ws.escalation_level}/10")
    print(f"Final phase: {ws.phase}")
    print(f"Oil price: ${ws.oil_price:.1f}")
    print(f"Hormuz: {'OPEN' if ws.strait_of_hormuz_open else 'CLOSED'}")
    print(f"Total events: {len(ws.events)}")
    print()
    for actor_id, actor in ws.actors.items():
        print(f"  {actor.actor_name}:")
        print(f"    Force: {actor.force_strength:.1f}/100")
        print(f"    Casualties: {actor.casualties}")
        print(f"    Approval: {actor.domestic_approval:.1%}")
        print(f"    Interceptors: {actor.interceptor_inventory:.1%}")
        print(f"    Missiles: {actor.missile_inventory:.1%}")
    print()

    # Verify assertions
    assert len(ws.events) > 0, "No events generated"
    assert ws.round_num > 0, "No rounds completed"
    print("INTEGRATION TEST PASSED")


if __name__ == "__main__":
    main()
