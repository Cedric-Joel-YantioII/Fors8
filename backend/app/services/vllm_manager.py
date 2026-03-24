"""
vLLM GPU Inference Manager.

Manages self-hosted vLLM instances on cloud GPUs (Vast.ai, RunPod, etc.)
for running 100K+ agent simulations affordably.

Architecture:
- Provisions GPU instances via Vast.ai API
- Deploys vLLM Docker container with chosen model
- Exposes OpenAI-compatible API endpoint
- Runs parallel simulation batches across instances
- Tears down instances when done

Supported models (all open, run locally):
- Qwen/Qwen2.5-72B-Instruct (best tool-calling reliability)
- deepseek-ai/DeepSeek-V3 (best reasoning)
- meta-llama/Llama-3.1-70B-Instruct (balanced)
- Qwen/Qwen2.5-14B-Instruct (fast, cheap, RTX 4090 compatible)
"""

import json
import logging
import os
import time
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger('mirofish.vllm_manager')


# Pre-configured model options
AVAILABLE_MODELS = {
    "qwen2.5-72b": {
        "hf_name": "Qwen/Qwen2.5-72B-Instruct",
        "min_gpus": 2,
        "recommended_gpus": 4,
        "min_vram_gb": 80,
        "gpu_type": "A100_80GB",
        "throughput_est": "200-400 req/sec on 2×A100",
        "strengths": "Best JSON/tool-calling reliability, multilingual",
    },
    "deepseek-v3": {
        "hf_name": "deepseek-ai/DeepSeek-V3",
        "min_gpus": 4,
        "recommended_gpus": 8,
        "min_vram_gb": 80,
        "gpu_type": "A100_80GB",
        "throughput_est": "100-200 req/sec on 4×A100",
        "strengths": "Best reasoning, most accurate predictions",
    },
    "llama3-70b": {
        "hf_name": "meta-llama/Llama-3.1-70B-Instruct",
        "min_gpus": 2,
        "recommended_gpus": 4,
        "min_vram_gb": 80,
        "gpu_type": "A100_80GB",
        "throughput_est": "200-500 req/sec on 2×A100",
        "strengths": "Balanced reasoning and speed",
    },
    "qwen2.5-14b": {
        "hf_name": "Qwen/Qwen2.5-14B-Instruct",
        "min_gpus": 1,
        "recommended_gpus": 1,
        "min_vram_gb": 24,
        "gpu_type": "RTX_4090",
        "throughput_est": "500-1000 req/sec on 1×4090",
        "strengths": "Fast, cheap, good for mass agents. 4090 compatible.",
    },
}

# Vast.ai GPU pricing estimates (as of March 2026)
GPU_PRICING = {
    "A100_80GB": {"price_per_hr": 1.50, "vram_gb": 80},
    "A100_40GB": {"price_per_hr": 1.00, "vram_gb": 40},
    "H100_80GB": {"price_per_hr": 2.50, "vram_gb": 80},
    "RTX_4090": {"price_per_hr": 0.40, "vram_gb": 24},
    "RTX_3090": {"price_per_hr": 0.25, "vram_gb": 24},
}


@dataclass
class GPUInstance:
    """A provisioned GPU instance running vLLM."""
    instance_id: str = ""
    provider: str = "vastai"  # vastai, runpod, lambda, local
    gpu_type: str = "A100_80GB"
    num_gpus: int = 2
    model_name: str = ""
    endpoint_url: str = ""  # e.g., http://instance-ip:8000/v1
    status: str = "provisioning"  # provisioning, loading_model, ready, running, terminated
    created_at: str = ""
    cost_per_hour: float = 0.0
    total_cost: float = 0.0


@dataclass
class ParallelRunConfig:
    """Configuration for parallel simulation runs."""
    num_runs: int = 10
    agents_per_run: int = 100000
    active_ratio: float = 0.10  # % of agents active per round
    rounds_per_run: int = 10
    model_id: str = "qwen2.5-72b"
    scenarios: List[str] = field(default_factory=lambda: ["baseline"])
    random_seeds: List[int] = field(default_factory=list)

    def estimate_total_calls(self) -> int:
        active_per_round = int(self.agents_per_run * self.active_ratio)
        return active_per_round * self.rounds_per_run * self.num_runs

    def estimate_time_minutes(self, throughput_per_sec: int = 300) -> float:
        total_calls = self.estimate_total_calls()
        return total_calls / throughput_per_sec / 60

    def estimate_cost(self, cost_per_hour: float = 3.0) -> float:
        time_hrs = self.estimate_time_minutes() / 60
        return time_hrs * cost_per_hour


