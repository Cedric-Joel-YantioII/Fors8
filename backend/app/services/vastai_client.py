"""
Vast.ai REST API Client.

Handles the full GPU instance lifecycle:
1. Search for cheapest available GPUs matching requirements
2. Launch instance with vLLM Docker image
3. Poll until model is loaded and API is ready
4. Return OpenAI-compatible endpoint URL
5. Destroy instance when simulation is done

API Base: https://console.vast.ai/api/v0/
Auth: Bearer token (API key from vast.ai account settings)
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('fors8.vastai')

VAST_API_BASE = "https://console.vast.ai/api/v0"

# GPU configs for each model size
MODEL_GPU_CONFIGS = {
    "Qwen/Qwen2.5-72B-Instruct": {"min_gpu_ram": 75, "gpu_name": "A100", "num_gpus": 2, "disk_gb": 200, "tp_size": 2},
    "deepseek-ai/DeepSeek-V3": {"min_gpu_ram": 75, "gpu_name": "A100", "num_gpus": 4, "disk_gb": 300, "tp_size": 4},
    "meta-llama/Llama-3.1-70B-Instruct": {"min_gpu_ram": 75, "gpu_name": "A100", "num_gpus": 2, "disk_gb": 200, "tp_size": 2},
    "Qwen/Qwen2.5-14B-Instruct": {"min_gpu_ram": 20, "gpu_name": "RTX 4090", "num_gpus": 1, "disk_gb": 80, "tp_size": 1},
}


@dataclass
class VastInstance:
    """A running Vast.ai GPU instance."""
    instance_id: int = 0
    offer_id: int = 0
    status: str = "pending"  # pending, loading, ready, failed, destroyed
    public_ip: str = ""
    ports: List[int] = field(default_factory=list)
    ssh_host: str = ""
    ssh_port: int = 0
    gpu_name: str = ""
    num_gpus: int = 0
    dph_total: float = 0.0  # dollars per hour
    model_name: str = ""
    endpoint_url: str = ""  # http://ip:port/v1 — the vLLM OpenAI-compat endpoint
    created_at: float = 0.0
    total_cost: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "status": self.status,
            "public_ip": self.public_ip,
            "endpoint_url": self.endpoint_url,
            "gpu_name": self.gpu_name,
            "num_gpus": self.num_gpus,
            "dph_total": self.dph_total,
            "model_name": self.model_name,
            "total_cost": self.total_cost,
        }


class SpendingGuardrails:
    """Prevents runaway GPU spending."""

    def __init__(self):
        import os
        self.max_spend_per_run = float(os.environ.get('VASTAI_MAX_SPEND_PER_RUN', '5.00'))
        self.max_instances = int(os.environ.get('VASTAI_MAX_INSTANCES', '2'))
        self.auto_destroy_minutes = int(os.environ.get('VASTAI_AUTO_DESTROY_MINUTES', '30'))
        self.max_price_per_hour = float(os.environ.get('VASTAI_MAX_PRICE_PER_HOUR', '3.00'))
        self.total_spent_session = 0.0
        self.active_instance_count = 0

    def check_can_launch(self, dph_total: float) -> tuple:
        """Returns (allowed: bool, reason: str)."""
        if self.active_instance_count >= self.max_instances:
            return False, f"Max {self.max_instances} concurrent instances allowed. Destroy one first."
        if dph_total > self.max_price_per_hour:
            return False, f"Offer costs ${dph_total:.2f}/hr — exceeds max ${self.max_price_per_hour:.2f}/hr limit."
        remaining_budget = self.max_spend_per_run - self.total_spent_session
        if remaining_budget <= 0:
            return False, f"Session budget of ${self.max_spend_per_run:.2f} exhausted. Spent: ${self.total_spent_session:.2f}."
        return True, "OK"

    def check_should_destroy(self, instance: 'VastInstance') -> tuple:
        """Check if an instance should be auto-destroyed."""
        if not instance.created_at:
            return False, ""
        elapsed_min = (time.time() - instance.created_at) / 60
        if elapsed_min > self.auto_destroy_minutes:
            return True, f"Instance running {elapsed_min:.0f} min — exceeds {self.auto_destroy_minutes} min auto-destroy limit."
        elapsed_cost = (elapsed_min / 60) * instance.dph_total
        if elapsed_cost > self.max_spend_per_run:
            return True, f"Instance cost ${elapsed_cost:.2f} — exceeds ${self.max_spend_per_run:.2f} per-run limit."
        return False, ""

    def record_launch(self):
        self.active_instance_count += 1

    def record_destroy(self, cost: float):
        self.active_instance_count = max(0, self.active_instance_count - 1)
        self.total_spent_session += cost


class VastAIClient:
    """Vast.ai REST API client for GPU instance management.

    Includes spending guardrails:
    - Max $/run (default $5)
    - Max concurrent instances (default 2)
    - Auto-destroy after N minutes (default 30)
    - Max $/hr per instance (default $3)
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.instances: Dict[int, VastInstance] = {}
        self.guardrails = SpendingGuardrails()
        logger.info(f"Vast.ai client initialized. Guardrails: max ${self.guardrails.max_spend_per_run}/run, "
                     f"max {self.guardrails.max_instances} instances, auto-destroy {self.guardrails.auto_destroy_minutes}min, "
                     f"max ${self.guardrails.max_price_per_hour}/hr")

    def search_offers(
        self,
        model_name: str = "Qwen/Qwen2.5-72B-Instruct",
        num_gpus: Optional[int] = None,
        max_price_per_hour: float = 5.0,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search for available GPU offers matching model requirements.

        Returns list of offers sorted by price (cheapest first).
        """
        import requests

        config = MODEL_GPU_CONFIGS.get(model_name, MODEL_GPU_CONFIGS["Qwen/Qwen2.5-72B-Instruct"])
        gpus = num_gpus or config["num_gpus"]

        # Use spot/interruptible by default — works without billing verification
        search_body = {
            "limit": limit,
            "type": "bid",
            "verified": {"eq": True},
            "rentable": {"eq": True},
            "num_gpus": {"gte": gpus},
            "gpu_ram": {"gte": config["min_gpu_ram"] * 1024},  # MB
            "dph_total": {"lte": max_price_per_hour},
            "order": [["dph_total", "asc"]],
        }
        # Only add gpu_name filter if specified (some configs use generic matching)
        if config.get("gpu_name"):
            search_body["gpu_name"] = {"eq": config["gpu_name"]}

        resp = requests.post(
            f"{VAST_API_BASE}/bundles/",
            headers=self._headers,
            json=search_body,
            timeout=15,
        )

        if resp.status_code != 200:
            logger.error(f"Search failed: {resp.status_code} {resp.text[:200]}")
            return []

        offers = resp.json().get("offers", [])
        logger.info(f"Found {len(offers)} GPU offers for {model_name} ({gpus}+ GPUs, <${max_price_per_hour}/hr)")

        return [
            {
                "id": o.get("id"),
                "gpu_name": o.get("gpu_name", ""),
                "num_gpus": o.get("num_gpus", 0),
                "gpu_ram": o.get("gpu_ram", 0),
                "dph_total": o.get("dph_total", 0),
                "inet_down": o.get("inet_down", 0),
                "disk_space": o.get("disk_space", 0),
                "reliability": o.get("reliability2", 0),
            }
            for o in offers
        ]

    def launch_instance(
        self,
        offer_id: int,
        model_name: str = "Qwen/Qwen2.5-72B-Instruct",
        label: str = "fors8-vllm",
    ) -> VastInstance:
        """Launch a GPU instance with vLLM serving the specified model.

        Args:
            offer_id: The offer ID from search_offers()
            model_name: HuggingFace model to serve
            label: Instance label for identification

        Returns:
            VastInstance with instance_id (status will be 'pending')

        Raises:
            RuntimeError if guardrails block the launch.
        """
        import requests

        config = MODEL_GPU_CONFIGS.get(model_name, MODEL_GPU_CONFIGS["Qwen/Qwen2.5-72B-Instruct"])

        # GUARDRAIL: Check spending limits before launching
        # We don't know exact dph yet, use max_price_per_hour as estimate
        allowed, reason = self.guardrails.check_can_launch(self.guardrails.max_price_per_hour)
        if not allowed:
            logger.warning(f"Launch blocked by guardrails: {reason}")
            raise RuntimeError(f"Guardrail: {reason}")

        # Build vLLM startup command — runs inside the container after boot
        onstart_cmd = (
            f"pip install vllm && "
            f"python -m vllm.entrypoints.openai.api_server "
            f"--model {model_name} "
            f"--tensor-parallel-size {config['tp_size']} "
            f"--max-model-len 4096 "
            f"--gpu-memory-utilization 0.92 "
            f"--port 8000 "
            f"--host 0.0.0.0 "
            f"--max-num-seqs 256 "
            f"--trust-remote-code "
            f"--enable-prefix-caching"
        )

        # Vast.ai API docs: env uses Docker flag format, onstart is a plain string
        create_body = {
            "image": "vllm/vllm-openai:latest",
            "disk": config["disk_gb"],
            "env": {"-p 8000:8000": "1"},
            "onstart": onstart_cmd,
            "label": label,
            "runtype": "ssh",
            "target_state": "running",
            "python_utf8": True,
            "cancel_unavail": True,
        }

        resp = requests.put(
            f"{VAST_API_BASE}/asks/{offer_id}/",
            headers=self._headers,
            json=create_body,
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            error_body = resp.text[:500]
            logger.error(f"Launch failed: HTTP {resp.status_code} — {error_body}")
            raise RuntimeError(f"Vast.ai launch failed (HTTP {resp.status_code}): {error_body}")

        data = resp.json()
        instance_id = data.get("new_contract", 0)

        instance = VastInstance(
            instance_id=instance_id,
            offer_id=offer_id,
            status="pending",
            model_name=model_name,
            created_at=time.time(),
        )

        self.instances[instance_id] = instance
        self.guardrails.record_launch()
        logger.info(f"Launched instance {instance_id} with {model_name}. "
                     f"Active instances: {self.guardrails.active_instance_count}/{self.guardrails.max_instances}")

        return instance

    def get_instance_status(self, instance_id: int) -> VastInstance:
        """Get current status and IP of an instance."""
        import requests

        resp = requests.get(
            f"{VAST_API_BASE}/instances/{instance_id}/",
            headers=self._headers,
            timeout=10,
        )

        if resp.status_code != 200:
            logger.warning(f"Status check failed for {instance_id}: {resp.status_code}")
            if instance_id in self.instances:
                return self.instances[instance_id]
            return VastInstance(instance_id=instance_id, status="unknown")

        data = resp.json()

        instance = self.instances.get(instance_id, VastInstance(instance_id=instance_id))
        instance.public_ip = data.get("public_ipaddr", "")
        instance.ports = data.get("ports", [])
        instance.ssh_host = data.get("ssh_host", "")
        instance.ssh_port = data.get("ssh_port", 0)
        instance.gpu_name = data.get("gpu_name", "")
        instance.num_gpus = data.get("num_gpus", 0)
        instance.dph_total = data.get("dph_total", 0)
        instance.status = data.get("actual_status", "pending")

        # Construct the vLLM endpoint URL
        if instance.public_ip and 8000 in (instance.ports or [8000]):
            instance.endpoint_url = f"http://{instance.public_ip}:8000/v1"

        self.instances[instance_id] = instance
        return instance

    def wait_until_ready(
        self,
        instance_id: int,
        timeout_seconds: int = 600,
        poll_interval: int = 15,
        progress_callback=None,
    ) -> VastInstance:
        """Poll until the instance is running and vLLM is serving.

        This waits for:
        1. Instance to boot (actual_status = "running")
        2. Model to download from HuggingFace (~5-10 min for 72B)
        3. vLLM to start serving (HTTP 200 on /v1/models)

        Args:
            instance_id: Instance to wait for
            timeout_seconds: Max wait time (default 10 min)
            poll_interval: Seconds between checks
            progress_callback: Optional fn(status_msg) for UI updates
        """
        import requests

        deadline = time.time() + timeout_seconds
        stage = "booting"

        while time.time() < deadline:
            instance = self.get_instance_status(instance_id)

            # GUARDRAIL: Auto-destroy if running too long
            should_destroy, destroy_reason = self.guardrails.check_should_destroy(instance)
            if should_destroy:
                logger.warning(f"Auto-destroying instance {instance_id}: {destroy_reason}")
                if progress_callback:
                    progress_callback(f"GUARDRAIL: {destroy_reason} Auto-destroying.")
                self.destroy_instance(instance_id)
                raise RuntimeError(f"Guardrail auto-destroy: {destroy_reason}")

            if instance.status == "running" and instance.endpoint_url:
                if stage == "booting":
                    stage = "loading_model"
                    if progress_callback:
                        progress_callback("Instance running. Downloading model from HuggingFace...")

                # Check if vLLM is actually serving
                try:
                    health = requests.get(
                        f"{instance.endpoint_url}/models",
                        timeout=5,
                    )
                    if health.status_code == 200:
                        models = health.json().get("data", [])
                        if models:
                            instance.status = "ready"
                            self.instances[instance_id] = instance
                            logger.info(f"Instance {instance_id} ready! Endpoint: {instance.endpoint_url}")
                            if progress_callback:
                                progress_callback(f"Model loaded! Endpoint: {instance.endpoint_url}")
                            return instance
                except (requests.ConnectionError, requests.Timeout):
                    pass  # Model still loading

                if progress_callback:
                    elapsed = int(time.time() - instance.created_at)
                    progress_callback(f"Loading model... ({elapsed}s elapsed)")

            elif progress_callback:
                progress_callback(f"Instance {instance.status}... waiting for boot")

            time.sleep(poll_interval)

        # Timeout
        instance = self.instances.get(instance_id, VastInstance(instance_id=instance_id))
        instance.status = "timeout"
        logger.error(f"Instance {instance_id} timed out after {timeout_seconds}s")
        raise TimeoutError(f"Instance {instance_id} did not become ready in {timeout_seconds}s")

    def destroy_instance(self, instance_id: int) -> bool:
        """Destroy/delete an instance permanently."""
        import requests

        resp = requests.delete(
            f"{VAST_API_BASE}/instances/{instance_id}/",
            headers=self._headers,
            timeout=10,
        )

        if resp.status_code == 200:
            instance = self.instances.get(instance_id)
            cost = 0.0
            if instance:
                elapsed_hrs = (time.time() - instance.created_at) / 3600
                instance.total_cost = elapsed_hrs * instance.dph_total
                instance.status = "destroyed"
                cost = instance.total_cost
                logger.info(f"Destroyed instance {instance_id}. Cost: ${cost:.2f}")
            self.guardrails.record_destroy(cost)
            logger.info(f"Session total spend: ${self.guardrails.total_spent_session:.2f} / ${self.guardrails.max_spend_per_run:.2f} budget")
            return True
        else:
            logger.error(f"Destroy failed for {instance_id}: {resp.status_code}")
            return False

    def launch_and_wait(
        self,
        model_name: str = "Qwen/Qwen2.5-72B-Instruct",
        num_gpus: Optional[int] = None,
        max_price: float = 5.0,
        progress_callback=None,
    ) -> VastInstance:
        """One-call convenience: search → launch (with retry) → wait → return ready endpoint."""
        if progress_callback:
            progress_callback("Searching for cheapest GPUs...")

        offers = self.search_offers(model_name, num_gpus, max_price)
        if not offers:
            raise RuntimeError(f"No GPU offers found for {model_name} under ${max_price}/hr. Try increasing the max price in Settings.")

        # Try each offer until one succeeds (offers get taken quickly)
        instance = None
        for i, offer in enumerate(offers[:5]):
            try:
                if progress_callback:
                    progress_callback(
                        f"Found {offer['gpu_name']} x{offer['num_gpus']} at ${offer['dph_total']:.2f}/hr. Launching (attempt {i+1})..."
                    )
                instance = self.launch_instance(offer["id"], model_name)
                break
            except RuntimeError as e:
                if "500" in str(e) or "server_error" in str(e):
                    logger.warning(f"Offer {offer['id']} unavailable, trying next...")
                    continue
                raise

        if not instance:
            raise RuntimeError("All GPU offers failed to launch. Try again in a minute.")

        if progress_callback:
            progress_callback(f"Instance {instance.instance_id} launched. Waiting for boot + model download...")

        instance = self.wait_until_ready(
            instance.instance_id,
            progress_callback=progress_callback,
        )

        return instance
