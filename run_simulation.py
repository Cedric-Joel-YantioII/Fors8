#!/usr/bin/env python3
"""
Quick simulation runner — connects to Vast.ai Ollama endpoint and runs a prediction.
Usage: python3 run_simulation.py [endpoint_url]
"""

import sys
import os
import json
import time
import requests

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Load env
from dotenv import load_dotenv
load_dotenv()


def wait_for_model(endpoint, model="qwen2.5:14b", timeout=600):
    """Wait for Ollama to be ready and model to be pulled."""
    print(f"Waiting for Ollama at {endpoint}...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            r = requests.get(f"{endpoint}/api/tags", timeout=5)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                if any(model in m for m in models):
                    print(f"Model ready: {models}")
                    return True
                else:
                    print(f"  Ollama up, models: {models}. Pulling {model}...")
                    # Trigger pull if not started
                    requests.post(f"{endpoint}/api/pull", json={"name": model}, timeout=5)
        except Exception as e:
            pass
        time.sleep(10)

    return False


def run_simulation(endpoint, question="What is the most likely outcome of the Iran-US conflict in the next 30 days?"):
    """Run a simplified simulation directly."""
    print(f"\n{'='*60}")
    print(f"QUESTION: {question}")
    print(f"ENDPOINT: {endpoint}")
    print(f"{'='*60}\n")

    # Step 1: Generate personas from data
    print("[1/5] Generating agent personas from data...")
    from app.services.graph_persona_generator import generate_personas_from_graph

    # Load actor data
    data_dir = os.path.join(os.path.dirname(__file__), "backend/data/iran_conflict")
    with open(os.path.join(data_dir, "actors.json")) as f:
        actors_data = json.load(f)
    with open(os.path.join(data_dir, "initial_conditions.json")) as f:
        initial_conditions = json.load(f)

    # Load strategic infrastructure
    infra_path = os.path.join(data_dir, "strategic_infrastructure.json")
    if os.path.exists(infra_path):
        with open(infra_path) as f:
            initial_conditions["strategic_infrastructure"] = json.load(f)

    personas = generate_personas_from_graph(
        graph_id="",
        question=question,
        actors_data=actors_data,
        initial_conditions=initial_conditions,
        target_count=200,  # Small for quick test
        endpoint=endpoint,
        model_name="qwen2.5:14b",
    )
    print(f"  Generated {len(personas)} personas")

    # Show trait distribution
    hawks = [p.hawkishness for p in personas]
    print(f"  Hawkishness: mean={sum(hawks)/len(hawks):.2f}, min={min(hawks):.2f}, max={max(hawks):.2f}")

    # Step 2: Run social simulation (3 rounds)
    print("\n[2/5] Running social simulation...")
    from app.services.social_simulation import SocialSimulation

    social_sim = SocialSimulation(
        population=personas,
        situation_data={
            "escalation": initial_conditions.get("escalation_level", 8),
            "oil_price": initial_conditions.get("oil_price", 119),
            "phase": initial_conditions.get("phase", "conflict"),
        },
    )

    social_results = []
    for round_num in range(1, 4):
        result = social_sim.run_social_round(
            round_num=round_num,
            situation_update={
                "escalation": initial_conditions.get("escalation_level", 8),
                "oil_price": initial_conditions.get("oil_price", 119),
                "phase": initial_conditions.get("phase", "conflict"),
            },
            sample_size=min(100, len(personas)),
        )
        social_results.append(result)
        print(f"  Round {round_num}: posts={result['total_posts']}, "
              f"esc_pressure={result['escalation_pressure']:.2f}, "
              f"deesc_pressure={result['deescalation_pressure']:.2f}")

    # Step 3: Run a quick agent decision round via Ollama
    print("\n[3/5] Running agent decisions via Ollama...")
    from app.services.mass_agent_runner import MassAgentRunner

    runner = MassAgentRunner(
        endpoint_url=endpoint,
        model_name="qwen2.5:14b",
        max_concurrent=5,
        timeout_per_request=60,
    )

    # Health check
    health = runner.health_check()
    print(f"  Health: {health}")

    # Pick 5 diverse agents for a test round
    test_agents = []
    seen_roles = set()
    for p in personas:
        if p.role not in seen_roles and len(test_agents) < 5:
            seen_roles.add(p.role)
            test_agents.append({
                "agent_id": p.agent_id,
                "agent_name": p.agent_name,
                "agent_type": "actor",
                "persona": p.to_dict(),
            })

    situation = json.dumps({
        "round": 1,
        "escalation": initial_conditions.get("escalation_level", 8),
        "oil_price": initial_conditions.get("oil_price", 119),
        "phase": "conflict",
        "actors": {a["agent_id"]: {"name": a["agent_name"]} for a in test_agents},
        "social_sentiment": {
            "escalation_pressure": social_results[-1]["escalation_pressure"],
            "deescalation_pressure": social_results[-1]["deescalation_pressure"],
        },
    })

    actions = "launch_strike, missile_launch, air_strike, deploy_forces, defend_position, propose_negotiation, issue_ultimatum, public_statement, hold_position, backchannel_communication, blockade, impose_sanctions"

    decisions = runner.run_round_sync_wrapper(
        agents=test_agents,
        situation_json=situation,
        available_actions=actions,
        temperature=0.7,
        max_tokens=300,
    )

    print(f"\n  Agent decisions ({len(decisions)}):")
    for d in decisions:
        if d.success and d.actions:
            action = d.actions[0]
            print(f"    {d.agent_id}: {action.get('action_type', '?')} → {action.get('target_actor_id', 'none')}")
            if action.get("reasoning"):
                print(f"      Reasoning: {action['reasoning'][:100]}")
            if action.get("data_references"):
                print(f"      Data refs: {action['data_references']}")
        else:
            print(f"    {d.agent_id}: FAILED — {d.error[:80] if d.error else 'no response'}")

    # Step 4: Generate answer via Ollama
    print("\n[4/5] Generating prediction answer...")
    answer_prompt = f"""You are a geopolitical analyst. Based on the following simulation data, answer the question.

SIMULATION DATA:
- {len(personas)} diverse agents simulated across {len(set(p.country for p in personas))} countries
- Social simulation: escalation pressure={social_results[-1]['escalation_pressure']:.2f}, de-escalation={social_results[-1]['deescalation_pressure']:.2f}
- Agent decisions: {json.dumps([{"agent": d.agent_id, "action": d.actions[0].get("action_type") if d.actions else "none"} for d in decisions if d.success])}
- Current conditions: escalation={initial_conditions.get('escalation_level')}/10, oil=${initial_conditions.get('oil_price')}, phase={initial_conditions.get('phase')}
- Country sentiments: {json.dumps(social_results[-1].get('country_sentiments', {}))}

QUESTION: {question}

Provide a concise assessment (3-4 paragraphs) citing specific data points from above."""

    try:
        resp = requests.post(f"{endpoint}/api/chat", json={
            "model": "qwen2.5:14b",
            "messages": [{"role": "user", "content": answer_prompt}],
            "stream": False,
        }, timeout=120)

        if resp.status_code == 200:
            answer = resp.json().get("message", {}).get("content", "")
            print(f"\n{'='*60}")
            print("PREDICTION:")
            print(f"{'='*60}")
            print(answer[:2000])
        else:
            print(f"  Answer generation failed: {resp.status_code}")
    except Exception as e:
        print(f"  Answer generation error: {e}")

    # Step 5: Validate grounding
    print(f"\n[5/5] Validating data grounding...")
    try:
        from app.services.prediction_validator import validate_grounding
        report = validate_grounding(answer, initial_conditions, {})
        print(f"  Grounding score: {report.grounding_score:.0%}")
        print(f"  Grounded claims: {report.grounded_claims}/{report.total_claims}")
        if report.suspicious_claims:
            print(f"  Suspicious (possible training data): {len(report.suspicious_claims)}")
    except Exception as e:
        print(f"  Validation error: {e}")

    print(f"\n{'='*60}")
    print("SIMULATION COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    endpoint = sys.argv[1] if len(sys.argv) > 1 else None

    if not endpoint:
        # Try to read from saved file
        try:
            endpoint = open("/tmp/vast_endpoint.txt").read().strip()
        except:
            print("No endpoint provided. Usage: python3 run_simulation.py http://IP:PORT")
            print("Waiting for Vast.ai instance...")
            exit(1)

    # Wait for model
    if not wait_for_model(endpoint):
        print("Model not ready after timeout. Check Vast.ai dashboard.")
        exit(1)

    run_simulation(endpoint)
