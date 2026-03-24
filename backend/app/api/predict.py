"""
Prediction API — the main endpoint users interact with.

POST /api/predict        — Submit a prediction question
GET  /api/predict/:id    — Get prediction status and results
"""

import os
import re
import traceback
from flask import request, jsonify, Blueprint

from ..utils.logger import get_logger
from ..services.predict_pipeline import create_prediction, get_job

logger = get_logger('fors8.api.predict')

predict_bp = Blueprint('predict', __name__)


@predict_bp.route('', methods=['POST'])
def start_prediction():
    """Submit a prediction question.

    Accepts multipart form data:
    - question: The prediction question (required)
    - files: Optional file attachments (PDF, MD, TXT, etc.)

    Returns { prediction_id, status } immediately.
    The pipeline runs in the background — poll GET /api/predict/:id for progress.
    """
    try:
        question = request.form.get('question', '').strip()

        if not question:
            return jsonify({"error": "No question provided"}), 400

        # Get config — re-read .env every time in case endpoint changed
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env'), override=True)
        except ImportError:
            pass  # dotenv not installed; rely on existing environment variables

        vllm_endpoint = request.form.get('vllm_endpoint', '') or os.environ.get('VLLM_ENDPOINT', '')
        model_name = request.form.get('model_name', '') or os.environ.get('VLLM_MODEL', 'qwen2.5:72b')

        logger.info(f"Predict request: question='{question[:50]}...' endpoint={vllm_endpoint} model={model_name}")

        # Handle file uploads (ingest into data pipeline)
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
        MAX_FILES = 10
        ALLOWED_EXTENSIONS = {'.pdf', '.md', '.txt', '.doc', '.docx', '.png', '.jpg', '.jpeg'}

        uploaded_files = request.files.getlist('files')
        if uploaded_files:
            from ..services.data_ingestor import DataIngestor, DataCategory, SourceCredibility
            ingestor = DataIngestor()
            for f in uploaded_files[:MAX_FILES]:
                if not f.filename:
                    continue
                # Sanitize filename: strip path traversal components
                safe_name = os.path.basename(f.filename)
                safe_name = re.sub(r'[^\w.\-]', '_', safe_name)
                # Validate extension
                _, ext = os.path.splitext(safe_name)
                if ext.lower() not in ALLOWED_EXTENSIONS:
                    logger.warning(f"Rejected upload with disallowed extension: {safe_name}")
                    continue
                # Read with size limit
                content_bytes = f.read(MAX_FILE_SIZE + 1)
                if len(content_bytes) > MAX_FILE_SIZE:
                    logger.warning(f"Rejected oversized upload: {safe_name}")
                    continue
                content = content_bytes.decode('utf-8', errors='replace')
                ingestor.ingest_document(
                    text=content,
                    source_name=safe_name,
                    category=DataCategory.INTELLIGENCE_REPORT,
                    credibility=SourceCredibility.INSTITUTIONAL,
                )
                logger.info(f"Ingested uploaded file: {safe_name}")

        # Create prediction job (runs in background thread)
        job = create_prediction(
            question=question,
            model_name=model_name,
            vllm_endpoint=vllm_endpoint,
            num_runs=3,  # Start with 3 runs for faster results
            num_agents=17,  # Use the 17 defined actors (not 100K mass agents for first test)
        )

        return jsonify({
            "prediction_id": job.prediction_id,
            "status": job.status,
            "message": "Prediction started. Poll GET /api/predict/{id} for progress.",
        })

    except Exception as e:
        logger.error(f"Prediction start failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@predict_bp.route('/<prediction_id>', methods=['GET'])
def get_prediction(prediction_id: str):
    """Get prediction status and results.

    Returns the full PredictionJob state including:
    - status: queued/provisioning/loading_model/simulating/aggregating/answering/complete/failed
    - progress_message: Human-readable progress text
    - progress_pct: 0-100 progress percentage
    - outcomes: Probability distribution (when complete)
    - actor_results: Per-actor stats (when complete)
    - answers: Narrative answers (when complete)
    """
    # Validate prediction_id format (expected: UUID or alphanumeric identifier)
    if not prediction_id or not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', prediction_id):
        return jsonify({"error": "Invalid prediction ID"}), 400

    job = get_job(prediction_id)
    if not job:
        return jsonify({"error": "Prediction not found"}), 404

    return jsonify(job.to_dict())
