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
from datetime import datetime, timedelta

from .database import get_db

logger = logging.getLogger('fors8.pipeline')


@dataclass
class PredictionJob:
    """Tracks the state of a prediction request."""
    prediction_id: str = ""
    question: str = ""
    status: str = "queued"  # queued, provisioning, loading_model, scraping_data, building_graph, extracting_actors, simulating, aggregating, answering, complete, failed
    progress_message: str = ""
    progress_pct: int = 0

    # Timing
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""

    # Config
    model_name: str = "Qwen/Qwen2.5-72B-Instruct"
    num_agents: int = 3000
    num_runs: int = 30
    rounds_per_run: int = 30
    num_gpus: int = 2

    # GPU
    vast_instance_id: Optional[int] = None
    vllm_endpoint: str = ""
    gpu_cost: float = 0.0

    # Seed documents (uploaded files carried into the pipeline)
    seed_documents: List[Dict[str, str]] = field(default_factory=list)

    # Results
    outcomes: Dict[str, Any] = field(default_factory=dict)
    actor_results: Dict[str, Any] = field(default_factory=dict)
    answers: Dict[str, str] = field(default_factory=dict)
    graph_id: str = ""
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
            "graph_id": self.graph_id,
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
    conversation_context: Optional[str] = None,
    previous_outcomes: Optional[Dict] = None,
    seed_documents: Optional[List[Dict[str, str]]] = None,
) -> PredictionJob:
    """Create a new prediction job and start it in a background thread.

    Args:
        conversation_context: Text of previous Q&A in this conversation, used
            to give agents awareness of prior analysis across follow-up runs.
        previous_outcomes: Outcomes dict from the last prediction run, so the
            new run can build on earlier results.
        seed_documents: List of uploaded file dicts with keys 'name' and 'content',
            carried into the pipeline for graph ingestion alongside scraped data.
    """

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
        seed_documents=seed_documents or [],
    )

    _evict_old_jobs()
    _jobs[job.prediction_id] = job

    # Persist the initial prediction to PostgreSQL
    try:
        get_db().save_prediction(job.to_dict())
    except Exception:
        logger.debug("Initial prediction DB save skipped (DB may be unavailable)")

    # Run the pipeline in a background thread
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job, conversation_context, previous_outcomes),
        daemon=True,
    )
    thread.start()

    logger.info(f"Created prediction job {job.prediction_id}: '{question}'")
    return job


def _persist_job(job: PredictionJob):
    """Best-effort save of current job state to PostgreSQL."""
    try:
        get_db().save_prediction(job.to_dict())
    except Exception:
        logger.debug("DB persist skipped for %s", job.prediction_id)


# ---------------------------------------------------------------------------
# Dynamic actor extraction from knowledge graph
# ---------------------------------------------------------------------------

# Geopolitical entity types we care about for simulation actors
_GEOPOLITICAL_ENTITY_TYPES = {
    "NationState", "Nation_State",
    "ProxyGroup", "Proxy_Group",
    "MilitaryForce", "Military_Force",
    "EconomicEntity", "Economic_Entity",
    "InternationalOrg", "International_Org",
    "PoliticalLeader", "Political_Leader",
    "MilitaryCommander", "Military_Commander",
    "MediaOutlet", "Media_Outlet",
    "InformationActor",
}


def _extract_actors_from_graph(job: PredictionJob, graph_id: str) -> tuple:
    """Extract actors and initial conditions from a knowledge graph.

    Returns: (actors_data: List[dict], initial_conditions: dict) or (None, None) on failure.
    """
    try:
        job.progress_message = "Extracting actors from knowledge graph..."
        job.progress_pct = 40

        from .zep_entity_reader import ZepEntityReader
        from .geopolitical_profile_generator import GeopoliticalProfileGenerator

        # Extract entities -- filter to geopolitical types only
        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(
            graph_id,
            defined_entity_types=list(_GEOPOLITICAL_ENTITY_TYPES),
            enrich_with_edges=True,
        )

        if not filtered.entities:
            logger.warning("No geopolitical entities found in graph -- falling back to static data")
            return None, None

        logger.info(
            "Found %d geopolitical entities of types: %s",
            filtered.filtered_count,
            filtered.entity_types,
        )

        # Generate profiles via LLM
        job.progress_message = f"Generating profiles for {filtered.filtered_count} actors..."
        job.progress_pct = 42

        profiler = GeopoliticalProfileGenerator(graph_id=graph_id)
        profiles = profiler.generate_profiles(
            entities=filtered.entities,
            simulation_requirement=job.question,
        )

        if not profiles:
            logger.warning("Profile generation returned no profiles")
            return None, None

        # Convert to actors.json-compatible dicts
        actors_data = [p.to_dict() for p in profiles]

        # Auto-generate initial conditions from graph context
        initial_conditions = _generate_initial_conditions_from_graph(
            graph_id, profiles, job.question,
        )

        logger.info("Generated %d actor profiles from knowledge graph", len(actors_data))
        return actors_data, initial_conditions

    except Exception as e:
        logger.warning("Actor extraction from graph failed: %s", e)
        return None, None


_INITIAL_CONDITIONS_PROMPT = """You are a geopolitical analyst. Based on the knowledge graph context below, generate initial conditions for a conflict simulation.

## Actor profiles extracted from the graph
{actor_summaries}

## Simulation question
{question}

## Output format (valid JSON only)
Generate a JSON object with these fields. Use real-world data where available; estimate conservatively where not.

```json
{{
    "scenario_name": "Brief scenario description",
    "war_start_date": "YYYY-MM-DD or null if no active conflict",
    "days_of_war": 0,
    "phase": "one of: peace, tensions, crisis, conflict, escalation-critical",
    "escalation_level": 0-10,
    "oil_price": current Brent crude estimate,
    "global_risk_index": 0.0-1.0,
    "strait_of_hormuz_open": true/false,
    "bab_el_mandeb_open": true/false,
    "suez_canal_open": true/false,
    "nuclear_threshold_status": "one of: stable, warning, critical",
    "humanitarian_impact": 0.0-1.0,
    "negotiation_status": "Brief description of negotiation state",
    "active_conflicts": ["list of active conflict zones"],
    "active_negotiations": ["list of active negotiation tracks"],
    "casualty_estimates": {{
        "mapping of actor_key to estimated casualties (integers)"
    }},
    "weapons_dynamics": {{
        "brief description of key weapons systems status"
    }},
    "nuclear_status": {{
        "iran_enrichment_capacity_post_strikes": "description",
        "iran_nuclear_weapon_status": "description"
    }},
    "energy_infrastructure_damage": {{
        "brief description of damage to energy infrastructure"
    }}
}}
```

Be grounded in real-world data. If this is a hypothetical/future scenario, extrapolate from the most recent known state of affairs."""


