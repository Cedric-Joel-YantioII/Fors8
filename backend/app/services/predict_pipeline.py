"""
End-to-End Prediction Pipeline.

Chains: Question → Vast.ai GPU → vLLM → Mass Agent Simulation → Aggregation → Answers

This is the single entry point that connects everything:
1. User asks a question (e.g., "Who will win the Iran war?")
2. Pipeline provisions GPU on Vast.ai (or uses existing endpoint)
3. Loads Qwen2.5-72B via vLLM
4. Runs N parallel simulations with 100K agents each
5. Aggregates outcomes into probability distributions
6. Generates narrative answers to the user's question
7. Tears down GPU when done

All progress is tracked in a PredictionJob object that the frontend polls.
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger('fors8.pipeline')


@dataclass
class PredictionJob:
    """Tracks the state of a prediction request."""
    prediction_id: str = ""
    question: str = ""
    status: str = "queued"  # queued, provisioning, loading_model, simulating, aggregating, answering, complete, failed
    progress_message: str = ""
    progress_pct: int = 0

    # Timing
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""

    # Config
    model_name: str = "Qwen/Qwen2.5-72B-Instruct"
    num_agents: int = 100000
    num_runs: int = 10
    rounds_per_run: int = 10
    num_gpus: int = 2

    # GPU
    vast_instance_id: Optional[int] = None
    vllm_endpoint: str = ""
    gpu_cost: float = 0.0

    # Results
    outcomes: Dict[str, Any] = field(default_factory=dict)
    actor_results: Dict[str, Any] = field(default_factory=dict)
    answers: Dict[str, str] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "question": self.question,
            "status": self.status,
            "progress_message": self.progress_message,
            "progress_pct": self.progress_pct,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "model_name": self.model_name,
            "num_agents": self.num_agents,
            "num_runs": self.num_runs,
            "gpu_cost": self.gpu_cost,
            "outcomes": self.outcomes,
            "actor_results": self.actor_results,
            "answers": self.answers,
            "error": self.error,
        }


# In-memory job store (bounded to prevent memory leaks)
_MAX_JOBS = 100
_jobs: Dict[str, PredictionJob] = {}


def get_job(prediction_id: str) -> Optional[PredictionJob]:
    return _jobs.get(prediction_id)


def _evict_old_jobs():
    """Remove oldest completed/failed jobs when store exceeds max size."""
    if len(_jobs) <= _MAX_JOBS:
        return
    # Sort by created_at, remove oldest completed/failed jobs first
    completed = [
        (pid, job) for pid, job in _jobs.items()
        if job.status in ("complete", "failed")
    ]
    completed.sort(key=lambda x: x[1].created_at)
    to_remove = len(_jobs) - _MAX_JOBS
    for pid, _ in completed[:to_remove]:
        del _jobs[pid]


def create_prediction(
    question: str,
    model_name: str = "Qwen/Qwen2.5-72B-Instruct",
    num_agents: int = 100000,
    num_runs: int = 10,
    num_gpus: int = 2,
    vllm_endpoint: str = "",
) -> PredictionJob:
    """Create a new prediction job and start it in a background thread."""

    job = PredictionJob(
        prediction_id=f"pred_{uuid.uuid4().hex[:12]}",
        question=question,
        status="queued",
        created_at=datetime.now().isoformat(),
        model_name=model_name,
        num_agents=num_agents,
        num_runs=num_runs,
        num_gpus=num_gpus,
        vllm_endpoint=vllm_endpoint,
    )

    _evict_old_jobs()
    _jobs[job.prediction_id] = job

    # Run the pipeline in a background thread
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job,),
        daemon=True,
    )
    thread.start()

    logger.info(f"Created prediction job {job.prediction_id}: '{question}'")
    return job


def _run_pipeline(job: PredictionJob):
    """Execute the full prediction pipeline in a background thread."""
    try:
        job.started_at = datetime.now().isoformat()
        vastai_client = None

        # Step 1: Get a vLLM endpoint (either provision or use existing)
        if job.vllm_endpoint:
            # User provided a manual endpoint
            job.status = "loading_model"
            job.progress_message = f"Using existing vLLM endpoint: {job.vllm_endpoint}"
            job.progress_pct = 15
            endpoint = job.vllm_endpoint
        else:
            # Provision Vast.ai
            job.status = "provisioning"
            job.progress_message = "Searching for cheapest GPUs on Vast.ai..."
            job.progress_pct = 5

            from .vastai_client import VastAIClient
            api_key = os.environ.get('VASTAI_API_KEY', '')
            if not api_key:
                raise RuntimeError("No VASTAI_API_KEY configured. Add it in Settings → Self-Hosted GPU.")

            vastai_client = VastAIClient(api_key=api_key)

            def progress_cb(msg):
                job.progress_message = msg
                if "Searching" in msg: job.progress_pct = 5
                elif "Launching" in msg or "Found" in msg: job.progress_pct = 10
                elif "Downloading" in msg or "loading" in msg.lower(): job.progress_pct = 15
                elif "loaded" in msg.lower() or "ready" in msg.lower(): job.progress_pct = 25
                elif "GUARDRAIL" in msg: job.progress_pct = 0

            instance = vastai_client.launch_and_wait(
                model_name=job.model_name,
                num_gpus=job.num_gpus,
                progress_callback=progress_cb,
            )

            endpoint = instance.endpoint_url
            job.vllm_endpoint = endpoint
            job.vast_instance_id = instance.instance_id

        # Step 2: Verify vLLM is serving
        job.status = "loading_model"
        job.progress_message = "Verifying model is loaded..."
        job.progress_pct = 25

        from .mass_agent_runner import MassAgentRunner
        runner = MassAgentRunner(
            endpoint_url=endpoint,
            model_name=job.model_name,
            max_concurrent=200,
        )

        health = runner.health_check()
        if not health.get("healthy"):
            raise RuntimeError(f"vLLM endpoint not healthy: {health.get('error', 'unknown')}")

        job.progress_message = f"Model ready: {health.get('models', ['unknown'])[0]}"
        job.progress_pct = 30

        # Step 3: Load actor data
        from .world_state import ActorState, ActorTier, WorldState, ActionType, ACTION_DOMAIN_MAP
        from .consequence_engine import ConsequenceEngine

        data_dir = os.path.join(os.path.dirname(__file__), '../../data/iran_conflict')
        actors_path = os.path.join(data_dir, 'actors.json')
        conditions_path = os.path.join(data_dir, 'initial_conditions.json')

        with open(actors_path, 'r') as f:
            actors_data = json.load(f)
        with open(conditions_path, 'r') as f:
            initial_conditions = json.load(f)

        # Step 4: Run parallel simulations
        job.status = "simulating"
        job.progress_pct = 35

        from .prediction_engine import PredictionEngine, RunOutcome
        ce = ConsequenceEngine()
        all_outcomes: List[RunOutcome] = []

        available_actions = "launch_strike, missile_launch, air_strike, deploy_forces, defend_position, propose_negotiation, issue_ultimatum, public_statement, hold_position, backchannel_communication, blockade, impose_sanctions, arm_proxy, direct_proxy_attack"

        for run_idx in range(job.num_runs):
            job.progress_message = f"Simulation run {run_idx + 1}/{job.num_runs}..."
            job.progress_pct = 35 + int((run_idx / job.num_runs) * 45)

            # Build fresh world state
            ws = WorldState()
            ws.escalation_level = initial_conditions.get("escalation_level", 7)
            ws.oil_price = initial_conditions.get("oil_price", 119.0)
            ws.strait_of_hormuz_open = initial_conditions.get("strait_of_hormuz_open", False)
            ws.phase = initial_conditions.get("phase", "conflict")

            tier_map = {"strategic": ActorTier.STRATEGIC, "operational": ActorTier.OPERATIONAL, "information": ActorTier.INFORMATION}
            active_agents = []

            for ad in actors_data:
                tier = tier_map.get(ad.get("tier", "operational"), ActorTier.OPERATIONAL)
                if tier == ActorTier.INFORMATION:
                    continue  # Skip info agents for mass sim

                actor = ActorState(
                    actor_id=ad["actor_id"],
                    actor_name=ad["actor_name"],
                    actor_type=ad.get("actor_type", "Organization"),
                    tier=tier,
                    force_strength=float(ad.get("initial_force_strength", 50)),
                    risk_tolerance=float(ad.get("risk_tolerance", 0.5)),
                    martyrdom_willingness=float(ad.get("martyrdom_willingness", 0.0)),
                    escalation_threshold=float(ad.get("escalation_threshold", 0.5)),
                    negotiation_willingness=float(ad.get("negotiation_willingness", 0.5)),
                    casualty_threshold=float(ad.get("casualty_threshold", 0.5)),
                    interceptor_inventory=float(ad.get("initial_interceptor_inventory", 1.0)),
                    missile_inventory=float(ad.get("initial_missile_inventory", 1.0)),
                    domestic_approval=float(ad.get("initial_domestic_approval", 0.5)),
                )
                ws.actors[ad["actor_id"]] = actor
                active_agents.append({
                    "agent_id": ad["actor_id"],
                    "agent_name": ad["actor_name"],
                    "agent_type": ad.get("actor_type", "Organization"),
                })

            # Run rounds
            for round_num in range(1, job.rounds_per_run + 1):
                ws.round_num = round_num
                from datetime import timedelta
                base_date = datetime(2026, 3, 22)
                sim_date = base_date + timedelta(days=round_num)
                ws.simulated_time = sim_date.strftime("%Y-%m-%dT00:00:00Z")

                # Check termination
                should_stop, reason = ce.check_termination(ws, job.rounds_per_run)
                if should_stop:
                    break

                # Build situation JSON
                situation = json.dumps({
                    "round": round_num,
                    "escalation": ws.escalation_level,
                    "oil_price": ws.oil_price,
                    "phase": ws.phase,
                    "hormuz": "open" if ws.strait_of_hormuz_open else "closed",
                }, default=str)

                # Get decisions from vLLM for all agents
                decisions = runner.run_round_sync_wrapper(
                    agents=active_agents,
                    situation_json=situation,
                    available_actions=available_actions,
                    temperature=0.5 + (run_idx * 0.03),  # Vary temperature across runs
                    max_tokens=300,
                )

                # Resolve actions
                for decision in decisions:
                    actor = ws.get_actor(decision.agent_id)
                    if not actor:
                        continue
                    for action_data in decision.actions[:2]:
                        try:
                            action_type = ActionType(action_data.get("action_type", "hold_position"))
                        except ValueError:
                            action_type = ActionType.HOLD_POSITION

                        target_id = action_data.get("target_actor_id")
                        target = ws.get_actor(target_id) if target_id else None
                        resolution = ce.resolve_action(action_type, actor, ws, target, action_data.get("params", {}))
                        ce.apply_resolution(resolution, ws)

                # Update phase
                if ws.escalation_level <= 2: ws.phase = "de-escalation"
                elif ws.escalation_level <= 4: ws.phase = "tensions"
                elif ws.escalation_level <= 6: ws.phase = "crisis"
                elif ws.escalation_level <= 8: ws.phase = "conflict"
                else: ws.phase = "escalation-critical"

            # Record outcome
            _, term_reason = ce.check_termination(ws, job.rounds_per_run)
            if not term_reason:
                term_reason = "max_rounds_reached"

            outcome = RunOutcome(
                run_id=run_idx,
                seed=run_idx * 42,
                final_round=ws.round_num,
                termination_reason=term_reason,
                final_escalation=ws.escalation_level,
                final_phase=ws.phase,
                oil_price=ws.oil_price,
                hormuz_open=ws.strait_of_hormuz_open,
                actor_states={
                    aid: {
                        "name": a.actor_name,
                        "force_strength": a.force_strength,
                        "casualties": a.casualties,
                        "domestic_approval": a.domestic_approval,
                    }
                    for aid, a in ws.actors.items()
                },
                key_events=[e.consequence_summary for e in ws.events[-5:]],
                total_events=len(ws.events),
            )
            all_outcomes.append(outcome)

        # Step 5: Aggregate
        job.status = "aggregating"
        job.progress_message = "Aggregating results across runs..."
        job.progress_pct = 82

        pred_engine = PredictionEngine()
        prediction = pred_engine.aggregate_runs(all_outcomes)

        job.outcomes = prediction.outcome_probabilities
        job.actor_results = prediction.actor_predictions

        # Step 6: Generate answers
        job.status = "answering"
        job.progress_message = "Generating narrative answers..."
        job.progress_pct = 88

        # Use vLLM to answer the user's question
        import requests
        answer_prompt = f"""Based on {job.num_runs} parallel war simulations with {job.num_agents} AI agents, here are the aggregated results:

