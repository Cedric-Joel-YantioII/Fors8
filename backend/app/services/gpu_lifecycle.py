"""
GPU Lifecycle Manager — Automated Vast.ai instance management with Ollama.

Handles the full GPU lifecycle transparently for end users:
1. Auto-provisions on first prediction request (cheapest spot instance)
2. Pulls selected Ollama model and waits for readiness
3. Keeps instance warm between predictions (configurable idle timeout)
4. Auto-destroys on inactivity to save money
5. Re-provisions automatically on next request

Singleton: use get_gpu_lifecycle() to get the shared instance.
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("fors8.gpu_lifecycle")

# ---------------------------------------------------------------------------
# Ollama model catalog — users pick one of these in Settings
# ---------------------------------------------------------------------------
OLLAMA_MODELS = {
    "qwen2.5:72b": {
        "min_vram_gb": 48,
        "min_gpus": 2,
        "size_gb": 42,
        "description": "Best JSON reliability",
    },
    "qwen2.5:32b": {
        "min_vram_gb": 24,
        "min_gpus": 1,
        "size_gb": 20,
        "description": "Good balance of speed and quality",
    },
    "qwen2.5:14b": {
        "min_vram_gb": 12,
        "min_gpus": 1,
        "size_gb": 9,
        "description": "Fast and cheap",
    },
    "deepseek-v3:latest": {
        "min_vram_gb": 48,
        "min_gpus": 2,
        "size_gb": 40,
        "description": "Best reasoning accuracy",
    },
    "llama3.1:70b": {
        "min_vram_gb": 48,
        "min_gpus": 2,
        "size_gb": 42,
        "description": "Balanced, well-tested",
    },
    "mistral:7b": {
        "min_vram_gb": 8,
        "min_gpus": 1,
        "size_gb": 4,
        "description": "Ultra-fast, cheapest option",
    },
}

VAST_API_BASE = "https://console.vast.ai/api/v0"

# Default idle timeout before auto-destroy (seconds).
# Set to 0 to disable auto-destroy (manual kill only — recommended for spot instances
# since they bill by the hour, so auto-killing at 10min wastes 50min of paid time).
DEFAULT_IDLE_TIMEOUT = int(os.environ.get("GPU_IDLE_TIMEOUT_SECONDS", "0"))  # 0 = no auto-kill (manual only)
# Background watchdog poll interval
WATCHDOG_INTERVAL = 30


class GPULifecycleManager:
    """Singleton manager for a single user's Vast.ai GPU lifecycle.

    Thread-safe: all mutable state is guarded by ``_lock``.
    """

    def __init__(self, idle_timeout: int = DEFAULT_IDLE_TIMEOUT):
        # --- configuration ---
        self.idle_timeout = idle_timeout

        # --- instance state (guarded by _lock) ---
        self._lock = threading.Lock()
        self._instance_id: Optional[int] = None
        self._offer_dph: float = 0.0
        self._gpu_name: str = ""
        self._num_gpus: int = 0
        self._public_ip: str = ""
        self._ollama_port: str = ""
        self._endpoint: str = ""  # http://{ip}:{port}
        self._model: str = ""
        self._status: str = "destroyed"  # destroyed | provisioning | pulling | ready | idle
        self._created_at: float = 0.0
        self._last_activity: float = 0.0
        self._model_ready: bool = False
        self._error: str = ""

        # cost tracking
        self._session_cost: float = 0.0
        self._prediction_start: float = 0.0

        # provisioning event — threads wait on this until the instance is ready
        self._ready_event = threading.Event()
        self._provision_error: str = ""

        # watchdog thread
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_endpoint(
        self,
        model: str = "qwen2.5:32b",
        api_key: str = "",
        timeout: int = 900,
        progress_callback=None,
    ) -> str:
        """Return a ready Ollama endpoint, provisioning a GPU if necessary.

        This is the single entry point called by the prediction pipeline.
        It blocks until the endpoint is usable (model pulled and responding).

        Args:
            model: Ollama model tag (must be a key in OLLAMA_MODELS).
            api_key: Vast.ai API key.
            timeout: Max seconds to wait for provisioning + model pull.
            progress_callback: Optional ``fn(msg)`` for UI progress updates.

        Returns:
            Endpoint URL string, e.g. ``http://1.2.3.4:12345``.

        Raises:
            RuntimeError on provisioning failure or timeout.
        """
        if not api_key:
            api_key = os.environ.get("VASTAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "No VASTAI_API_KEY configured. Add it in Settings -> Self-Hosted GPU."
            )

        with self._lock:
            self._last_activity = time.time()

            # Fast path: instance running and model ready
            if self._status in ("ready", "idle") and self._model_ready and self._model == model:
                self._status = "ready"
                logger.debug("Returning cached endpoint %s", self._endpoint)
                return self._endpoint

            # If already provisioning (maybe from another thread), just wait
            if self._status == "provisioning" or self._status == "pulling":
                needs_provision = False
            else:
                # Need a new provision
                needs_provision = True
                self._status = "provisioning"
                self._model = model
                self._model_ready = False
                self._ready_event.clear()
                self._provision_error = ""
                self._error = ""

        if needs_provision:
            # Kick off provisioning in a background thread so multiple
            # callers can wait on _ready_event concurrently.
            t = threading.Thread(
                target=self._provision_and_pull,
                args=(model, api_key, progress_callback),
                daemon=True,
            )
            t.start()

        # Wait for the instance to be ready
        ready = self._ready_event.wait(timeout=timeout)
        if not ready:
            raise RuntimeError(
                f"GPU provisioning timed out after {timeout}s. "
                f"Status: {self._status}, error: {self._provision_error}"
            )

        if self._provision_error:
            raise RuntimeError(f"GPU provisioning failed: {self._provision_error}")

        with self._lock:
            self._last_activity = time.time()
            self._status = "ready"
            return self._endpoint

    def mark_prediction_start(self):
        """Called when a prediction begins, for per-prediction cost tracking."""
        with self._lock:
            self._prediction_start = time.time()
            self._last_activity = time.time()

    def mark_prediction_end(self) -> float:
        """Called when a prediction ends. Returns the cost for this prediction."""
        with self._lock:
            self._last_activity = time.time()
            self._status = "idle"
            if self._prediction_start and self._offer_dph:
                elapsed_hrs = (time.time() - self._prediction_start) / 3600
                cost = elapsed_hrs * self._offer_dph
                self._session_cost += cost
                self._prediction_start = 0.0
                return cost
            return 0.0

    def get_status(self) -> Dict[str, Any]:
        """Return current lifecycle status for the frontend."""
        with self._lock:
            now = time.time()
            uptime = now - self._created_at if self._created_at else 0
            idle_time = now - self._last_activity if self._last_activity else 0
            time_until_destroy = max(0, self.idle_timeout - idle_time) if self._status == "idle" else None
            running_cost = 0.0
            if self._created_at and self._offer_dph:
                running_cost = (uptime / 3600) * self._offer_dph

            return {
                "instance_id": self._instance_id,
                "gpu_type": self._gpu_name,
                "num_gpus": self._num_gpus,
                "model": self._model,
                "status": self._status,
                "uptime_seconds": round(uptime, 1),
                "cost_so_far": round(self._session_cost + running_cost, 4),
                "dph_total": self._offer_dph,
                "idle_seconds": round(idle_time, 1),
                "time_until_auto_destroy": round(time_until_destroy, 1) if time_until_destroy is not None else None,
                "endpoint": self._endpoint,
                "error": self._error,
            }

    def destroy(self, reason: str = "manual"):
        """Destroy the current instance immediately."""
        with self._lock:
            instance_id = self._instance_id
            dph = self._offer_dph
            created = self._created_at
            api_key = os.environ.get("VASTAI_API_KEY", "")

        if not instance_id:
            logger.info("destroy() called but no instance running")
            return

        cost = 0.0
        if created and dph:
            cost = ((time.time() - created) / 3600) * dph

        self._do_destroy(instance_id, api_key)

        with self._lock:
            self._session_cost += cost
            self._instance_id = None
            self._endpoint = ""
            self._public_ip = ""
            self._ollama_port = ""
            self._model_ready = False
            self._status = "destroyed"
            self._created_at = 0.0
            self._last_activity = 0.0
            self._offer_dph = 0.0
            self._gpu_name = ""
            self._num_gpus = 0

        logger.info(
            "Destroyed instance %s (reason: %s). Cost this session: $%.4f",
            instance_id,
            reason,
            self._session_cost,
        )

    def shutdown(self):
        """Graceful shutdown — destroy instance and stop watchdog."""
        self._watchdog_stop.set()
        self.destroy(reason="shutdown")

    # ------------------------------------------------------------------
    # Internal: provisioning
    # ------------------------------------------------------------------

    def _provision_and_pull(
        self,
        model: str,
        api_key: str,
        progress_callback=None,
    ):
        """Background thread: search -> launch -> wait for boot -> pull model -> signal ready."""
        try:
            self._cb(progress_callback, "Searching for cheapest GPU on Vast.ai...")

            model_config = OLLAMA_MODELS.get(model)
            if not model_config:
                raise RuntimeError(
                    f"Unknown model '{model}'. Available: {list(OLLAMA_MODELS.keys())}"
                )

            # Step 1: Search for offers
            offers = self._search_offers(api_key, model_config)
            if not offers:
                raise RuntimeError(
                    f"No GPU offers found for {model} "
                    f"(need {model_config['min_vram_gb']}GB VRAM, "
                    f"{model_config['min_gpus']}+ GPUs). "
                    "Try a smaller model or wait for availability."
                )

            # Step 2: Launch cheapest offer (retry up to 5)
            instance_id = None
            offer_dph = 0.0
            for i, offer in enumerate(offers[:5]):
                try:
                    self._cb(
                        progress_callback,
                        f"Launching {offer['gpu_name']} x{offer['num_gpus']} "
                        f"at ${offer['dph_total']:.2f}/hr (attempt {i + 1})...",
                    )
                    instance_id = self._launch_instance(api_key, offer["id"])
                    offer_dph = offer["dph_total"]
                    with self._lock:
                        self._instance_id = instance_id
                        self._offer_dph = offer_dph
                        self._gpu_name = offer["gpu_name"]
                        self._num_gpus = offer["num_gpus"]
                        self._created_at = time.time()
                    break
                except RuntimeError as e:
                    logger.warning("Offer %s failed: %s", offer["id"], e)
                    continue

            if not instance_id:
                raise RuntimeError("All GPU offers failed to launch. Try again in a minute.")

            # Step 3: Wait for instance to boot and get IP + port
            self._cb(progress_callback, "Waiting for instance to boot...")
            endpoint = self._wait_for_boot(api_key, instance_id, timeout=300)

            with self._lock:
                self._endpoint = endpoint
                self._status = "pulling"

            # Step 4: Pull the model via Ollama
            self._cb(
                progress_callback,
                f"Pulling {model} ({model_config['size_gb']}GB) via Ollama...",
            )
            self._pull_model(endpoint, model, timeout=1200, progress_callback=progress_callback)

            # Step 5: Verify model is responding
            self._cb(progress_callback, "Verifying model is ready...")
            self._wait_for_model(endpoint, model, timeout=120)

            with self._lock:
                self._model_ready = True
                self._status = "ready"
                self._last_activity = time.time()

            self._cb(progress_callback, f"GPU ready! Endpoint: {endpoint}")
            logger.info(
                "Instance %s ready with %s at %s ($%.2f/hr)",
                instance_id,
                model,
                endpoint,
                offer_dph,
            )

            # Start watchdog if not already running
            self._ensure_watchdog()

            # Signal waiters
            self._ready_event.set()

        except Exception as e:
            logger.error("Provisioning failed: %s", e)
            self._provision_error = str(e)
            with self._lock:
                self._status = "destroyed"
                self._error = str(e)
            # Clean up if we managed to launch an instance
            if self._instance_id:
                try:
                    self._do_destroy(
                        self._instance_id,
                        os.environ.get("VASTAI_API_KEY", ""),
                    )
                except Exception:
                    pass
                with self._lock:
                    self._instance_id = None
            self._ready_event.set()  # unblock waiters so they see the error

    def _search_offers(
        self, api_key: str, model_config: Dict[str, Any]
    ) -> list:
        """Search Vast.ai for cheapest spot instances matching model requirements."""
        import requests

        min_vram_mb = model_config["min_vram_gb"] * 1024
        min_gpus = model_config["min_gpus"]
        # Extra disk for model download: model size + 20GB headroom
        min_disk = model_config["size_gb"] + 20

        search_body = {
            "limit": 20,
            "type": "on-demand",  # on-demand for reliability (spot hosts often phantom)
            "verified": {"eq": True},
            "rentable": {"eq": True},
            "num_gpus": {"gte": min_gpus},
            "gpu_ram": {"gte": min_vram_mb},
            "disk_space": {"gte": min_disk},
            "order": [["dph_total", "asc"]],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(
            f"{VAST_API_BASE}/bundles/",
            headers=headers,
            json=search_body,
            timeout=15,
        )

        if resp.status_code != 200:
            logger.error("Vast.ai search failed: %s %s", resp.status_code, resp.text[:200])
            return []

        offers = resp.json().get("offers", [])
        logger.info("Found %d offers for %dGB VRAM, %d+ GPUs", len(offers), model_config["min_vram_gb"], min_gpus)

        return [
            {
                "id": o.get("id"),
                "gpu_name": o.get("gpu_name", ""),
                "num_gpus": o.get("num_gpus", 0),
                "gpu_ram": o.get("gpu_ram", 0),
                "dph_total": o.get("dph_total", 0),
                "disk_space": o.get("disk_space", 0),
                "inet_down": o.get("inet_down", 0),
            }
            for o in offers
        ]

    def _launch_instance(self, api_key: str, offer_id: int) -> int:
        """Launch a Vast.ai instance with the ollama/ollama Docker image."""
        import requests

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        create_body = {
            "image": "ollama/ollama",
            "disk": 100,
            "env": {"-p 11434:11434": "1"},
            "onstart": "ollama serve",
            "label": "fors8-ollama",
            "runtype": "ssh",
            "target_state": "running",
            "python_utf8": True,
            "cancel_unavail": True,
        }

        resp = requests.put(
            f"{VAST_API_BASE}/asks/{offer_id}/",
            headers=headers,
            json=create_body,
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Vast.ai launch failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )

        data = resp.json()
        instance_id = data.get("new_contract", 0)
        if not instance_id:
            raise RuntimeError(f"Vast.ai returned no instance ID: {data}")

        logger.info("Launched instance %s on offer %s", instance_id, offer_id)
        return instance_id

    def _wait_for_boot(self, api_key: str, instance_id: int, timeout: int = 300) -> str:
        """Poll until the instance is running and we can resolve the Ollama endpoint.

        Vast.ai remaps container ports. We read the ``ports`` dict to find
        the host port mapped to container port 11434.

        Returns:
            Endpoint URL, e.g. ``http://1.2.3.4:34567``
        """
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                # Use the list endpoint — the single-instance endpoint
                # returns blank data for newly created instances on Vast.ai
                resp = requests.get(
                    f"{VAST_API_BASE}/instances/",
                    headers=headers,
                    params={"owner": "me"},
                    timeout=10,
                )
                if resp.status_code != 200:
                    time.sleep(10)
                    continue

                # Find our instance in the list
                data = {}
                for inst in resp.json().get("instances", []):
                    if inst.get("id") == instance_id:
                        data = inst
                        break

                status = data.get("actual_status", "")
                public_ip = data.get("public_ipaddr", "")
                ports = data.get("ports", {})

                if status == "running" and public_ip and ports:
                    real_port = self._extract_ollama_port(ports)
                    if real_port:
                        with self._lock:
                            self._public_ip = public_ip
                            self._ollama_port = real_port
                        endpoint = f"http://{public_ip}:{real_port}"
                        logger.info(
                            "Instance %s booted at %s (port mapping: 11434 -> %s)",
                            instance_id,
                            endpoint,
                            real_port,
                        )
                        return endpoint

                logger.debug(
                    "Instance %s status=%s ip=%s ports=%s — waiting...",
                    instance_id,
                    status,
                    public_ip,
                    bool(ports),
                )
            except Exception as e:
                logger.debug("Boot poll error: %s", e)

            time.sleep(10)

        raise RuntimeError(
            f"Instance {instance_id} did not boot within {timeout}s"
        )

    @staticmethod
    def _extract_ollama_port(ports: dict) -> str:
        """Extract the host port mapped to container port 11434 from Vast.ai ports dict.

        Vast.ai ports format example:
            {"11434/tcp": [{"HostIp": "0.0.0.0", "HostPort": "34567"}]}
        """
        for container_port, mappings in ports.items():
            if "11434" in str(container_port) and mappings:
                if isinstance(mappings, list) and len(mappings) > 0:
                    host_port = mappings[0].get("HostPort", "")
                    if host_port:
                        return str(host_port)
        return ""

    def _pull_model(
        self,
        endpoint: str,
        model: str,
        timeout: int = 600,
        progress_callback=None,
    ):
        """Pull an Ollama model on the remote instance via the Ollama API."""
        import requests

        deadline = time.time() + timeout

        # The Ollama pull endpoint streams progress as JSON lines
        try:
            resp = requests.post(
                f"{endpoint}/api/pull",
                json={"name": model, "stream": False},
                timeout=timeout,
            )
            if resp.status_code == 200:
                logger.info("Model %s pulled successfully", model)
                return
            else:
                logger.warning("Pull returned %s: %s", resp.status_code, resp.text[:200])
        except requests.Timeout:
            logger.warning("Pull request timed out, polling for readiness instead")
        except requests.ConnectionError as e:
            logger.warning("Pull connection error: %s — will retry", e)

        # Fallback: poll until the model shows up in the list
        while time.time() < deadline:
            try:
                tags_resp = requests.get(f"{endpoint}/api/tags", timeout=10)
                if tags_resp.status_code == 200:
                    models = [
                        m.get("name", "") for m in tags_resp.json().get("models", [])
                    ]
                    # Ollama tags can include `:latest` suffix
                    if any(model in m or m in model for m in models):
                        logger.info("Model %s found in tag list", model)
                        return
            except Exception:
                pass
            self._cb(progress_callback, f"Still pulling {model}...")
            time.sleep(15)

        raise RuntimeError(f"Model pull for {model} timed out after {timeout}s")

    def _wait_for_model(self, endpoint: str, model: str, timeout: int = 120):
        """Send a trivial generate request to confirm the model is loaded and responding."""
        import requests

        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                resp = requests.post(
                    f"{endpoint}/api/generate",
                    json={"model": model, "prompt": "ping", "stream": False},
                    timeout=30,
                )
                if resp.status_code == 200 and resp.json().get("response"):
                    logger.info("Model %s verified — responding to prompts", model)
                    return
            except Exception as e:
                logger.debug("Model verify attempt failed: %s", e)
            time.sleep(5)

        raise RuntimeError(f"Model {model} not responding after {timeout}s")

    # ------------------------------------------------------------------
    # Internal: destruction
    # ------------------------------------------------------------------

    @staticmethod
    def _do_destroy(instance_id: int, api_key: str):
        """Send the destroy request to Vast.ai."""
        import requests

        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.delete(
            f"{VAST_API_BASE}/instances/{instance_id}/",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Destroyed Vast.ai instance %s", instance_id)
        else:
            logger.error(
                "Failed to destroy instance %s: HTTP %s",
                instance_id,
                resp.status_code,
            )

    # ------------------------------------------------------------------
    # Internal: watchdog
    # ------------------------------------------------------------------

    def _ensure_watchdog(self):
        """Start the background watchdog thread if it is not already running."""
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self._watchdog_thread.start()
        logger.info("Watchdog started (idle timeout: %ds)", self.idle_timeout)

    def _watchdog_loop(self):
        """Background loop: check every WATCHDOG_INTERVAL seconds for idle expiry."""
        while not self._watchdog_stop.is_set():
            self._watchdog_stop.wait(WATCHDOG_INTERVAL)
            if self._watchdog_stop.is_set():
                break

            # Skip auto-destroy if timeout is 0 (manual kill only)
            if self.idle_timeout <= 0:
                continue

            with self._lock:
                if self._status not in ("idle", "ready"):
                    continue
                if not self._instance_id or not self._last_activity:
                    continue
                idle_seconds = time.time() - self._last_activity
                if idle_seconds < self.idle_timeout:
                    continue
                instance_id = self._instance_id
                dph = self._offer_dph

            logger.info(
                "Instance %s idle for %.0fs (limit %ds) — auto-destroying",
                instance_id,
                idle_seconds,
                self.idle_timeout,
            )
            self.destroy(reason=f"idle_timeout ({idle_seconds:.0f}s)")

        logger.info("Watchdog stopped")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cb(callback, msg: str):
        """Invoke progress callback if provided."""
        if callback:
            try:
                callback(msg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_lifecycle_instance: Optional[GPULifecycleManager] = None
_lifecycle_lock = threading.Lock()


def get_gpu_lifecycle() -> GPULifecycleManager:
    """Return the module-level singleton GPULifecycleManager."""
    global _lifecycle_instance
    if _lifecycle_instance is None:
        with _lifecycle_lock:
            if _lifecycle_instance is None:
                _lifecycle_instance = GPULifecycleManager()
    return _lifecycle_instance