def _generate_initial_conditions_from_graph(
    graph_id: str,
    profiles: list,
    question: str,
) -> dict:
    """Use the LLM to generate initial_conditions from graph context and actor profiles.

    Returns a dict matching the schema used by the simulation pipeline
    (escalation_level, oil_price, phase, etc.).  Falls back to reasonable
    defaults on any error so the pipeline is never blocked.
    """
    try:
        from openai import OpenAI
        from ..config import Config

        actor_summaries = "\n".join(
            f"- {p.actor_name} ({p.actor_type}, tier={p.tier}): {p.description}"
            for p in profiles
        )

        prompt = _INITIAL_CONDITIONS_PROMPT.format(
            actor_summaries=actor_summaries,
            question=question,
        )

        client = OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL)
        response = client.chat.completions.create(
            model=Config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Generate initial conditions for: {question}"},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        conditions = json.loads(content)

        # Ensure critical keys have sane defaults
        conditions.setdefault("escalation_level", 5)
        conditions.setdefault("oil_price", 85.0)
        conditions.setdefault("phase", "tensions")
        conditions.setdefault("strait_of_hormuz_open", True)
        conditions.setdefault("bab_el_mandeb_open", True)
        conditions.setdefault("suez_canal_open", True)
        conditions.setdefault("global_risk_index", 0.5)
        conditions.setdefault("nuclear_threshold_status", "stable")
        conditions.setdefault("humanitarian_impact", 0.0)
        conditions.setdefault("casualty_estimates", {})
        conditions.setdefault("active_conflicts", [])
        conditions.setdefault("active_negotiations", [])

        logger.info("Generated initial conditions from graph: phase=%s, escalation=%s",
                     conditions.get("phase"), conditions.get("escalation_level"))
        return conditions

    except Exception as e:
        logger.warning("Initial conditions generation failed (%s), using defaults", e)
        return {
            "scenario_name": "Auto-generated scenario",
            "phase": "tensions",
            "escalation_level": 5,
            "oil_price": 85.0,
            "global_risk_index": 0.5,
            "strait_of_hormuz_open": True,
            "bab_el_mandeb_open": True,
            "suez_canal_open": True,
            "nuclear_threshold_status": "stable",
            "humanitarian_impact": 0.0,
            "casualty_estimates": {},
            "active_conflicts": [],
            "active_negotiations": [],
        }


def _save_run_memories(job: PredictionJob, run_idx: int, outcome):
    """Save key insights from a simulation run as agent memories."""
    try:
        db = get_db()
        # Save per-actor memories from this run
        for aid, state in (outcome.actor_states or {}).items():
            insight = (
                f"Run {run_idx + 1}: final_escalation={outcome.final_escalation}, "
                f"phase={outcome.final_phase}, force={state.get('force_strength', '?')}, "
                f"casualties={state.get('casualties', '?')}, "
                f"approval={state.get('domestic_approval', '?')}"
            )
            db.save_memory(
                actor_id=aid,
                content=insight,
                memory_type="run_outcome",
                source_prediction_id=job.prediction_id,
                round_num=outcome.final_round,
            )
        # Save key events as memories under a synthetic "events" actor
        for event_text in (outcome.key_events or []):
            db.save_memory(
                actor_id="__events__",
                content=event_text,
                memory_type="key_event",
                source_prediction_id=job.prediction_id,
                round_num=outcome.final_round,
            )
    except Exception:
        logger.debug("Failed to save run memories for run %d", run_idx)


def _ingest_realtime_data(job: PredictionJob, static_data_dir: Optional[str] = None) -> str:
    """Scrape and ingest real-time OSINT + social media data before simulation.

    Returns combined text for use in ontology generation and graph building.
    All scraping is wrapped in try/except so failures are non-fatal.
    """
    combined_text = job.question + "\n\n"

    # 1. OSINT (GDELT, news, oil prices, YouTube, RSS feeds)
    try:
        from .osint_scrapers import OSINTManager
        job.progress_message = "Scraping latest intelligence data..."
        osint = OSINTManager()
        osint.configure(
            newsapi_key=os.environ.get("NEWSAPI_KEY"),
            youtube_api_key=os.environ.get("YOUTUBE_API_KEY"),
            newsdata_key=os.environ.get("NEWSDATA_KEY"),
            gnews_key=os.environ.get("GNEWS_KEY"),
            acled_email=os.environ.get("ACLED_EMAIL"),
            acled_key=os.environ.get("ACLED_KEY"),
        )
        data = osint.fetch_all(query=job.question)

        for source_name, source_data in data.get("sources", {}).items():
            if not isinstance(source_data, dict):
                continue
            # News/GDELT articles
            for article in source_data.get("articles", [])[:15]:
                title = article.get("title", "")
                content = article.get("content", article.get("description", ""))
                text = f"[{source_name}] {title}: {content}"
                combined_text += text + "\n\n"
            # Oil prices
            if "prices" in source_data:
                combined_text += f"[Oil Prices] {json.dumps(source_data['prices'])}\n\n"
            # YouTube videos
            for video in source_data.get("videos", [])[:10]:
                text = f"[{source_name}] {video.get('title', '')}: {video.get('description', '')}"
                combined_text += text + "\n\n"

        osint_source_count = len(data.get("sources", {}))
        logger.info("OSINT scraping complete: %d sources", osint_source_count)
    except Exception as e:
        logger.warning("OSINT scraping failed: %s", e)

    # 2. Social media (official accounts — heads of state, military spokespersons)
    try:
        from .social_media_scraper import SocialMediaScraper
        job.progress_message = "Checking official statements..."
        scraper = SocialMediaScraper(
            twitter_bearer_token=os.environ.get("TWITTER_BEARER_TOKEN"),
            telegram_api_id=os.environ.get("TELEGRAM_API_ID"),
            telegram_api_hash=os.environ.get("TELEGRAM_API_HASH"),
        )
        scraper.configure_accounts()  # Loads default accounts (POTUS, IDF, Khamenei, etc.)
        results = scraper.scrape_all()  # Returns Dict[actor_id, List[ScrapedPost]]

        post_count = 0
        for actor_id, posts in results.items():
            for post in posts[:20]:
                text = f"[{post.platform} - {post.actor_name}] {post.content}"
                combined_text += text + "\n\n"
                post_count += 1
                if post_count >= 20:
                    break
            if post_count >= 20:
                break

        logger.info("Social media scraping complete: %d posts from %d actors", post_count, len(results))
    except Exception as e:
        logger.warning("Social media scraping failed: %s", e)

    # 3. Static baseline data (only if a scenario-specific data dir was found)
    if static_data_dir and os.path.isdir(static_data_dir):
        try:
            for fname in os.listdir(static_data_dir):
                fpath = os.path.join(static_data_dir, fname)
                if os.path.isfile(fpath) and fname.endswith('.json'):
                    with open(fpath) as f:
                        combined_text += f"\n\n[Baseline Data: {fname}]\n{f.read()}\n"
            logger.info("Loaded baseline data from %s", static_data_dir)
        except Exception as e:
            logger.warning("Failed to load baseline data from %s: %s", static_data_dir, e)

    # 4. Uploaded seed documents (carried on the job from the API endpoint)
    for doc in job.seed_documents:
        doc_name = doc.get("name", "uploaded_file")
        doc_content = doc.get("content", "")
        if doc_content:
            combined_text += f"\n\n[Uploaded: {doc_name}]\n{doc_content}\n"

    return combined_text


def _build_knowledge_graph(job: PredictionJob, realtime_text: str) -> Optional[str]:
    """Build a knowledge graph from scraped OSINT data + seed documents.

    Accepts the combined ``realtime_text`` already produced by
    ``_ingest_realtime_data()`` so we avoid scraping twice.  After the
    graph structure is created via ``GraphBuilderService``, a
    ``DataIngestor`` sends individual records into the *same* graph with
    proper credibility tags, making them available for entity extraction.

    Returns a Zep graph_id on success, or None if any step fails.  This is
    Step 2.5 of the pipeline -- runs between GPU provisioning and the
    simulation step.  It is intentionally non-blocking: if graph building
    fails for any reason, the pipeline falls back to static actors.json.
    """
    try:
        job.status = "building_graph"
        job.progress_message = "Analyzing question and building knowledge graph..."
        job.progress_pct = 32
        _persist_job(job)

        from .ontology_generator import OntologyGenerator
        from .text_processor import TextProcessor

        # Use the pre-scraped realtime_text (question + OSINT + social media
        # + baseline data) instead of re-scraping.
        seed_text = realtime_text

        # Append uploaded seed documents so they participate in ontology
        # generation and graph building
        for doc in job.seed_documents:
            doc_name = doc.get("name", "uploaded_file")
            doc_content = doc.get("content", "")
            if doc_content:
                seed_text += f"\n\n[Uploaded: {doc_name}]\n{doc_content}"

        # Generate ontology from combined text
        og = OntologyGenerator()
        ontology = og.generate(
            document_texts=[seed_text],
            simulation_requirement=job.question,
        )

        if not ontology or not ontology.get("entity_types"):
            logger.warning("Ontology generation returned empty -- falling back to static data")
            return None

        job.progress_message = "Building knowledge graph in Zep..."
        job.progress_pct = 35
        _persist_job(job)

        # Build graph via Zep
        from .graph_builder import GraphBuilderService
        graph_service = GraphBuilderService()
        graph_id = graph_service.create_graph(name=f"pred_{job.prediction_id}")
        graph_service.set_ontology(graph_id, ontology)

        # Chunk and add the combined text to the graph
        preprocessed = TextProcessor.preprocess_text(seed_text)
        chunks = TextProcessor.split_text(preprocessed, chunk_size=500, overlap=50)
        episode_uuids = graph_service.add_text_batches(graph_id, chunks, batch_size=3)

        # Wait for Zep to process (shorter timeout for prediction flow)
        if episode_uuids:
            graph_service._wait_for_episodes(episode_uuids, timeout=120)

        # --- DataIngestor: send individual records with credibility tags ---
        # The chunks above give Zep the raw text for entity extraction.
        # The DataIngestor sends the *same* data as tagged EpisodeData so that
        # each record carries its source credibility and category metadata
        # inside the graph, enabling downstream trust-weighted reasoning.
        job.progress_message = "Ingesting records with credibility tags..."
        job.progress_pct = 37
        _persist_job(job)

        _ingest_records_into_graph(job, graph_id)

        job.progress_message = "Knowledge graph built successfully"
        job.progress_pct = 38
        _persist_job(job)
        logger.info("Knowledge graph built: graph_id=%s (%d chunks)", graph_id, len(chunks))
        return graph_id

    except Exception as e:
        logger.warning("Knowledge graph building failed (falling back to static): %s", e)
        return None


def _ingest_records_into_graph(job: PredictionJob, graph_id: str):
    """Send individual tagged records into the Zep graph via DataIngestor.

    Called *after* the graph has been created and the ontology set so that
    each record is stored as a credibility-tagged episode inside the same
    graph the GraphBuilder uses for entity extraction.

    Non-fatal: any failure here is logged but does not abort the pipeline.
    """
    try:
        from .data_ingestor import DataIngestor, DataCategory, SourceCredibility
        from ..config import Config

        # Build a DataIngestor targeting the prediction's graph
        zep_client = None
        if Config.ZEP_API_KEY:
            try:
                from zep_cloud.client import Zep
                zep_client = Zep(api_key=Config.ZEP_API_KEY)
            except Exception:
                pass

        ingestor = DataIngestor(zep_client=zep_client, graph_id=graph_id)
        total_ingested = 0

        # 1. Re-ingest OSINT data with proper credibility tags
        #    (the combined text was already chunked above; here we add
        #    tagged records so Zep can weight them by credibility)
        try:
            from .osint_scrapers import OSINTManager
            osint = OSINTManager(data_ingestor=ingestor)
            osint.configure(
                newsapi_key=os.environ.get("NEWSAPI_KEY"),
                youtube_api_key=os.environ.get("YOUTUBE_API_KEY"),
                newsdata_key=os.environ.get("NEWSDATA_KEY"),
                gnews_key=os.environ.get("GNEWS_KEY"),
                acled_email=os.environ.get("ACLED_EMAIL"),
                acled_key=os.environ.get("ACLED_KEY"),
            )
            # fetch_all will call ingestor.ingest_news_article for each
            # article when a data_ingestor is attached to the OSINTManager
            osint.fetch_all(query=job.question)
            total_ingested += len(ingestor.list_sources())
        except Exception as e:
            logger.warning("OSINT re-ingestion into graph failed (non-fatal): %s", e)

        # 2. Ingest social media posts as official statements
        try:
            from .social_media_scraper import SocialMediaScraper
            scraper = SocialMediaScraper(
                twitter_bearer_token=os.environ.get("TWITTER_BEARER_TOKEN"),
                telegram_api_id=os.environ.get("TELEGRAM_API_ID"),
                telegram_api_hash=os.environ.get("TELEGRAM_API_HASH"),
            )
            scraper.configure_accounts()
            results = scraper.scrape_all()

            for actor_id, posts in results.items():
                for post in posts[:20]:
                    ingestor.ingest_official_statement(
                        actor_id=actor_id,
                        actor_name=getattr(post, 'actor_name', actor_id),
                        statement=post.content,
                        platform=getattr(post, 'platform', 'unknown'),
                        timestamp=getattr(post, 'timestamp', datetime.now().isoformat()),
                        url=getattr(post, 'url', None),
                    )
                    total_ingested += 1
        except Exception as e:
            logger.warning("Social media ingestion into graph failed (non-fatal): %s", e)

        # 3. Ingest uploaded seed documents with credibility tags
        for doc in job.seed_documents:
            doc_name = doc.get("name", "uploaded_file")
            doc_content = doc.get("content", "")
            if doc_content:
                ingestor.ingest_document(
                    text=doc_content,
                    source_name=doc_name,
                    category=DataCategory.INTELLIGENCE_REPORT,
                    credibility=SourceCredibility.INSTITUTIONAL,
                )
                total_ingested += 1

        # 4. Ingest static baseline data package (if scenario-specific data exists)
        if hasattr(job, '_static_data_dir') and job._static_data_dir and os.path.isdir(job._static_data_dir):
            result = ingestor.ingest_data_package(job._static_data_dir)
            total_ingested += result.records_ingested

        logger.info(
            "DataIngestor: %d records sent to graph %s with credibility tags",
            total_ingested, graph_id,
        )

    except Exception as e:
        logger.warning("DataIngestor record ingestion failed (non-fatal): %s", e)


def _run_pipeline(job: PredictionJob, conversation_context: Optional[str] = None, previous_outcomes: Optional[Dict] = None):
    """Execute the full prediction pipeline in a background thread.

    Pipeline flow:
        Step 1 – Get inference endpoint (GPU provisioning)
        Step 2 – Verify model health
        Step 3 – Ingest real-time data (OSINT + social media)
        Step 4 – Build knowledge graph
        Step 5 – Extract actors from graph (fallback: static JSON)
        Step 6 – Run parallel simulations
        Step 7 – Aggregate results
        Step 8 – Generate answers
        Step 9 – Cleanup
    """
    try:
        job.started_at = datetime.now().isoformat()
        gpu_lifecycle = None

        # Classify the scenario from the user's question
        from .scenario_classifier import classify_scenario
        scenario_config = classify_scenario(job.question)
        logger.info("Scenario classified: type=%s, %d actions available",
                     scenario_config.scenario_type, len(scenario_config.available_actions))
        # Store on job for use by data ingestion functions
        job._static_data_dir = scenario_config.static_data_dir

        # ==================================================================
        # Step 1: Get an inference endpoint (EXISTING — don't change)
        # Priority: explicit endpoint > GPU lifecycle manager
        if job.vllm_endpoint:
            # User provided a manual endpoint
            job.status = "loading_model"
            job.progress_message = f"Using existing endpoint: {job.vllm_endpoint}"
            job.progress_pct = 15
            endpoint = job.vllm_endpoint
        else:
            # Use the GPU lifecycle manager — it handles provisioning,
            # model pulling, idle timeout, and auto-destroy transparently.
            job.status = "provisioning"
            job.progress_message = "GPU lifecycle: acquiring endpoint..."
            job.progress_pct = 5

            from .gpu_lifecycle import get_gpu_lifecycle
            gpu_lifecycle = get_gpu_lifecycle()

            def progress_cb(msg):
                job.progress_message = msg
                if "Searching" in msg: job.progress_pct = 5
                elif "Launching" in msg or "Found" in msg: job.progress_pct = 10
                elif "Pulling" in msg or "pulling" in msg.lower(): job.progress_pct = 15
                elif "ready" in msg.lower() or "Verifying" in msg: job.progress_pct = 25
                elif "Still" in msg: job.progress_pct = 18

            endpoint = gpu_lifecycle.get_endpoint(
                model=job.model_name,
                progress_callback=progress_cb,
            )
            job.vllm_endpoint = endpoint
            gpu_lifecycle.mark_prediction_start()

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
        _persist_job(job)

        # ==================================================================
        # Step 3 (NEW): Ingest real-time data (OSINT + social media)
        # Progress: 30% → 32%
        # ==================================================================
        combined_text = None
        try:
            job.status = "scraping_data"
            job.progress_message = "Ingesting real-time OSINT data..."
            job.progress_pct = 30
            _persist_job(job)

            combined_text = _ingest_realtime_data(job, static_data_dir=scenario_config.static_data_dir)

            job.progress_message = "Real-time data ingestion complete."
            job.progress_pct = 32
            _persist_job(job)
            logger.info("Real-time data ingestion complete: %d chars", len(combined_text or ""))
        except Exception as e:
            logger.warning("Real-time data ingestion failed, falling back to question text: %s", e)
            combined_text = None
            job.progress_message = "OSINT scraping failed, using question text only."
            job.progress_pct = 32
            _persist_job(job)

        # If scraping failed or returned empty, fall back to just the question text
        if not combined_text:
            combined_text = job.question

        # ==================================================================
        # Step 4 (NEW): Build knowledge graph from ingested data
        # Progress: 32% → 38%
        # ==================================================================
        graph_id = None
        try:
            job.status = "building_graph"
            job.progress_message = "Building knowledge graph from real-time data..."
            job.progress_pct = 33
            _persist_job(job)

            graph_id = _build_knowledge_graph(job, combined_text)

            if graph_id:
                job.graph_id = graph_id
                job.progress_message = f"Knowledge graph built: {graph_id}"
                logger.info("Using knowledge graph %s for prediction %s", graph_id, job.prediction_id)
            else:
                job.progress_message = "Knowledge graph build returned None, using static actors."
                logger.info("No knowledge graph — using static actors.json for prediction %s", job.prediction_id)
            job.progress_pct = 38
            _persist_job(job)
        except Exception as e:
            logger.warning("Knowledge graph build failed, using static actors: %s", e)
            graph_id = None
            job.progress_message = "Graph build failed, falling back to static actors."
            job.progress_pct = 38
            _persist_job(job)

        # ==================================================================
        # Step 5 (NEW): Extract actors & initial conditions from graph
        # Progress: 38% → 45%
        # ==================================================================
        actors_data = None
        initial_conditions = None
        try:
            if graph_id:
                job.status = "extracting_actors"
                job.progress_message = "Extracting actors and conditions from knowledge graph..."
                job.progress_pct = 39
                _persist_job(job)

                extracted = _extract_actors_from_graph(job, graph_id)
                if extracted and extracted[0] and extracted[1]:
                    actors_data, initial_conditions = extracted
                    job.progress_message = f"Extracted {len(actors_data)} actors from graph."
                else:
                    actors_data = None
                    initial_conditions = None
                    job.progress_message = "Actor extraction returned None, using static actors."
                job.progress_pct = 45
                _persist_job(job)
        except Exception as e:
            logger.warning("Actor extraction from graph failed, using static actors: %s", e)
            actors_data = None
            initial_conditions = None
            job.progress_message = "Actor extraction failed, falling back to static actors."
            job.progress_pct = 45
            _persist_job(job)

        # Fallback: load static actor data if dynamic extraction didn't work
        if not actors_data or not initial_conditions:
            loaded_static = False
            # Try scenario-specific static data first
            if scenario_config and scenario_config.static_data_dir:
                static_dir = scenario_config.static_data_dir
                actors_path = os.path.join(static_dir, 'actors.json')
                conditions_path = os.path.join(static_dir, 'initial_conditions.json')
                if os.path.exists(actors_path) and os.path.exists(conditions_path):
                    with open(actors_path, 'r') as f:
                        actors_data = json.load(f)
                    with open(conditions_path, 'r') as f:
                        initial_conditions = json.load(f)
                    loaded_static = True
                    logger.info("Using static data from %s", static_dir)

            # Enrich initial_conditions with strategic infrastructure data
            try:
                infra_path = os.path.join(os.path.dirname(__file__), '../../data/iran_conflict/strategic_infrastructure.json')
                if os.path.exists(infra_path):
                    with open(infra_path, 'r') as f:
                        infra_data = json.load(f)
                    initial_conditions["strategic_infrastructure"] = infra_data
                    logger.info("Loaded strategic infrastructure data")
            except Exception as e:
                logger.warning("Failed to load strategic infrastructure data: %s", e)

            # If no scenario-specific data, use classifier defaults
            if not loaded_static:
                if not initial_conditions and scenario_config:
                    initial_conditions = scenario_config.default_initial_conditions.copy()
                    logger.info("Using scenario classifier default conditions: type=%s", scenario_config.scenario_type)
                elif not initial_conditions:
                    initial_conditions = {
                        "phase": "tensions", "escalation_level": 5, "oil_price": 85.0,
                        "global_risk_index": 0.5, "strait_of_hormuz_open": True,
                        "bab_el_mandeb_open": True, "suez_canal_open": True,
                        "nuclear_threshold_status": "stable", "humanitarian_impact": 0.0,
                        "casualty_estimates": {}, "active_conflicts": [], "active_negotiations": [],
                    }
                if not actors_data:
                    # No actors available - the LLM-generated answer will still work
                    # but simulation can't run without actors
                    logger.warning("No actors available for simulation — will skip simulation step")
                    actors_data = []
            job.progress_pct = 45
            _persist_job(job)

        # Import world_state / consequence_engine (needed for simulation)
        from .world_state import ActorState, ActorTier, WorldState, ActionType, ActionDomain, ACTION_DOMAIN_MAP, GeopoliticalEvent
        from .consequence_engine import ConsequenceEngine

        # ==================================================================
        # Step 6: Run parallel simulations (EXISTING logic, dynamic actors)
        # Progress: 45% → 80%
        # ==================================================================
        job.status = "simulating"
        job.progress_pct = 45
        _persist_job(job)

        # Generate agent personas from knowledge graph data (MiroFish-style)
        # Key: personas derived from DATA, not hardcoded trait tables
        population = None
        social_sim = None
        try:
            from .graph_persona_generator import generate_personas_from_graph

            population = generate_personas_from_graph(
                graph_id=graph_id or "",
                question=job.question,
                actors_data=actors_data,
                initial_conditions=initial_conditions,
                target_count=min(job.num_agents, 3000),  # Cap at 3K interacting agents
                endpoint=endpoint,
                model_name=job.model_name,
            )
            logger.info("Graph-derived personas: %d agents generated", len(population))
            job.progress_message = f"Generated {len(population)} data-derived agent personas..."
            _persist_job(job)

            # Initialize social simulation with graph-derived personas
            from .social_simulation import SocialSimulation
            social_sim = SocialSimulation(
                population=population,
                situation_data={
                    "escalation": initial_conditions.get("escalation_level", 5),
                    "oil_price": initial_conditions.get("oil_price", 85),
                    "phase": initial_conditions.get("phase", "tensions"),
                },
            )
            logger.info("Social simulation initialized with %d forums", len(social_sim.forums))
        except Exception as e:
            logger.warning("Graph persona generation failed, continuing without social sim: %s", e)
            population = None
            social_sim = None

        from .prediction_engine import PredictionEngine, RunOutcome
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_outcomes: List[RunOutcome] = []

        # Use scenario-specific actions (set by classifier earlier in pipeline)
        if scenario_config:
            available_actions = ", ".join(scenario_config.available_actions)
        else:
            available_actions = "launch_strike, missile_launch, air_strike, deploy_forces, defend_position, propose_negotiation, issue_ultimatum, public_statement, hold_position, backchannel_communication, blockade, impose_sanctions, arm_proxy, direct_proxy_attack"

        # Thread-safe progress tracking
        _progress_lock = threading.Lock()
        _completed_runs = [0]  # mutable counter in list for closure access

        def _run_single_simulation(run_idx: int) -> RunOutcome:
            """Execute a single simulation run (thread-safe — own WorldState, own CE)."""
            # Each thread gets its own WorldState and ConsequenceEngine
            ce = ConsequenceEngine()
            ws = WorldState()
            sc_defaults = scenario_config.default_initial_conditions if scenario_config else {}
            ws.escalation_level = initial_conditions.get("escalation_level", sc_defaults.get("escalation_level", 5))
            ws.oil_price = initial_conditions.get("oil_price", sc_defaults.get("oil_price", 85.0))
            ws.strait_of_hormuz_open = initial_conditions.get("strait_of_hormuz_open", sc_defaults.get("strait_of_hormuz_open", True))
            ws.phase = initial_conditions.get("phase", sc_defaults.get("phase", "tensions"))
            # Enrich WorldState with additional initial_conditions fields
            ws.global_risk_index = initial_conditions.get("global_risk_index", 0.5)
            ws.nuclear_threshold_status = initial_conditions.get("nuclear_threshold_status", "warning")
            ws.humanitarian_impact = initial_conditions.get("humanitarian_impact", 0.0)
            ws.bab_el_mandeb_open = initial_conditions.get("bab_el_mandeb_open", True)
            ws.suez_canal_open = initial_conditions.get("suez_canal_open", True)
            ws.active_conflicts = initial_conditions.get("active_conflicts", [])
            ws.active_negotiations = initial_conditions.get("active_negotiations", [])

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
                # Set initial casualties from initial_conditions casualty_estimates
                # Look up by actor_id directly (no hardcoded mapping needed)
                ic_casualties = initial_conditions.get("casualty_estimates", {})
                if ad["actor_id"] in ic_casualties:
                    actor.casualties = int(ic_casualties[ad["actor_id"]])
                else:
                    # Try common key variations (actor_id with _military suffix, etc.)
                    for suffix in ["", "_military", "_forces"]:
                        key = ad["actor_id"] + suffix
                        if key in ic_casualties:
                            actor.casualties = int(ic_casualties[key])
                            break

                ws.actors[ad["actor_id"]] = actor
                active_agents.append({
                    "agent_id": ad["actor_id"],
                    "agent_name": ad["actor_name"],
                    "agent_type": ad.get("actor_type", "Organization"),
                    "persona": {
                        "doctrine": ad.get("strategic_doctrine", ""),
                        "temperament": ad.get("leadership_temperament", ""),
                        "red_lines": ad.get("red_lines", []),
                        "belief_system": ad.get("belief_system", ""),
                        "historical_patterns": ad.get("historical_behavior_patterns", ""),
                        "primary_objective": ad.get("primary_objective", ""),
                        "constraints": ad.get("constraints", []),
                        "alliance_network": ad.get("alliance_network", []),
                        "adversaries": ad.get("adversaries", []),
                        "risk_tolerance": ad.get("risk_tolerance", 0.5),
                        "escalation_threshold": ad.get("escalation_threshold", 0.5),
                        "martyrdom_willingness": ad.get("martyrdom_willingness", 0.0),
                        "key_weapons": ad.get("key_weapons", []),
                        "nuclear_status": ad.get("nuclear_status", "none"),
                        "vulnerabilities": ad.get("existential_vulnerabilities", {}),
                        "termination_conditions": ad.get("war_termination_conditions", {}),
                    }
                })

            # Run rounds
            for round_num in range(1, job.rounds_per_run + 1):
                ws.round_num = round_num
                # Use scenario base date (defaults to today) instead of hardcoded date
                base_date = scenario_config.base_date if scenario_config else datetime.now()
                sim_date = base_date + timedelta(days=round_num)
                ws.simulated_time = sim_date.strftime("%Y-%m-%dT00:00:00Z")

                # Check termination
                should_stop, reason = ce.check_termination(ws, job.rounds_per_run)
                if should_stop:
                    break

                # Build situation JSON — include actor info so LLM knows valid targets
                actors_summary = {
                    aid: {
                        "name": a.actor_name,
                        "type": a.actor_type,
                        "force_strength": round(a.force_strength, 1),
                        "casualties": a.casualties,
                    }
                    for aid, a in ws.actors.items()
                }
                # Recent events summary (last 2 rounds, keep short for prompt budget)
                recent_events_summary = []
                for ev in ws.events:
                    if ev.round_num >= max(0, round_num - 2):
                        recent_events_summary.append(
                            f"{ev.actor_name}: {ev.action_type.value} -> {ev.target_actor_name or 'n/a'}"
                        )

                # Include previous round's social signals (if available)
                prev_social = None
                if social_sim and run_idx == 0 and hasattr(ws, '_social_signals') and ws._social_signals:
                    prev_social = ws._social_signals[-1]

                situation_data = {
                    "round": round_num,
                    "escalation": ws.escalation_level,
                    "oil_price": ws.oil_price,
                    "phase": ws.phase,
                    "hormuz": "open" if ws.strait_of_hormuz_open else "closed",
                    "bab_el_mandeb": "open" if ws.bab_el_mandeb_open else "closed",
                    "suez": "open" if ws.suez_canal_open else "closed",
                    "nuclear_status": ws.nuclear_threshold_status,
                    "actors": actors_summary,
                    "recent_events": recent_events_summary[-10:],  # cap at 10
                    # Feedback: what happened last round (enables agent learning/adaptation)
                    "round_feedback": {
                        "previous_escalation_change": round(ws.escalation_level - initial_conditions.get("escalation_level", 5), 1),
                        "total_casualties_so_far": sum(a.casualties for a in ws.actors.values()),
                        "force_balance": {
                            aid: round(a.force_strength, 1) for aid, a in ws.actors.items()
                        },
                        "rounds_remaining": job.rounds_per_run - round_num,
                        "termination_approaching": job.rounds_per_run - round_num < 5,
                    },
                    "social_sentiment": {
                        "escalation_pressure": prev_social.get("escalation_pressure", 0) if prev_social else 0,
                        "deescalation_pressure": prev_social.get("deescalation_pressure", 0) if prev_social else 0,
                        "public_mood": prev_social.get("net_pressure", 0) if prev_social else 0,
                    } if prev_social else {},
                }

                # Build real-world context bullets from initial_conditions (generic, max 8)
                ic_context_bullets = []
                for key, val in initial_conditions.items():
                    if key in ("scenario_name", "phase", "escalation_level", "oil_price"):
                        continue  # Already in situation_data
                    if isinstance(val, dict):
                        summary_parts = [f"{k}: {v}" for k, v in list(val.items())[:4]]
                        if summary_parts:
                            label = key.replace('_', ' ').title()
                            ic_context_bullets.append(f"{label}: {', '.join(summary_parts)}")
                    elif isinstance(val, list) and val:
                        label = key.replace('_', ' ').title()
                        ic_context_bullets.append(f"{label}: {', '.join(str(v) for v in val[:4])}")
                    elif isinstance(val, (str, int, float)) and val:
                        label = key.replace('_', ' ').title()
                        ic_context_bullets.append(f"{label}: {val}")
                    if len(ic_context_bullets) >= 8:
                        break

                situation_data["real_world_context"] = ic_context_bullets[:8]

                # Fetch real-time market data
                try:
                    from .market_data import MarketDataFetcher
                    market = MarketDataFetcher().fetch_all()
                    if market:
                        situation_data["market_data"] = {
                            "oil_price_brent": market.get("oil", {}).get("brent_current"),
                            "oil_change_1w": market.get("oil", {}).get("brent_1w_change"),
                            "vix": market.get("safe_havens", {}).get("vix_current"),
                            "gcc_markets_trend": market.get("gcc", {}).get("summary"),
                        }
                except Exception:
                    pass  # Non-fatal

                if conversation_context:
                    situation_data["previous_analysis"] = (
                        f"Previous analysis from earlier simulation runs suggested: "
                        f"{conversation_context}. Consider whether this analysis still "
                        f"holds given the current situation."
                    )
                if previous_outcomes:
                    situation_data["previous_outcome_probabilities"] = previous_outcomes
                situation = json.dumps(situation_data, default=str)

                # Get decisions from vLLM for all agents
                decisions = runner.run_round_sync_wrapper(
                    agents=active_agents,
                    situation_json=situation,
                    available_actions=available_actions,
                    temperature=0.7 + (run_idx * 0.005),  # 0.7-0.85 range — higher temp combats central tendency bias
                    max_tokens=300,
                )

                # Resolve actions
                round_action_counts: Dict[str, int] = {}
                round_casualties = 0
                round_no_target = 0
                for decision in decisions:
                    actor = ws.get_actor(decision.agent_id)
                    if not actor:
                        continue
                    for action_data in decision.actions[:2]:
                        try:
                            action_type = ActionType(action_data.get("action_type", "hold_position"))
                        except ValueError:
                            action_type = ActionType.HOLD_POSITION

                        round_action_counts[action_type.value] = round_action_counts.get(action_type.value, 0) + 1

                        target_id = action_data.get("target_actor_id")
                        target = ws.get_actor(target_id) if target_id else None

                        # Log when combat actions have no valid target (the main casualty bug)
                        if action_type in (ActionType.LAUNCH_STRIKE, ActionType.AIR_STRIKE,
                                           ActionType.MISSILE_LAUNCH, ActionType.DIRECT_PROXY_ATTACK) and target is None:
                            round_no_target += 1
                            logger.warning(
                                f"Run {run_idx} R{round_num}: {actor.actor_name} chose {action_type.value} "
                                f"but target_actor_id='{target_id}' not found in world state"
                            )

                        resolution = ce.resolve_action(action_type, actor, ws, target, action_data.get("params", {}))
                        ce.apply_resolution(resolution, ws)

                        # Track casualties generated this round
                        for changes in resolution.state_changes.values():
                            round_casualties += changes.get("casualties", 0)

                        # Record event in world state so subsequent rounds see history
                        ws.events.append(GeopoliticalEvent(
                            round_num=round_num,
                            timestamp=ws.simulated_time,
                            actor_id=decision.agent_id,
                            actor_name=actor.actor_name,
                            action_type=action_type,
                            action_domain=ACTION_DOMAIN_MAP.get(action_type, ActionDomain.PASSIVE),
                            target_actor_id=target_id,
                            target_actor_name=target.actor_name if target else None,
                            consequence_summary=resolution.consequence_summary,
                            escalation_delta=resolution.escalation_delta,
                        ))

                logger.info(
                    f"Run {run_idx} R{round_num}: actions={round_action_counts} "
                    f"casualties={round_casualties} no_target_combat={round_no_target}"
                )

                # Run social simulation round (only on first run to avoid redundancy)
                if social_sim and run_idx == 0:
                    try:
                        social_result = social_sim.run_social_round(
                            round_num=round_num,
                            situation_update={
                                "escalation": ws.escalation_level,
                                "oil_price": ws.oil_price,
                                "phase": ws.phase,
                                "round": round_num,
                            },
                            sample_size=min(5000, len(social_sim.population)),
                        )
                        # Store social signals for answer generation
                        if not hasattr(ws, '_social_signals'):
                            ws._social_signals = []
                        ws._social_signals.append(social_result)
                        # Feed social sentiment into next round's situation
                        situation_data["social_pressure"] = {
                            "escalation_pressure": social_result.get("escalation_pressure", 0),
                            "deescalation_pressure": social_result.get("deescalation_pressure", 0),
                            "net_pressure": social_result.get("net_pressure", 0),
                            "dominant_narrative": social_result.get("top_narratives", [("unknown", 0)])[0][0] if social_result.get("top_narratives") else "unknown",
                        }
                    except Exception:
                        pass  # Non-fatal

                # Update phase using scenario-specific thresholds
                if scenario_config and scenario_config.phase_thresholds:
                    for max_esc, phase_name in scenario_config.phase_thresholds:
                        if ws.escalation_level <= max_esc:
                            ws.phase = phase_name
                            break
                    else:
                        # Above all thresholds
                        ws.phase = scenario_config.phase_thresholds[-1][1]
                else:
                    # Fallback to default military phases
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

            # Update progress (thread-safe)
            with _progress_lock:
                _completed_runs[0] += 1
                done = _completed_runs[0]
                job.progress_message = f"Simulation run {done}/{job.num_runs} complete..."
                job.progress_pct = 45 + int((done / job.num_runs) * 35)

            return run_idx, outcome

        # Run all simulations in parallel with max 5 concurrent threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(_run_single_simulation, run_idx): run_idx
                for run_idx in range(job.num_runs)
            }
            for future in as_completed(futures):
                run_idx, outcome = future.result()
                all_outcomes.append(outcome)
                _save_run_memories(job, run_idx, outcome)

        # Persist status heading into aggregation
        _persist_job(job)

        # Step 7: Aggregate results
        job.status = "aggregating"
        job.progress_message = "Aggregating results across runs..."
        job.progress_pct = 82

        pred_engine = PredictionEngine()
        prediction = pred_engine.aggregate_runs(all_outcomes)

        job.outcomes = prediction.outcome_probabilities
        job.actor_results = prediction.actor_predictions

        # Step 8: Generate answers
        job.status = "answering"
        job.progress_message = "Generating narrative answers..."
        job.progress_pct = 88

        # Use vLLM to answer the user's question
        import requests

        previous_context_section = ""
        if conversation_context:
            previous_context_section = f"""
PREVIOUS ANALYSIS (from earlier simulation runs in this conversation):
{conversation_context}

Build on the previous analysis above. Note where this run's results confirm, refine, or contradict earlier findings.
"""

        # Build context dynamically from whatever initial_conditions contains
        ic_lines = [f"SCENARIO CONTEXT:"]
        # Include all top-level scalar/simple fields
        skip_keys = set()
        for key, val in initial_conditions.items():
            if isinstance(val, (str, int, float, bool)):
                label = key.replace('_', ' ').title()
                ic_lines.append(f"- {label}: {val}")
                skip_keys.add(key)
        # Include complex fields as JSON
        for key, val in initial_conditions.items():
            if key not in skip_keys and val:
                label = key.replace('_', ' ').title()
                ic_lines.append(f"- {label}: {json.dumps(val, indent=2)}")
        ic_context = "\n".join(ic_lines)

        # Build actor profiles context
        actor_profiles_ctx = "ACTOR PROFILES (doctrine & objectives driving their decisions):\n"
        for ad in actors_data:
            if ad.get("tier") == "information":
                continue
            constraints = ad.get("constraints", [])
            constraints_str = ", ".join(constraints[:3]) if constraints else "N/A"
            actor_profiles_ctx += (
                f"- {ad['actor_name']}: {ad.get('strategic_doctrine', 'N/A')}. "
                f"Objective: {ad.get('primary_objective', 'N/A')}. "
                f"Constraints: {constraints_str}\n"
            )

        # Collect sample key events across runs
        sample_events = []
        for o in all_outcomes[:5]:
            sample_events.extend(o.key_events[:5])

        # Fetch market data for the final report
        market_context = ""
        try:
            from .market_data import MarketDataFetcher
            mkt = MarketDataFetcher().fetch_all()
            if mkt:
                lines = ["REAL-TIME MARKET DATA:"]
                oil = mkt.get("oil", {})
                if oil.get("brent_current"):
                    lines.append(f"- Brent Crude: ${oil['brent_current']} (1w: {oil.get('brent_1w_change', '?')}%, 1mo: {oil.get('brent_1mo_change', '?')}%)")
                if oil.get("wti_current"):
                    lines.append(f"- WTI Crude: ${oil['wti_current']} (1w: {oil.get('wti_1w_change', '?')}%, 1mo: {oil.get('wti_1mo_change', '?')}%)")
                sh = mkt.get("safe_havens", {})
                if sh.get("gold_current"):
                    lines.append(f"- Gold: ${sh['gold_current']} (1w: {sh.get('gold_1w_change', '?')}%)")
                if sh.get("vix_current"):
                    lines.append(f"- VIX: {sh['vix_current']} (1w: {sh.get('vix_1w_change', '?')}%)")
                if sh.get("treasury_10y_current"):
                    lines.append(f"- 10Y Treasury: {sh['treasury_10y_current']}%")
                gcc = mkt.get("gcc", {})
                if gcc.get("summary"):
                    lines.append(f"- {gcc['summary']}")
                defense = mkt.get("defense_stocks", {})
                if isinstance(defense, dict) and "error" not in defense:
                    ds_parts = [f"{s}: ${d.get('price','?')} ({d.get('1w_change_pct','?')}% 1w)" for s, d in defense.items() if isinstance(d, dict)]
                    if ds_parts:
                        lines.append(f"- Defense stocks: {', '.join(ds_parts)}")
                shipping = mkt.get("shipping", {})
                if isinstance(shipping, dict) and "error" not in shipping:
                    for sym, d in shipping.items():
                        if isinstance(d, dict) and d.get("price"):
                            lines.append(f"- {sym}: ${d['price']} ({d.get('1w_change_pct', '?')}% 1w)")
                market_context = "\n".join(lines)
        except Exception:
            pass  # Non-fatal

        # Build social simulation context for the answer
        social_context = ""
        if social_sim:
            try:
                pop_state = social_sim.get_population_state()
                social_context = f"""
SOCIAL SIMULATION ({pop_state['total_agents']} agents across {len(pop_state['forums'])} forums):
- Sentiment: {pop_state['sentiment_distribution']}
- Forums: {json.dumps({k: v['total_posts'] for k, v in pop_state['forums'].items() if v['total_posts'] > 0})}
"""
                # Add last round's social signals
                if hasattr(all_outcomes[0], '_social_signals') or (social_sim and social_sim.round_posts):
                    last_social = social_sim._aggregate_round(job.rounds_per_run) if social_sim else {}
                    if last_social:
                        social_context += f"""- Escalation Pressure: {last_social.get('escalation_pressure', 'N/A')}
- De-escalation Pressure: {last_social.get('deescalation_pressure', 'N/A')}
- Net Pressure: {last_social.get('net_pressure', 'N/A')}
- Country Sentiments: {json.dumps(last_social.get('country_sentiments', {}), indent=2)}
- Top Narratives: {last_social.get('top_narratives', [])}
"""
            except Exception as e:
                logger.warning("Social context build failed: %s", e)

        answer_prompt = f"""You are a senior geopolitical intelligence analyst producing a structured prediction report.

{ic_context}

{actor_profiles_ctx}

{market_context}

SIMULATION RESULTS ({job.num_runs} parallel runs, {job.rounds_per_run} rounds each, {len(actors_data)} actors):
- Outcome Probabilities: {json.dumps(prediction.outcome_probabilities)}
- Average Escalation: {prediction.avg_final_escalation:.1f}/10
- Nuclear Risk: {prediction.nuclear_escalation_probability:.0%}
- Average Oil Price: ${prediction.avg_oil_price:.0f}
- Hormuz Reopened: {getattr(prediction, 'hormuz_open_probability', 0):.0%} of runs
- Duration: Average {prediction.avg_duration_rounds:.0f} rounds (range: {prediction.min_duration}-{prediction.max_duration})
- Actor Outcomes: {json.dumps(prediction.actor_predictions, indent=2)}
- Sample Simulation Events: {json.dumps(sample_events[:15])}
{social_context}
{previous_context_section}
USER QUESTION: {job.question}

Produce a structured intelligence assessment with EXACTLY these sections:

## Executive Summary
Answer the question in 2-3 sentences with specific probabilities from the simulation data.

## Methodology
Explain: {job.num_runs} parallel Monte Carlo simulations, {job.rounds_per_run} rounds each, {len(actors_data)} AI agents role-playing as real-world actors with doctrine-driven decision-making. Each agent operates with its own strategic doctrine, temperament, red lines, and objectives derived from real-world actor profiles. Outcomes are classified and aggregated across all runs to produce probability distributions.

## Key Findings
Numbered list of 4-6 major findings. Each finding MUST include:
- The specific probability or data point from the simulation
- WHY the simulation produced this result (which actor behaviors and doctrines drove it)
- What real-world data from the initial conditions supports or contradicts this finding

## Actor-by-Actor Analysis
For each major actor in the simulation results, state: average final force level, casualties, approval rating, and explain what happened to them and why based on their doctrine, constraints, and red lines.

## Market Impact Analysis
If real-time market data is available above, analyze how current oil prices, defense stocks, GCC markets, VIX, gold, and shipping rates reflect or diverge from the simulation's predicted trajectory. If market data is not available, note that market data was unavailable and provide qualitative analysis based on the simulation's oil price and economic predictions.

## Data Sources & Confidence
List the specific information sources that informed this prediction: actor profiles (doctrines, temperaments, red lines), initial conditions (war start date, escalation level, weapons dynamics, nuclear status, energy infrastructure damage), behavioral parameters, and real-time market data (if available). State overall confidence level (high/medium/low) and identify key uncertainties that could change outcomes.

Be specific. Use numbers from the simulation data. Cite the real-world context when explaining why results occurred."""

        try:
            # Try OpenAI-compatible endpoint first, then Ollama native
            answer_text = ""
            for chat_path in ["/v1/chat/completions", "/chat/completions", "/api/chat"]:
                try:
                    body = {
                        "model": job.model_name,
                        "messages": [{"role": "user", "content": answer_prompt}],
                        "temperature": 0.3,
                    }
                    if "/api/chat" not in chat_path:
                        body["max_tokens"] = 2500
                    resp = requests.post(f"{endpoint}{chat_path}", json=body, timeout=120)
                    if resp.status_code == 200:
                        data = resp.json()
                        if "choices" in data:
                            answer_text = data["choices"][0].get("message", {}).get("content", "")
                        elif "message" in data:
                            answer_text = data["message"].get("content", "")
                        if answer_text:
                            break
                except Exception:
                    continue

            if answer_text:
                import re
                answer_text = re.sub(r'<think>[\s\S]*?</think>', '', answer_text).strip()

                # Validate data grounding — ensures predictions cite source data
                try:
                    from .prediction_validator import validate_grounding, add_grounding_to_answer
                    grounding_report = validate_grounding(
                        prediction_text=answer_text,
                        source_data=initial_conditions,
                        simulation_results={
                            "outcomes": prediction.outcome_probabilities,
                            "actor_results": prediction.actor_predictions,
                            "avg_escalation": prediction.avg_final_escalation,
                            "nuclear_risk": prediction.nuclear_escalation_probability,
                            "avg_oil_price": prediction.avg_oil_price,
                        },
                    )
                    answer_text = add_grounding_to_answer(answer_text, grounding_report)
                    logger.info("Grounding score: %.0f%% (%d/%d claims grounded)",
                               grounding_report.grounding_score * 100,
                               grounding_report.grounded_claims,
                               grounding_report.total_claims)
                    if grounding_report.suspicious_claims:
                        logger.warning("Suspicious claims (possible training data leakage): %d",
                                      len(grounding_report.suspicious_claims))
                except Exception as e:
                    logger.warning("Grounding validation failed (non-fatal): %s", e)

                job.answers = {"main_answer": answer_text}
            else:
                job.answers = {"main_answer": f"Answer generation failed. Raw data is available above."}
        except Exception as e:
            job.answers = {"main_answer": f"Answer generation failed: {str(e)}. Raw simulation data is available above."}

        # Step 9: Cleanup
        job.status = "complete"
        job.progress_message = "Prediction complete."
        job.progress_pct = 100
        job.completed_at = datetime.now().isoformat()

        # Mark prediction end on the lifecycle manager (starts idle timer,
        # does NOT destroy — the instance stays warm for the next prediction).
        if gpu_lifecycle:
            try:
                prediction_cost = gpu_lifecycle.mark_prediction_end()
                job.gpu_cost = prediction_cost
                job.progress_message = (
                    f"Prediction complete. GPU cost: ${prediction_cost:.4f}. "
                    f"Instance will auto-destroy after idle timeout."
                )
            except Exception as e:
                logger.error(f"Failed to mark prediction end: {e}")

        # Persist final completed state to PostgreSQL
        _persist_job(job)

        logger.info(f"Prediction {job.prediction_id} complete. GPU cost: ${job.gpu_cost:.4f}")

    except Exception as e:
        import traceback
        logger.error(f"Pipeline failed: {e}\n{traceback.format_exc()}")
        job.status = "failed"
        job.error = str(e)
        job.progress_message = f"Failed: {str(e)}"

        # Persist failed state to PostgreSQL
        _persist_job(job)

        # On failure, mark prediction end so the idle timer starts.
        # The lifecycle manager will auto-destroy after the timeout.
        # We do NOT destroy immediately — the user might retry quickly.
        if gpu_lifecycle:
            try:
                gpu_lifecycle.mark_prediction_end()
            except Exception:
                logger.debug("Failed to mark prediction end during error cleanup")
