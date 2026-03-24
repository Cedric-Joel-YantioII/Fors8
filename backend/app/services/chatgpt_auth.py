"""
ChatGPT OAuth Authentication Service.

Enables using a ChatGPT Plus/Pro subscription to power the simulation
instead of paying per-token API credits. Uses OpenAI's official OAuth flow
(same mechanism as Codex CLI).

Flow:
1. User clicks "Sign in with ChatGPT" → opens browser OAuth flow
2. Browser returns access_token + refresh_token
3. System uses access_token to call ChatGPT backend API
4. Tokens auto-refresh before expiry
5. All requests billed against ChatGPT subscription, not API credits

Backend API:    https://chatgpt.com/backend-api
OAuth Client:   app_EMoamEEZ73f0CkXaXp7hrann (OpenAI's official client ID)
Token endpoint: https://auth.openai.com/oauth/token
Auth storage:   ~/.mirofish/auth.json (or ~/.codex/auth.json if Codex is installed)
"""

import json
import os
import time
import logging
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger('mirofish.chatgpt_auth')

# OpenAI OAuth constants (same as Codex CLI)
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_AUTH_URL = "https://auth.openai.com/authorize"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_DEVICE_CODE_URL = "https://auth.openai.com/oauth/device/code"
CHATGPT_BACKEND_URL = "https://chatgpt.com/backend-api"
OAUTH_REDIRECT_PORT = 18923
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_REDIRECT_PORT}/callback"
OAUTH_SCOPE = "openid profile email offline_access"
OAUTH_AUDIENCE = "https://api.openai.com/v1"

# Auth file paths (check multiple locations)
AUTH_FILE_PATHS = [
    os.path.expanduser("~/.mirofish/auth.json"),
    os.path.expanduser("~/.codex/auth.json"),
    os.path.expanduser("~/.chatgpt-local/auth.json"),
]


