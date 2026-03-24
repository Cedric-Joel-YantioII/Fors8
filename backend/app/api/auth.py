"""
Authentication API routes.

Supports two auth methods:
1. API Key — standard OpenAI/OpenRouter API key (pay per token)
2. ChatGPT Sign-in — OAuth with ChatGPT Plus/Pro subscription (uses subscription credits)
"""

import traceback
from flask import request, jsonify

from . import auth_bp
from ..utils.logger import get_logger
from ..services.chatgpt_auth import get_auth_manager

logger = get_logger('mirofish.api.auth')


@auth_bp.route('/status', methods=['GET'])
def auth_status():
    """Get current authentication status."""
    try:
        mgr = get_auth_manager()
        status = mgr.get_status()

        # Also check if API key is configured
        from ..config import Config
        status["api_key_configured"] = bool(Config.LLM_API_KEY)
        status["api_base_url"] = Config.LLM_BASE_URL
        status["api_model"] = Config.LLM_MODEL_NAME

        return jsonify(status)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/login/browser', methods=['POST'])
def login_browser():
    """Start browser-based ChatGPT OAuth login.

    Opens a browser window for the user to sign in with their
    ChatGPT Plus/Pro account. Returns session info on success.
    """
    try:
        mgr = get_auth_manager()
        session = mgr.start_browser_login()

        if session:
            return jsonify({
                "success": True,
                "method": "chatgpt_oauth",
                "user_email": session.user_email,
                "subscription_plan": session.subscription_plan,
                "message": "Authenticated with ChatGPT. Simulation will use your subscription credits.",
            })
        else:
            return jsonify({
                "success": False,
                "error": "Authentication failed or timed out. Please try again.",
            }), 401

    except Exception as e:
        logger.error(f"Browser login failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/login/device', methods=['POST'])
def login_device():
    """Start device-code ChatGPT login (for headless/remote environments).

    Returns a user code and verification URL. The user visits the URL
    on any device, enters the code, and signs in.
    """
    try:
        mgr = get_auth_manager()
        session = mgr.start_device_login()

        if session:
            return jsonify({
                "success": True,
                "method": "chatgpt_oauth_device",
                "user_email": session.user_email,
                "message": "Device login successful.",
            })
        else:
            return jsonify({
                "success": False,
                "error": "Device login failed or timed out.",
            }), 401

    except Exception as e:
        logger.error(f"Device login failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Clear ChatGPT OAuth session."""
    try:
        mgr = get_auth_manager()
        mgr.logout()
        return jsonify({"success": True, "message": "Logged out from ChatGPT."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
