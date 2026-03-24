#!/usr/bin/env python3
"""
Geopolitical Conflict Simulation Runner.

Runs the geopolitical simulation engine as a subprocess, communicating
with the Flask backend via IPC (same pattern as run_reddit_simulation.py).

Usage:
    python run_geopolitical_simulation.py --config /path/to/simulation_config.json
"""

import os
import sys
import json
import argparse
import logging
import time
from datetime import datetime

# Add parent directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.config import Config
from app.utils.llm_client import LLMClient
from app.services.world_state import (
    ActorState, ActorTier, WorldState, ActionType, ActionDomain, ACTION_DOMAIN_MAP,
)
from app.services.consequence_engine import ConsequenceEngine
from app.services.geopolitical_engine import GeopoliticalEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('geopolitical_simulation')


def load_config(config_path: str) -> dict:
    """Load simulation configuration."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_actor_profiles(sim_dir: str) -> dict:
    """Load actor profiles from the simulation directory."""
    profiles_path = os.path.join(sim_dir, "actor_profiles.json")
    if not os.path.exists(profiles_path):
        logger.error(f"Actor profiles not found: {profiles_path}")
        return {}

    with open(profiles_path, 'r', encoding='utf-8') as f:
        profiles_list = json.load(f)

    return {p["actor_id"]: p for p in profiles_list}


def build_initial_world_state(config: dict, profiles: dict) -> WorldState:
    """Build the initial world state from config and profiles."""
    world_state = WorldState()

    # Set global initial conditions
    initial = config.get("initial_conditions", {})
    world_state.escalation_level = initial.get("escalation_level", 5)
    world_state.oil_price = initial.get("oil_price", 90.0)
    world_state.strait_of_hormuz_open = initial.get("strait_of_hormuz_open", False)
    world_state.bab_el_mandeb_open = initial.get("bab_el_mandeb_open", True)
    world_state.suez_canal_open = initial.get("suez_canal_open", True)
    world_state.active_conflicts = initial.get("active_conflicts", [])
    world_state.active_negotiations = initial.get("active_negotiations", [])
    world_state.nuclear_threshold_status = initial.get("nuclear_threshold_status", "warning")
    world_state.phase = initial.get("phase", "conflict")

    # Create actor states from profiles
    for actor_id, profile in profiles.items():
        tier_str = profile.get("tier", "operational")
        try:
            tier = ActorTier(tier_str)
        except ValueError:
            tier = ActorTier.OPERATIONAL

        actor = ActorState(
            actor_id=actor_id,
            actor_name=profile.get("actor_name", actor_id),
            actor_type=profile.get("actor_type", "Organization"),
            tier=tier,
            force_strength=float(profile.get("initial_force_strength", 50)),
            domestic_approval=float(profile.get("initial_domestic_approval", 0.5)),
            interceptor_inventory=float(profile.get("initial_interceptor_inventory", 1.0)),
            missile_inventory=float(profile.get("initial_missile_inventory", 1.0)),
            risk_tolerance=float(profile.get("risk_tolerance", 0.5)),
            escalation_threshold=float(profile.get("escalation_threshold", 0.5)),
            negotiation_willingness=float(profile.get("negotiation_willingness", 0.5)),
            casualty_threshold=float(profile.get("casualty_threshold", 0.5)),
            martyrdom_willingness=float(profile.get("martyrdom_willingness", 0.0)),
            eschatological_factor=float(profile.get("eschatological_factor", 0.0)),
            regime_survival_priority=float(profile.get("regime_survival_priority", 0.5)),
        )

        # Set intel visibility
        intel_vis = profile.get("initial_intel_visibility", {})
        for ally in profile.get("alliance_network", []):
            # Allies have high visibility by default
            ally_id = ally.lower().replace(" ", "_")
            intel_vis[ally_id] = intel_vis.get(ally_id, 0.8)
        for adversary in profile.get("adversaries", []):
            adversary_id = adversary.lower().replace(" ", "_")
            intel_vis[adversary_id] = intel_vis.get(adversary_id, 0.4)
        actor.intel_visibility = intel_vis

        world_state.actors[actor_id] = actor

    return world_state


def write_action_log(sim_dir: str, event: dict):
    """Append an action to the JSONL log file."""
    log_path = os.path.join(sim_dir, "geopolitical_actions.jsonl")
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Run geopolitical conflict simulation')
    parser.add_argument('--config', required=True, help='Path to simulation_config.json')
    parser.add_argument('--max-rounds', type=int, default=None, help='Override max rounds')
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    sim_dir = os.path.dirname(args.config)

    # Load actor profiles
    profiles = load_actor_profiles(sim_dir)
    if not profiles:
        logger.error("No actor profiles found. Run prepare_simulation first.")
        sys.exit(1)

    logger.info(f"Loaded {len(profiles)} actor profiles")

    # Determine max rounds
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 720)  # 30 days default
    hours_per_round = config.get("geo_time_step_hours", Config.GEO_TIME_STEP_HOURS)
    max_rounds = args.max_rounds or config.get("max_rounds", Config.GEO_DEFAULT_MAX_ROUNDS)

    # Build initial world state
    world_state = build_initial_world_state(config, profiles)
    logger.info(f"Initial world state: escalation={world_state.escalation_level}, "
                f"actors={len(world_state.actors)}, phase={world_state.phase}")

    # Initialize LLM client
    llm_client = LLMClient()

    # Initialize dual LLM if configured
    dual_llm_client = None
    use_dual_llm = config.get("dual_llm_enabled", Config.DUAL_LLM_ENABLED)
    if use_dual_llm and Config.DUAL_LLM_API_KEY:
        from openai import OpenAI
        dual_llm_client = LLMClient(
            api_key=Config.DUAL_LLM_API_KEY,
            base_url=Config.DUAL_LLM_BASE_URL,
            model_name=Config.DUAL_LLM_MODEL_NAME,
        )
        logger.info("Dual-LLM mode enabled (Mode B)")

    # Initialize consequence engine
    rules_path = config.get("rules_path", Config.GEO_RULES_PATH) or None
    consequence_engine = ConsequenceEngine(rules_path=rules_path)

    # Initialize geopolitical engine
    engine = GeopoliticalEngine(
        llm_client=llm_client,
        consequence_engine=consequence_engine,
        dual_llm_client=dual_llm_client,
        use_dual_llm=use_dual_llm,
        actor_profiles=profiles,
    )

    # Set up action logging callback
    def on_action_resolved(event, resolution):
        action_log = {
            "round": event.round_num,
            "timestamp": event.timestamp,
            "actor": event.actor_name,
            "action_type": event.action_type.value,
            "action_domain": event.action_domain.value,
            "target": event.target_actor_name,
            "reasoning": event.reasoning,
            "consequence": event.consequence_summary,
            "escalation_delta": event.escalation_delta,
        }
        write_action_log(sim_dir, action_log)

    def on_round_complete(ws):
        # Write world state snapshot
        snapshot = ws.snapshot()
        snapshot_path = os.path.join(sim_dir, "world_state_latest.json")
        with open(snapshot_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        # Write round marker to action log
        write_action_log(sim_dir, {
            "type": "round_complete",
            "round": ws.round_num,
            "escalation_level": ws.escalation_level,
            "phase": ws.phase,
            "oil_price": ws.oil_price,
            "timestamp": ws.simulated_time,
        })

        logger.info(f"Round {ws.round_num} complete. "
                     f"Escalation: {ws.escalation_level}/10, Phase: {ws.phase}, "
                     f"Oil: ${ws.oil_price:.1f}")

    engine.on_action_resolved = on_action_resolved
    engine.on_round_complete = on_round_complete

    # Determine start time
    start_time = config.get("start_time", "2026-03-23T00:00:00Z")

    # Write simulation start marker
    write_action_log(sim_dir, {
        "type": "simulation_start",
        "timestamp": datetime.now().isoformat(),
        "actors": len(profiles),
        "max_rounds": max_rounds,
        "start_time": start_time,
        "escalation_level": world_state.escalation_level,
    })

    logger.info(f"Starting simulation: {max_rounds} rounds, {len(profiles)} actors")

    # Run simulation
    try:
        final_state = engine.run_simulation(
            world_state=world_state,
            max_rounds=max_rounds,
            time_step_hours=hours_per_round,
            start_time=start_time,
        )

        # Write final state
        final_snapshot = final_state.snapshot()
        final_path = os.path.join(sim_dir, "world_state_final.json")
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(final_snapshot, f, ensure_ascii=False, indent=2)

        # Write simulation end marker
        write_action_log(sim_dir, {
            "type": "simulation_end",
            "timestamp": datetime.now().isoformat(),
            "final_round": final_state.round_num,
            "final_escalation": final_state.escalation_level,
            "final_phase": final_state.phase,
            "total_events": len(final_state.events),
        })

        # Save round summaries
        summaries_path = os.path.join(sim_dir, "round_summaries.json")
        with open(summaries_path, 'w', encoding='utf-8') as f:
            json.dump(final_state.round_summaries, f, ensure_ascii=False, indent=2)

        logger.info(f"Simulation complete. Final escalation: {final_state.escalation_level}/10, "
                     f"Phase: {final_state.phase}, Events: {len(final_state.events)}")

    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
        write_action_log(sim_dir, {
            "type": "simulation_interrupted",
            "timestamp": datetime.now().isoformat(),
            "round": world_state.round_num,
        })
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        write_action_log(sim_dir, {
            "type": "simulation_error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
