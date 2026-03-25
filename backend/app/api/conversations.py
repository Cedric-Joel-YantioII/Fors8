"""
Conversations API — manage multi-turn prediction conversations.

POST   /api/conversations                  — Create a new conversation
GET    /api/conversations                  — List all conversations
GET    /api/conversations/:id              — Get conversation with messages
DELETE /api/conversations/:id              — Delete a conversation
POST   /api/conversations/:id/messages     — Add a message (triggers prediction for user msgs)
GET    /api/conversations/:id/predictions  — Get all predictions in a conversation
"""

import os
import re
import traceback
import uuid
from datetime import datetime
from flask import request, jsonify, Blueprint

from ..utils.logger import get_logger

logger = get_logger('fors8.api.conversations')

# Attempt to import Database service; handle gracefully if not yet created
try:
    from ..services.database import Database
    db = Database()
except Exception:
    db = None
    logger.warning("Database service not available — conversations API will return 503")

# Attempt to import prediction pipeline
try:
    from ..services.predict_pipeline import create_prediction, get_job
except Exception:
    create_prediction = None
    get_job = None
    logger.warning("Predict pipeline not available — prediction triggers disabled")

conversations_bp = Blueprint('conversations', __name__)


def _require_db():
    """Return an error response tuple if the database is unavailable."""
    if db is None:
        return jsonify({"error": "Database service not available"}), 503
    return None


def _generate_title(content: str) -> str:
    """Auto-generate a short title from the first message content."""
    # Take first 60 chars, trim to last word boundary
    title = content.strip()
    if len(title) > 60:
        title = title[:60].rsplit(' ', 1)[0] + '...'
    return title or "New Conversation"


