"""
Data Sources API routes.

Endpoints for importing structured data, documents, configuring scrapers,
and managing OSINT feeds for the geopolitical simulation.
"""

import os
import json
import traceback
from flask import request, jsonify

from . import data_bp
from ..config import Config
from ..utils.logger import get_logger
from ..services.data_ingestor import (
    DataIngestor, DataCategory, SourceCredibility, IngestionResult,
)
from ..services.social_media_scraper import SocialMediaScraper
from ..services.osint_scrapers import OSINTManager

logger = get_logger('mirofish.api.data')

# Module-level instances (initialized on first use)
_data_ingestor = None
_social_scraper = None
_osint_manager = None


def _get_data_ingestor(graph_id: str = None) -> DataIngestor:
    global _data_ingestor
    if _data_ingestor is None or (graph_id and _data_ingestor.graph_id != graph_id):
        zep_client = None
        if Config.ZEP_API_KEY:
            try:
                from zep_cloud.client import Zep
                zep_client = Zep(api_key=Config.ZEP_API_KEY)
            except Exception:
                pass
        _data_ingestor = DataIngestor(zep_client=zep_client, graph_id=graph_id)
    return _data_ingestor


def _get_social_scraper() -> SocialMediaScraper:
    global _social_scraper
    if _social_scraper is None:
        _social_scraper = SocialMediaScraper(
            twitter_bearer_token=os.environ.get('TWITTER_BEARER_TOKEN'),
            telegram_api_id=os.environ.get('TELEGRAM_API_ID'),
            telegram_api_hash=os.environ.get('TELEGRAM_API_HASH'),
            data_ingestor=_get_data_ingestor(),
        )
        _social_scraper.configure_accounts()
    return _social_scraper


def _get_osint_manager() -> OSINTManager:
    global _osint_manager
    if _osint_manager is None:
        _osint_manager = OSINTManager(data_ingestor=_get_data_ingestor())
        _osint_manager.configure(
            newsapi_key=os.environ.get('NEWSAPI_KEY'),
            youtube_api_key=os.environ.get('YOUTUBE_API_KEY'),
            newsdata_key=os.environ.get('NEWSDATA_KEY'),
            mediastack_key=os.environ.get('MEDIASTACK_KEY'),
            gnews_key=os.environ.get('GNEWS_KEY'),
            acled_email=os.environ.get('ACLED_EMAIL'),
            acled_key=os.environ.get('ACLED_KEY'),
        )
    return _osint_manager


# ============== Structured Data Import ==============