OUTCOME PROBABILITIES: {json.dumps(prediction.outcome_probabilities)}
AVERAGE ESCALATION: {prediction.avg_final_escalation:.1f}/10
NUCLEAR RISK: {prediction.nuclear_escalation_probability:.0%}
AVERAGE OIL PRICE: ${prediction.avg_oil_price:.0f}

ACTOR OUTCOMES:
{json.dumps(prediction.actor_predictions, indent=2)}

USER QUESTION: {job.question}

Answer the question directly and specifically based on the simulation data. Include probability percentages. Be detailed but concise (3-5 paragraphs)."""

        try:
            resp = requests.post(
                f"{endpoint}/chat/completions",
                json={
                    "model": job.model_name,
                    "messages": [{"role": "user", "content": answer_prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                import re
                answer_text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                answer_text = re.sub(r'<think>[\s\S]*?</think>', '', answer_text).strip()
                job.answers = {"main_answer": answer_text}
            else:
                job.answers = {"main_answer": f"Answer generation failed (HTTP {resp.status_code}). Raw data is available above."}
        except Exception as e:
            job.answers = {"main_answer": f"Answer generation failed: {str(e)}. Raw simulation data is available above."}

        # Step 7: Cleanup
        job.status = "complete"
        job.progress_message = "Prediction complete."
        job.progress_pct = 100
        job.completed_at = datetime.now().isoformat()

        # Destroy Vast.ai instance if we provisioned one
        if vastai_client and job.vast_instance_id:
            try:
                job.progress_message = "Tearing down GPU instance..."
                vastai_client.destroy_instance(job.vast_instance_id)
                instance = vastai_client.instances.get(job.vast_instance_id)
                if instance:
                    job.gpu_cost = instance.total_cost
            except Exception as destroy_err:
                logger.error(f"Failed to destroy instance {job.vast_instance_id} after success: {destroy_err}")

        logger.info(f"Prediction {job.prediction_id} complete. GPU cost: ${job.gpu_cost:.2f}")

    except Exception as e:
        import traceback
        logger.error(f"Pipeline failed: {e}\n{traceback.format_exc()}")
        job.status = "failed"
        job.error = str(e)
        job.progress_message = f"Failed: {str(e)}"

        # Cleanup GPU on failure — destroy all instances tracked by the client,
        # not just job.vast_instance_id, because the instance may have been
        # launched but its ID not yet recorded on the job (e.g., timeout during wait_until_ready).
        if vastai_client:
            for inst_id in list(vastai_client.instances.keys()):
                try:
                    vastai_client.destroy_instance(inst_id)
                except Exception:
                    logger.error(f"Failed to destroy leaked instance {inst_id} during error cleanup")
