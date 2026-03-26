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
        # Handle both JSON and form data (frontend sends JSON for text-only, form for file uploads)
        if request.is_json:
            data = request.get_json()
            question = (data.get('question', '') or '').strip()
        else:
            question = (request.form.get('question', '') or '').strip()

        if not question:
            return jsonify({"error": "No question provided"}), 400

        # Get config — re-read .env every time in case endpoint changed
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env'), override=True)
        except ImportError:
            pass  # dotenv not installed; rely on existing environment variables

        # If the user provides an explicit endpoint, use it directly.
        # Otherwise leave blank — the GPU lifecycle manager will auto-provision.
        vllm_endpoint = request.form.get('vllm_endpoint', '') or os.environ.get('VLLM_ENDPOINT', '')
        model_name = request.form.get('model_name', '') or os.environ.get('VLLM_MODEL', 'qwen2.5:32b')

        logger.info(f"Predict request: question='{question[:50]}...' endpoint={vllm_endpoint} model={model_name}")

        # Handle file uploads — collect contents into seed_documents so the
        # prediction pipeline can include them in graph building and ingestion.
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
        MAX_FILES = 10
        ALLOWED_EXTENSIONS = {'.pdf', '.md', '.txt', '.doc', '.docx', '.png', '.jpg', '.jpeg'}

        seed_documents = []
        uploaded_files = request.files.getlist('files')
        if uploaded_files:
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
                seed_documents.append({"name": safe_name, "content": content})
                logger.info(f"Collected uploaded file for pipeline: {safe_name}")

        # Create prediction job (runs in background thread)
        # seed_documents are carried on the PredictionJob so the pipeline
        # can include them in graph building and DataIngestor ingestion.
        job = create_prediction(
            question=question,
            model_name=model_name,
            vllm_endpoint=vllm_endpoint,
            num_runs=100,
            num_agents=3000,
            seed_documents=seed_documents,
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
    if job:
        return jsonify(job.to_dict())

    # Fall back to database for completed/persisted predictions
    try:
        from ..services.database import get_db
        db_pred = get_db().get_prediction(prediction_id)
        if db_pred:
            return jsonify(db_pred)
    except Exception:
        pass

    return jsonify({"error": "Prediction not found"}), 404


@predict_bp.route('/gpu/status', methods=['GET'])
def gpu_status():
    """Get GPU instance status — is it running, idle, cost so far."""
    try:
        from ..services.gpu_lifecycle import get_gpu_lifecycle
        lifecycle = get_gpu_lifecycle()
        return jsonify(lifecycle.get_status())
    except Exception as e:
        return jsonify({"status": "unavailable", "error": str(e)})


@predict_bp.route('/gpu/destroy', methods=['POST'])
def gpu_destroy():
    """Manually destroy the GPU instance to stop billing."""
    try:
        from ..services.gpu_lifecycle import get_gpu_lifecycle
        lifecycle = get_gpu_lifecycle()
        lifecycle.destroy(reason="manual_user_request")
        return jsonify({"success": True, "message": "GPU instance destroyed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