class VLLMManager:
    """Manages vLLM GPU instances for large-scale simulations."""

    def __init__(self, vastai_api_key: Optional[str] = None):
        self.vastai_api_key = vastai_api_key or os.environ.get('VASTAI_API_KEY', '')
        self.instances: Dict[str, GPUInstance] = {}
        self._active_runs: Dict[str, Dict] = {}

    def get_available_models(self) -> Dict[str, Any]:
        """Return available models with specs and pricing."""
        result = {}
        for model_id, spec in AVAILABLE_MODELS.items():
            gpu_info = GPU_PRICING.get(spec["gpu_type"], {})
            cost = gpu_info.get("price_per_hr", 0) * spec["recommended_gpus"]
            result[model_id] = {
                **spec,
                "estimated_cost_per_hour": cost,
                "estimated_cost_per_100k_run": cost * 0.15,  # ~10 min per run
            }
        return result

    def estimate_run(self, config: ParallelRunConfig) -> Dict[str, Any]:
        """Estimate time and cost for a parallel run configuration."""
        model_spec = AVAILABLE_MODELS.get(config.model_id, AVAILABLE_MODELS["qwen2.5-72b"])
        gpu_info = GPU_PRICING.get(model_spec["gpu_type"], GPU_PRICING["A100_80GB"])
        num_gpus = model_spec["recommended_gpus"]
        cost_per_hour = gpu_info["price_per_hr"] * num_gpus

        # Parse throughput estimate
        throughput_str = model_spec.get("throughput_est", "300 req/sec")
        try:
            throughput = int(throughput_str.split("-")[0])
        except (ValueError, IndexError):
            throughput = 300

        total_calls = config.estimate_total_calls()
        time_minutes = config.estimate_time_minutes(throughput)
        cost = (time_minutes / 60) * cost_per_hour

        return {
            "model": model_spec["hf_name"],
            "gpu_type": model_spec["gpu_type"],
            "num_gpus": num_gpus,
            "total_llm_calls": total_calls,
            "estimated_time_minutes": round(time_minutes, 1),
            "estimated_cost_usd": round(cost, 2),
            "cost_per_hour": cost_per_hour,
            "throughput_per_sec": throughput,
            "num_runs": config.num_runs,
            "agents_per_run": config.agents_per_run,
            "active_per_round": int(config.agents_per_run * config.active_ratio),
            "rounds_per_run": config.rounds_per_run,
        }

    def provision_instance(
        self,
        model_id: str = "qwen2.5-72b",
        num_gpus: Optional[int] = None,
        provider: str = "vastai",
    ) -> GPUInstance:
        """Provision a GPU instance and deploy vLLM.

        For Vast.ai: Uses their API to find cheapest available GPUs,
        deploy our Docker image, and return the endpoint URL.
        """
        model_spec = AVAILABLE_MODELS.get(model_id, AVAILABLE_MODELS["qwen2.5-72b"])
        gpus = num_gpus or model_spec["recommended_gpus"]

        instance = GPUInstance(
            instance_id=f"vllm_{int(time.time())}",
            provider=provider,
            gpu_type=model_spec["gpu_type"],
            num_gpus=gpus,
            model_name=model_spec["hf_name"],
            status="provisioning",
            created_at=datetime.now().isoformat(),
            cost_per_hour=GPU_PRICING.get(model_spec["gpu_type"], {}).get("price_per_hr", 1.5) * gpus,
        )

        if provider == "vastai" and self.vastai_api_key:
            instance = self._provision_vastai(instance, model_spec)
        elif provider == "local":
            instance.endpoint_url = os.environ.get('VLLM_ENDPOINT', 'http://localhost:8000/v1')
            instance.status = "ready"
        else:
            # Manual mode — user provides endpoint after deploying themselves
            instance.status = "awaiting_endpoint"
            logger.info(f"Instance {instance.instance_id} created in manual mode. "
                        f"Deploy vLLM with model {model_spec['hf_name']} on {gpus}× {model_spec['gpu_type']}, "
                        f"then call set_endpoint().")

        self.instances[instance.instance_id] = instance
        return instance

    def set_endpoint(self, instance_id: str, endpoint_url: str):
        """Manually set the vLLM endpoint URL after user deploys."""
        if instance_id in self.instances:
            self.instances[instance_id].endpoint_url = endpoint_url
            self.instances[instance_id].status = "ready"
            logger.info(f"Endpoint set for {instance_id}: {endpoint_url}")

    def get_client_for_instance(self, instance_id: str):
        """Get an OpenAI-compatible client pointing at a vLLM instance."""
        instance = self.instances.get(instance_id)
        if not instance or not instance.endpoint_url:
            raise ValueError(f"Instance {instance_id} not ready")

        from openai import OpenAI
        return OpenAI(
            api_key="not-needed",  # vLLM doesn't require auth
            base_url=instance.endpoint_url,
        )

    def terminate_instance(self, instance_id: str):
        """Terminate a GPU instance."""
        instance = self.instances.get(instance_id)
        if not instance:
            return

        if instance.provider == "vastai" and self.vastai_api_key:
            self._terminate_vastai(instance)

        instance.status = "terminated"
        elapsed_hrs = (time.time() - datetime.fromisoformat(instance.created_at).timestamp()) / 3600
        instance.total_cost = elapsed_hrs * instance.cost_per_hour
        logger.info(f"Terminated {instance_id}. Total cost: ${instance.total_cost:.2f}")

    def get_status(self) -> Dict[str, Any]:
        """Get status of all instances."""
        return {
            "instances": {
                iid: {
                    "provider": inst.provider,
                    "gpu_type": inst.gpu_type,
                    "num_gpus": inst.num_gpus,
                    "model": inst.model_name,
                    "endpoint": inst.endpoint_url,
                    "status": inst.status,
                    "cost_per_hour": inst.cost_per_hour,
                    "created_at": inst.created_at,
                }
                for iid, inst in self.instances.items()
            },
            "available_models": list(AVAILABLE_MODELS.keys()),
            "vastai_configured": bool(self.vastai_api_key),
        }

    def _provision_vastai(self, instance: GPUInstance, model_spec: Dict) -> GPUInstance:
        """Provision via Vast.ai API."""
        try:
            import requests

            headers = {"Authorization": f"Bearer {self.vastai_api_key}"}

            # Search for available GPU offers
            gpu_name_map = {
                "A100_80GB": "A100_SXM4",
                "A100_40GB": "A100_PCIE",
                "H100_80GB": "H100",
                "RTX_4090": "RTX_4090",
            }
            gpu_search = gpu_name_map.get(instance.gpu_type, "A100")

            search_resp = requests.get(
                "https://cloud.vast.ai/api/v0/bundles/",
                headers=headers,
                params={
                    "q": json.dumps({
                        "gpu_name": {"eq": gpu_search},
                        "num_gpus": {"gte": instance.num_gpus},
                        "rentable": {"eq": True},
                        "order": [["dph_total", "asc"]],
                        "type": "on-demand",
                    })
                },
                timeout=15,
            )

            if search_resp.status_code != 200:
                logger.error(f"Vast.ai search failed: {search_resp.status_code}")
                instance.status = "failed"
                return instance

            offers = search_resp.json().get("offers", [])
            if not offers:
                logger.error("No Vast.ai GPU offers available")
                instance.status = "failed"
                return instance

            # Pick cheapest offer
            offer = offers[0]
            offer_id = offer["id"]
            instance.cost_per_hour = offer.get("dph_total", instance.cost_per_hour)

            # Create instance with our Docker image
            create_resp = requests.put(
                f"https://cloud.vast.ai/api/v0/asks/{offer_id}/",
                headers=headers,
                json={
                    "client_id": "me",
                    "image": "vllm/vllm-openai:latest",
                    "env": {
                        "MODEL_NAME": model_spec["hf_name"],
                        "TENSOR_PARALLEL_SIZE": str(instance.num_gpus),
                        "MAX_MODEL_LEN": "4096",
                        "GPU_MEMORY_UTILIZATION": "0.92",
                    },
                    "disk": 100,  # GB
                    "onstart": (
                        f"python -m vllm.entrypoints.openai.api_server "
                        f"--model {model_spec['hf_name']} "
                        f"--tensor-parallel-size {instance.num_gpus} "
                        f"--max-model-len 4096 "
                        f"--gpu-memory-utilization 0.92 "
                        f"--port 8000 "
                        f"--max-num-seqs 256 "
                        f"--trust-remote-code "
                        f"--enable-prefix-caching"
                    ),
                },
                timeout=15,
            )

            if create_resp.status_code in (200, 201):
                result = create_resp.json()
                instance.instance_id = str(result.get("new_contract", instance.instance_id))
                instance.status = "loading_model"
                logger.info(f"Vast.ai instance created: {instance.instance_id}")

                # Get the instance IP (may need polling)
                instance.endpoint_url = f"http://{result.get('public_ipaddr', 'pending')}:8000/v1"
            else:
                logger.error(f"Vast.ai create failed: {create_resp.status_code}")
                instance.status = "failed"

        except Exception as e:
            logger.error(f"Vast.ai provisioning error: {e}")
            instance.status = "failed"

        return instance

    def _terminate_vastai(self, instance: GPUInstance):
        """Terminate Vast.ai instance."""
        try:
            import requests
            requests.delete(
                f"https://cloud.vast.ai/api/v0/instances/{instance.instance_id}/",
                headers={"Authorization": f"Bearer {self.vastai_api_key}"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Vast.ai termination error: {e}")