@data_bp.route('/import/structured', methods=['POST'])
def import_structured():
    """Import structured JSON data (military capabilities, economic indicators, etc.).

    Request body:
    {
        "data": [...],
        "source_name": "sipri_arms_transfers",
        "category": "military_capability",
        "credibility": "institutional",
        "graph_id": "optional_graph_id"
    }
    """
    try:
        body = request.get_json()
        if not body or 'data' not in body:
            return jsonify({"error": "Missing 'data' field"}), 400

        graph_id = body.get('graph_id')
        ingestor = _get_data_ingestor(graph_id)

        category = DataCategory(body.get('category', 'military_capability'))
        credibility = SourceCredibility(body.get('credibility', 'institutional'))

        result = ingestor.ingest_json(
            data=body['data'],
            source_name=body.get('source_name', 'manual_upload'),
            category=category,
            credibility=credibility,
        )

        return jsonify({
            "success": result.success,
            "records_ingested": result.records_ingested,
            "records_failed": result.records_failed,
            "errors": result.errors,
        })

    except Exception as e:
        logger.error(f"Structured import failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@data_bp.route('/import/document', methods=['POST'])
def import_document():
    """Import an unstructured document (intelligence report, news article, etc.).

    Request body:
    {
        "text": "document content...",
        "source_name": "cia_assessment_march2026",
        "category": "intelligence_report",
        "credibility": "official",
        "actors_mentioned": ["usa", "iran"],
        "graph_id": "optional"
    }
    """
    try:
        body = request.get_json()
        if not body or 'text' not in body:
            return jsonify({"error": "Missing 'text' field"}), 400

        graph_id = body.get('graph_id')
        ingestor = _get_data_ingestor(graph_id)

        category = DataCategory(body.get('category', 'intelligence_report'))
        credibility = SourceCredibility(body.get('credibility', 'news_tier1'))

        result = ingestor.ingest_document(
            text=body['text'],
            source_name=body.get('source_name', 'manual_document'),
            category=category,
            credibility=credibility,
            actors_mentioned=body.get('actors_mentioned'),
            timestamp=body.get('timestamp'),
        )

        return jsonify({
            "success": result.success,
            "records_ingested": result.records_ingested,
        })

    except Exception as e:
        logger.error(f"Document import failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@data_bp.route('/import/package', methods=['POST'])
def import_data_package():
    """Import a pre-built data package (e.g., Iran conflict data).

    Request body:
    {
        "package": "iran_conflict",
        "graph_id": "optional"
    }
    """
    try:
        body = request.get_json() or {}
        package_name = body.get('package', 'iran_conflict')

        package_dir = os.path.join(
            os.path.dirname(__file__), f'../../data/{package_name}'
        )
        package_dir = os.path.abspath(package_dir)

        if not os.path.isdir(package_dir):
            return jsonify({"error": f"Package not found: {package_name}"}), 404

        graph_id = body.get('graph_id')
        ingestor = _get_data_ingestor(graph_id)

        result = ingestor.ingest_data_package(package_dir)

        return jsonify({
            "success": result.success,
            "records_ingested": result.records_ingested,
            "records_failed": result.records_failed,
            "errors": result.errors[:10],  # Limit error output
        })

    except Exception as e:
        logger.error(f"Package import failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ============== Scraper Management ==============

@data_bp.route('/scraper/configure', methods=['POST'])
def configure_scraper():
    """Configure social media scraper accounts and OSINT feeds.

    Request body:
    {
        "social_media": {
            "accounts": [...],  // Optional: override default accounts
            "twitter_bearer_token": "...",
            "telegram_api_id": "...",
            "telegram_api_hash": "..."
        },
        "osint": {
            "newsapi_key": "...",
            "feeds": [...]
        }
    }
    """
    try:
        body = request.get_json() or {}

        # Configure social media scraper
        sm_config = body.get('social_media', {})
        scraper = _get_social_scraper()

        if sm_config.get('twitter_bearer_token'):
            scraper.twitter_bearer_token = sm_config['twitter_bearer_token']
        if sm_config.get('telegram_api_id'):
            scraper.telegram_api_id = sm_config['telegram_api_id']
            scraper.telegram_api_hash = sm_config.get('telegram_api_hash', '')

        if 'accounts' in sm_config:
            scraper.configure_accounts(sm_config['accounts'])

        # Configure OSINT
        osint_config = body.get('osint', {})
        osint = _get_osint_manager()
        osint.configure(
            newsapi_key=osint_config.get('newsapi_key'),
            feeds=osint_config.get('feeds'),
        )

        return jsonify({
            "success": True,
            "social_media_accounts": len(scraper.accounts),
            "osint_feeds_configured": True,
        })

    except Exception as e:
        logger.error(f"Scraper configure failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@data_bp.route('/scraper/run', methods=['POST'])
def run_scraper():
    """Trigger a manual scrape of all configured sources.

    Request body (optional):
    {
        "sources": ["social_media", "osint"],  // Which to run, default both
        "query": "Iran war 2026"  // OSINT search query
    }
    """
    try:
        body = request.get_json() or {}
        sources = body.get('sources', ['social_media', 'osint'])
        query = body.get('query', 'Iran Israel war 2026')

        results = {}

        if 'social_media' in sources:
            scraper = _get_social_scraper()
            sm_results = scraper.scrape_all()
            total_posts = sum(len(posts) for posts in sm_results.values())
            results['social_media'] = {
                "actors_scraped": len(sm_results),
                "total_posts": total_posts,
            }

        if 'osint' in sources:
            osint = _get_osint_manager()
            osint_results = osint.fetch_all(query=query)
            results['osint'] = {
                "sources_fetched": len(osint_results.get('sources', {})),
            }

        return jsonify({
            "success": True,
            "results": results,
        })

    except Exception as e:
        logger.error(f"Scraper run failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@data_bp.route('/scraper/status', methods=['GET'])
def scraper_status():
    """Get status of all scrapers and feeds."""
    try:
        scraper = _get_social_scraper()
        osint = _get_osint_manager()

        return jsonify({
            "social_media": scraper.get_status(),
            "osint": osint.get_status(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============== Data Source Management ==============

@data_bp.route('/sources', methods=['GET'])
def list_sources():
    """List all imported data sources."""
    try:
        ingestor = _get_data_ingestor()
        return jsonify({
            "sources": ingestor.list_sources(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@data_bp.route('/sources/<source_id>', methods=['DELETE'])
def delete_source(source_id: str):
    """Remove a data source tracking entry."""
    try:
        ingestor = _get_data_ingestor()
        removed = ingestor.remove_source(source_id)
        if removed:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Source not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============== Prediction Queries ==============

@data_bp.route('/predict/ask', methods=['POST'])
def predict_ask():
    """Ask a prediction question based on simulation results.

    Request body:
    {
        "question": "Who will win the war?",
        "simulation_id": "sim_xxx"  // optional — uses latest if not provided
    }
    """
    try:
        body = request.get_json() or {}
        question = body.get('question', '')

        if not question:
            return jsonify({"error": "Missing 'question' field"}), 400

        from ..services.prediction_engine import PredictionEngine, PredictionResult

        # For now, return the prediction questions framework
        # Full implementation requires completed simulation runs
        engine = PredictionEngine()

        return jsonify({
            "question": question,
            "answer": "Simulation runs required. Configure GPU provider in Settings, run a simulation, then ask questions about the results.",
            "available_questions": [
                {"id": q[0], "question": q[1]}
                for q in engine.__class__.__mro__[0].__module__
            ] if False else [
                "Who will win the war?",
                "How long will it last?",
                "How will the winner win?",
                "What will it cost each side?",
                "What happens to proxy groups?",
                "Probability of nuclear escalation?",
            ],
            "status": "needs_simulation_data",
        })

    except Exception as e:
        logger.error(f"Prediction query failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