@dataclass
class ChatGPTSession:
    """Stored OAuth session."""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # Unix timestamp
    token_type: str = "Bearer"
    user_email: str = ""
    subscription_plan: str = ""  # plus, pro, etc.
    authenticated_at: str = ""

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60  # 60s buffer

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "user_email": self.user_email,
            "subscription_plan": self.subscription_plan,
            "authenticated_at": self.authenticated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatGPTSession":
        return cls(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=data.get("expires_at", 0),
            token_type=data.get("token_type", "Bearer"),
            user_email=data.get("user_email", ""),
            subscription_plan=data.get("subscription_plan", ""),
            authenticated_at=data.get("authenticated_at", ""),
        )


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to receive OAuth callback."""
    authorization_code = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/callback" and "code" in params:
            _OAuthCallbackHandler.authorization_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:50px">
                <h2>MiroFish - Authentication Successful</h2>
                <p>You can close this window and return to MiroFish.</p>
                <script>setTimeout(()=>window.close(),3000)</script>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authentication failed")

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


class ChatGPTAuthManager:
    """Manages ChatGPT OAuth authentication and token lifecycle."""

    def __init__(self):
        self._session: Optional[ChatGPTSession] = None
        self._lock = threading.Lock()

    def get_session(self) -> Optional[ChatGPTSession]:
        """Get current valid session, refreshing if needed."""
        with self._lock:
            if not self._session:
                self._session = self._load_cached_session()

            if self._session and self._session.is_expired():
                logger.info("Access token expired, refreshing...")
                refreshed = self._refresh_token(self._session.refresh_token)
                if refreshed:
                    self._session = refreshed
                    self._save_session(refreshed)
                else:
                    logger.warning("Token refresh failed — re-authentication needed")
                    self._session = None

            return self._session

    def is_authenticated(self) -> bool:
        """Check if we have a valid session."""
        session = self.get_session()
        return session is not None and session.access_token != ""

    def get_access_token(self) -> Optional[str]:
        """Get a valid access token, or None if not authenticated."""
        session = self.get_session()
        return session.access_token if session else None

    def start_browser_login(self) -> Optional[ChatGPTSession]:
        """Start the OAuth browser login flow.

        1. Starts a local HTTP server for the callback
        2. Opens the browser to OpenAI's auth page
        3. Waits for the callback with authorization code
        4. Exchanges code for tokens
        """
        import secrets
        import hashlib
        import base64

        # PKCE (Proof Key for Code Exchange) — required by OpenAI
        code_verifier = secrets.token_urlsafe(43)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        state = secrets.token_urlsafe(16)

        auth_params = {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "audience": OAUTH_AUDIENCE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        auth_url = f"{OAUTH_AUTH_URL}?{urlencode(auth_params)}"

        # Start local callback server
        _OAuthCallbackHandler.authorization_code = None
        try:
            server = HTTPServer(("localhost", OAUTH_REDIRECT_PORT), _OAuthCallbackHandler)
        except OSError as e:
            logger.error(f"Cannot start OAuth callback server on port {OAUTH_REDIRECT_PORT}: {e}. "
                         f"Is another instance running?")
            return None
        server.timeout = 120  # 2 minute timeout

        logger.info(f"Opening browser for ChatGPT login...")
        webbrowser.open(auth_url)

        # Wait for callback with a deadline to prevent infinite loop
        deadline = time.time() + 300  # 5 minute overall deadline
        while _OAuthCallbackHandler.authorization_code is None:
            if time.time() > deadline:
                logger.error("OAuth login timed out after 5 minutes")
                server.server_close()
                return None
            server.handle_request()
            if _OAuthCallbackHandler.authorization_code:
                break

        server.server_close()
        code = _OAuthCallbackHandler.authorization_code

        if not code:
            logger.error("No authorization code received")
            return None

        # Exchange code for tokens
        session = self._exchange_code(code, code_verifier)
        if session:
            self._session = session
            self._save_session(session)
            logger.info(f"Authenticated as {session.user_email or 'ChatGPT user'}")

        return session

    def start_device_login(self) -> Optional[ChatGPTSession]:
        """Start the device code login flow (for headless/remote environments).

        1. Request device code from OpenAI
        2. Display user code and verification URL
        3. Poll for token until user completes login
        """
        try:
            import requests

            # Request device code
            resp = requests.post(OAUTH_DEVICE_CODE_URL, json={
                "client_id": OAUTH_CLIENT_ID,
                "scope": OAUTH_SCOPE,
                "audience": OAUTH_AUDIENCE,
            }, timeout=10)

            if resp.status_code != 200:
                logger.error(f"Device code request failed: {resp.status_code}")
                return None

            data = resp.json()
            device_code = data.get("device_code", "")
            user_code = data.get("user_code", "")
            verification_uri = data.get("verification_uri_complete", data.get("verification_uri", ""))
            interval = data.get("interval", 5)
            expires_in = data.get("expires_in", 600)

            print(f"\n{'='*50}")
            print(f"  MiroFish - Sign in with ChatGPT")
            print(f"{'='*50}")
            print(f"  1. Go to: {verification_uri}")
            print(f"  2. Enter code: {user_code}")
            print(f"  3. Sign in with your ChatGPT account")
            print(f"{'='*50}\n")

            # Poll for token
            deadline = time.time() + expires_in
            while time.time() < deadline:
                time.sleep(interval)
                token_resp = requests.post(OAUTH_TOKEN_URL, json={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": OAUTH_CLIENT_ID,
                    "device_code": device_code,
                }, timeout=10)

                if token_resp.status_code == 200:
                    token_data = token_resp.json()
                    session = self._build_session(token_data)
                    self._session = session
                    self._save_session(session)
                    logger.info("Device login successful")
                    return session

                error = token_resp.json().get("error", "")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 1
                else:
                    logger.error(f"Device login failed: {error}")
                    return None

            logger.error("Device login timed out")
            return None

        except ImportError:
            logger.error("requests library not installed")
            return None

    def logout(self):
        """Clear the session and cached tokens."""
        self._session = None
        for path in AUTH_FILE_PATHS:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Removed auth file: {path}")

    def get_status(self) -> Dict[str, Any]:
        """Get authentication status."""
        session = self.get_session()
        if session:
            return {
                "authenticated": True,
                "method": "chatgpt_oauth",
                "user_email": session.user_email,
                "subscription_plan": session.subscription_plan,
                "token_expires_at": datetime.fromtimestamp(session.expires_at).isoformat() if session.expires_at else None,
                "authenticated_at": session.authenticated_at,
            }
        return {
            "authenticated": False,
            "method": None,
        }

    def _exchange_code(self, code: str, code_verifier: str) -> Optional[ChatGPTSession]:
        """Exchange authorization code for tokens."""
        try:
            import requests

            resp = requests.post(OAUTH_TOKEN_URL, json={
                "grant_type": "authorization_code",
                "client_id": OAUTH_CLIENT_ID,
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "code_verifier": code_verifier,
            }, timeout=10)

            if resp.status_code != 200:
                logger.error(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")
                return None

            return self._build_session(resp.json())

        except Exception as e:
            logger.error(f"Token exchange error: {e}")
            return None

    def _refresh_token(self, refresh_token: str) -> Optional[ChatGPTSession]:
        """Refresh an expired access token."""
        try:
            import requests

            resp = requests.post(OAUTH_TOKEN_URL, json={
                "grant_type": "refresh_token",
                "client_id": OAUTH_CLIENT_ID,
                "refresh_token": refresh_token,
            }, timeout=10)

            if resp.status_code != 200:
                logger.error(f"Token refresh failed: {resp.status_code}")
                return None

            data = resp.json()
            session = self._build_session(data)
            # Preserve refresh token if not returned
            if not session.refresh_token:
                session.refresh_token = refresh_token
            return session

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return None

    def _build_session(self, token_data: Dict[str, Any]) -> ChatGPTSession:
        """Build a session from token response data."""
        expires_in = token_data.get("expires_in", 3600)
        return ChatGPTSession(
            access_token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token", ""),
            expires_at=time.time() + expires_in,
            token_type=token_data.get("token_type", "Bearer"),
            authenticated_at=datetime.now().isoformat(),
        )

    def _save_session(self, session: ChatGPTSession):
        """Save session to disk."""
        path = AUTH_FILE_PATHS[0]  # ~/.mirofish/auth.json
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, 'w') as f:
            json.dump(session.to_dict(), f, indent=2)

        # Restrict file permissions — owner read/write only
        try:
            os.chmod(path, 0o600)
        except OSError:
            # os.chmod with Unix modes may not work on Windows;
            # the file is still saved, just without restricted permissions.
            logger.debug(f"Could not set file permissions on {path} (expected on Windows)")

        logger.info(f"Session saved to {path}")

    def _load_cached_session(self) -> Optional[ChatGPTSession]:
        """Load a cached session from disk."""
        for path in AUTH_FILE_PATHS:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    session = ChatGPTSession.from_dict(data)
                    if session.access_token:
                        logger.info(f"Loaded cached session from {path}")
                        return session
                except Exception as e:
                    logger.warning(f"Failed to load {path}: {e}")
        return None


class ChatGPTBackendClient:
    """Client that routes requests through the ChatGPT backend API
    instead of the standard OpenAI API. Uses OAuth session token.

    This replaces the standard OpenAI client when using subscription auth.
    Provides the same interface as LLMClient for drop-in compatibility.
    """

    def __init__(self, auth_manager: ChatGPTAuthManager):
        self.auth_manager = auth_manager

    def chat(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model: str = "gpt-4o",
        response_format: Optional[Dict] = None,
    ) -> str:
        """Send a chat request through the ChatGPT backend."""
        import requests
        import re

        token = self.auth_manager.get_access_token()
        if not token:
            raise ValueError("Not authenticated with ChatGPT. Call start_browser_login() first.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        # Use the ChatGPT backend conversation endpoint
        resp = requests.post(
            f"{CHATGPT_BACKEND_URL}/conversation",
            headers=headers,
            json=payload,
            timeout=120,
        )

        if resp.status_code == 401:
            # Token expired mid-request, try refresh
            self.auth_manager.get_session()  # This triggers refresh
            token = self.auth_manager.get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                resp = requests.post(
                    f"{CHATGPT_BACKEND_URL}/conversation",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )

        if resp.status_code != 200:
            raise ValueError(f"ChatGPT backend error: {resp.status_code} {resp.text[:200]}")

        # Parse response — ChatGPT backend may use SSE format
        content = resp.text
        # Extract the assistant message from the response
        try:
            data = resp.json()
            # Standard format
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
            # ChatGPT backend format
            elif "message" in data:
                content = data["message"].get("content", {}).get("parts", [""])[0]
        except (json.JSONDecodeError, KeyError, IndexError):
            # Try to extract from SSE stream
            lines = content.split("\n")
            for line in reversed(lines):
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        parts = chunk.get("message", {}).get("content", {}).get("parts", [])
                        if parts:
                            content = parts[0]
                            break
                    except json.JSONDecodeError:
                        continue

        # Clean thinking tags
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(self, messages: list, temperature: float = 0.3, max_tokens: int = 4096, model: str = "gpt-4o") -> Dict[str, Any]:
        """Send chat request and parse JSON response."""
        import re
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            response_format={"type": "json_object"},
        )
        cleaned = response.strip()
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        return json.loads(cleaned.strip())


# Module-level singleton
_auth_manager: Optional[ChatGPTAuthManager] = None


def get_auth_manager() -> ChatGPTAuthManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = ChatGPTAuthManager()
    return _auth_manager