# ---------------------------------------------------------------------------
# POST /api/conversations — Create a new conversation
# ---------------------------------------------------------------------------
@conversations_bp.route('', methods=['POST'])
def create_conversation():
    """Create a new conversation.

    Body: { "title": "optional title" }
    Returns: { conversation_id, title }
    """
    err = _require_db()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '').strip() or "New Conversation"

        conversation = db.create_conversation(title=title)
        if not conversation:
            return jsonify({"error": "Failed to create conversation"}), 500

        return jsonify({
            "id": conversation["id"],
            "title": conversation["title"],
            "created_at": conversation.get("created_at"),
            "updated_at": conversation.get("updated_at"),
        }), 201

    except Exception as e:
        logger.error(f"Failed to create conversation: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/conversations — List all conversations
# ---------------------------------------------------------------------------
@conversations_bp.route('', methods=['GET'])
def list_conversations():
    """List all conversations ordered by most recent first.

    Returns: [{ id, title, created_at, message_count, last_message_preview }]
    """
    err = _require_db()
    if err:
        return err

    try:
        conversations = db.list_conversations()
        return jsonify(conversations)

    except Exception as e:
        logger.error(f"Failed to list conversations: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/conversations/:id — Get conversation with all messages
# ---------------------------------------------------------------------------
@conversations_bp.route('/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id: str):
    """Get a conversation with all its messages.

    Returns: { id, title, messages: [{ role, content, prediction_id, created_at }] }
    """
    err = _require_db()
    if err:
        return err

    try:
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            return jsonify({"error": "Conversation not found"}), 404

        return jsonify(conversation)

    except Exception as e:
        logger.error(f"Failed to get conversation {conversation_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/conversations/:id — Delete a conversation
# ---------------------------------------------------------------------------
@conversations_bp.route('/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    err = _require_db()
    if err:
        return err

    try:
        success = db.delete_conversation(conversation_id)
        if not success:
            return jsonify({"error": "Conversation not found"}), 404

        return jsonify({"message": "Conversation deleted"}), 200

    except Exception as e:
        logger.error(f"Failed to delete conversation {conversation_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/conversations/:id/messages — Add a message to a conversation
# ---------------------------------------------------------------------------
@conversations_bp.route('/<conversation_id>/messages', methods=['POST'])
def add_message(conversation_id: str):
    """Add a message to a conversation.

    Body: { "content": "Who will win?", "role": "user" }

    If role is "user", triggers a prediction with full conversation history
    as context so agents see all prior analysis.

    Returns: { message_id, prediction_id }
    """
    err = _require_db()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        content = (data.get('content') or '').strip()
        role = (data.get('role') or 'user').strip()

        if not content:
            return jsonify({"error": "Message content is required"}), 400

        if role not in ('user', 'assistant', 'system'):
            return jsonify({"error": "Role must be 'user', 'assistant', or 'system'"}), 400

        # Verify conversation exists
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            return jsonify({"error": "Conversation not found"}), 404

        # Auto-update title from first user message if still default
        if conversation.get("title") == "New Conversation" and role == "user":
            auto_title = _generate_title(content)
            try:
                db.update_conversation(conversation_id, title=auto_title)
            except Exception:
                pass  # Non-critical — title update failure shouldn't block message

        # Save the user/system message
        message = db.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )

        if not message:
            return jsonify({"error": "Failed to save message"}), 500

        prediction_id = None

        # If user message, trigger a prediction with full conversation context
        if role == 'user' and create_prediction is not None:
            try:
                # Build context from all previous messages in the conversation
                # so agents see the full analysis history
                messages = conversation.get('messages', [])
                context_parts = []
                for msg in messages:
                    prefix = "User" if msg["role"] == "user" else "Assistant"
                    context_parts.append(f"{prefix}: {msg['content']}")
                # Append the current new message
                context_parts.append(f"User: {content}")

                # Construct the question with conversation context
                if len(context_parts) > 1:
                    context_str = "\n\n".join(context_parts)
                    question_with_context = (
                        f"Previous conversation context:\n"
                        f"---\n{context_str}\n---\n\n"
                        f"Based on the above conversation, answer the latest question: {content}"
                    )
                else:
                    question_with_context = content

                # Read config from environment
                try:
                    from dotenv import load_dotenv
                    load_dotenv(
                        os.path.join(os.path.dirname(__file__), '../../../.env'),
                        override=True,
                    )
                except ImportError:
                    pass

                vllm_endpoint = os.environ.get('VLLM_ENDPOINT', '')
                model_name = os.environ.get('VLLM_MODEL', 'qwen2.5:72b')

                job = create_prediction(
                    question=question_with_context,
                    model_name=model_name,
                    vllm_endpoint=vllm_endpoint,
                    num_runs=10,
                    num_agents=17,
                )
                prediction_id = job.prediction_id

                # Store the prediction_id on the user message
                try:
                    db.update_message(message["id"], prediction_id=prediction_id)
                except Exception:
                    pass  # Best-effort — some DB implementations may not have update_message

                logger.info(
                    f"Triggered prediction {prediction_id} for conversation "
                    f"{conversation_id} with {len(messages)} prior messages as context"
                )

            except Exception as e:
                logger.error(f"Failed to trigger prediction: {e}\n{traceback.format_exc()}")
                # Don't fail the message add just because prediction failed

        return jsonify({
            "message_id": message["id"],
            "prediction_id": prediction_id,
        }), 201

    except Exception as e:
        logger.error(f"Failed to add message to {conversation_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/conversations/:id/predictions — Get all predictions in a conversation
# ---------------------------------------------------------------------------
@conversations_bp.route('/<conversation_id>/predictions', methods=['GET'])
def get_conversation_predictions(conversation_id: str):
    """Get all predictions associated with a conversation.

    Returns: [{ prediction_id, question, status, outcomes, answers }]
    """
    err = _require_db()
    if err:
        return err

    if get_job is None:
        return jsonify({"error": "Prediction service not available"}), 503

    try:
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            return jsonify({"error": "Conversation not found"}), 404

        # Collect prediction_ids from messages
        prediction_ids = []
        for msg in conversation.get('messages', []):
            pid = msg.get('prediction_id')
            if pid and pid not in prediction_ids:
                prediction_ids.append(pid)

        # Fetch each prediction's status
        predictions = []
        for pid in prediction_ids:
            job = get_job(pid)
            if job:
                job_dict = job.to_dict()
                predictions.append({
                    "prediction_id": pid,
                    "question": job_dict.get("question", ""),
                    "status": job_dict.get("status", "unknown"),
                    "outcomes": job_dict.get("outcomes", {}),
                    "answers": job_dict.get("answers", {}),
                })
            else:
                predictions.append({
                    "prediction_id": pid,
                    "question": "",
                    "status": "not_found",
                    "outcomes": {},
                    "answers": {},
                })

        return jsonify(predictions)

    except Exception as e:
        logger.error(
            f"Failed to get predictions for {conversation_id}: {e}\n{traceback.format_exc()}"
        )
        return jsonify({"error": str(e)}), 500
