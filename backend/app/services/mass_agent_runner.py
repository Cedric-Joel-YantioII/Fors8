"""
Mass Agent Runner.

Sends 10K-100K+ agent decisions per round to a vLLM endpoint using
async HTTP with high concurrency. This is the bridge between the
geopolitical simulation engine and self-hosted GPU inference.

Architecture:
- Uses asyncio + aiohttp for concurrent requests
- Batches agents by type/tier for efficient prompt reuse (vLLM prefix caching)
- Respects vLLM's max_num_seqs concurrency limit
- Reports progress per round for real-time UI updates

Performance targets:
- 10K agents/round on 2×A100: ~30 seconds
- 100K agents/round on 4×A100: ~5 minutes
"""

import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger('fors8.mass_runner')


@dataclass
class AgentDecision:
    """Result of one agent's LLM decision."""
    agent_id: str
    actions: List[Dict[str, Any]]
    situation_assessment: str = ""
    raw_response: str = ""
    success: bool = True
    error: str = ""


def _clean_response(text: str) -> str:
    """Clean LLM response for JSON parsing."""
    if not text:
        return ""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text).strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def _build_agent_prompt(agent_name: str, agent_type: str, situation_json: str, available_actions: str) -> str:
    """Build the decision prompt for a single agent. Kept short for throughput."""
    return f"""You simulate {agent_name} ({agent_type}) in a war. Output ONLY valid JSON.

Format: {{"situation_assessment":"1 sentence","actions":[{{"action_type":"name","target_actor_id":"id_or_null","reasoning":"1 sentence"}}]}}

Actions: {available_actions}

Situation:
{situation_json}

What does {agent_name} do? JSON only:"""


class MassAgentRunner:
    """Runs thousands of agent decisions per round against a vLLM endpoint."""

    def __init__(
        self,
        endpoint_url: str,
        model_name: str = "Qwen/Qwen2.5-72B-Instruct",
        max_concurrent: int = 200,
        timeout_per_request: int = 30,
    ):
        """
        Args:
            endpoint_url: vLLM OpenAI-compatible endpoint (e.g., http://gpu-ip:8000/v1)
            model_name: Model name as registered in vLLM
            max_concurrent: Max simultaneous requests (match vLLM --max-num-seqs)
            timeout_per_request: Timeout per individual request in seconds
        """
        self.endpoint_url = endpoint_url.rstrip('/')
        self.model_name = model_name
        self.max_concurrent = max_concurrent
        self.timeout = timeout_per_request
        # Support both vLLM (/v1/chat/completions) and Ollama (/v1/chat/completions or /api/chat)
        if '/v1' in self.endpoint_url:
            self._completions_url = f"{self.endpoint_url}/chat/completions"
        else:
            self._completions_url = f"{self.endpoint_url}/v1/chat/completions"

    async def run_round(
        self,
        agents: List[Dict[str, Any]],
        situation_json: str,
        available_actions: str,
        temperature: float = 0.5,
        max_tokens: int = 300,
        progress_callback: Optional[Callable] = None,
    ) -> List[AgentDecision]:
        """Run one round of decisions for all agents concurrently.

        Args:
            agents: List of agent dicts with 'agent_id', 'agent_name', 'agent_type'
            situation_json: Shared situation briefing (same for all agents in this batch)
            available_actions: Comma-separated action list
            temperature: LLM temperature
            max_tokens: Max response tokens per agent
            progress_callback: Optional fn(completed, total) for progress

        Returns:
            List of AgentDecision results
        """
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed. Install with: pip install aiohttp")
            # Fallback to synchronous requests
            return self._run_round_sync(agents, situation_json, available_actions, temperature, max_tokens, progress_callback)

        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: List[AgentDecision] = []
        completed = 0
        total = len(agents)

        async def process_agent(session: aiohttp.ClientSession, agent: Dict) -> AgentDecision:
            nonlocal completed

            prompt = _build_agent_prompt(
                agent["agent_name"],
                agent.get("agent_type", "actor"),
                situation_json[:2000],  # Truncate to keep prompts fast
                available_actions,
            )

            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            async with semaphore:
                try:
                    async with session.post(
                        self._completions_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            return AgentDecision(
                                agent_id=agent["agent_id"],
                                actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": "API error"}],
                                success=False,
                                error=f"HTTP {resp.status}: {error_text[:100]}",
                            )

                        data = await resp.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        content = _clean_response(content)

                        try:
                            parsed = json.loads(content)
                            decision = AgentDecision(
                                agent_id=agent["agent_id"],
                                actions=parsed.get("actions", []),
                                situation_assessment=parsed.get("situation_assessment", ""),
                                raw_response=content,
                            )
                        except json.JSONDecodeError:
                            decision = AgentDecision(
                                agent_id=agent["agent_id"],
                                actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": "JSON parse fallback"}],
                                raw_response=content,
                            )

                except asyncio.TimeoutError:
                    decision = AgentDecision(
                        agent_id=agent["agent_id"],
                        actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": "timeout"}],
                        success=False,
                        error="Request timed out",
                    )
                except Exception as e:
                    decision = AgentDecision(
                        agent_id=agent["agent_id"],
                        actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": str(e)[:50]}],
                        success=False,
                        error=str(e),
                    )

                completed += 1
                if progress_callback and completed % 100 == 0:
                    progress_callback(completed, total)

                return decision

        # Run agents in batches to limit memory usage with 100K+ agents.
        # Each batch is fully concurrent (up to semaphore limit), but we don't
        # schedule all 100K coroutines into memory at once.
        BATCH_SIZE = 5000
        connector = aiohttp.TCPConnector(limit=self.max_concurrent, force_close=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for batch_start in range(0, len(agents), BATCH_SIZE):
                batch = agents[batch_start:batch_start + BATCH_SIZE]
                tasks = [process_agent(session, agent) for agent in batch]
                batch_results = await asyncio.gather(*tasks)
                results.extend(batch_results)

        if progress_callback:
            progress_callback(total, total)

        successes = sum(1 for r in results if r.success)
        logger.info(f"Round complete: {successes}/{total} successful ({total - successes} fallbacks)")

        return results

    def _run_round_sync(
        self,
        agents: List[Dict],
        situation_json: str,
        available_actions: str,
        temperature: float,
        max_tokens: int,
        progress_callback: Optional[Callable],
    ) -> List[AgentDecision]:
        """Synchronous fallback when aiohttp is not available."""
        import requests

        results = []
        total = len(agents)

        for i, agent in enumerate(agents):
            prompt = _build_agent_prompt(
                agent["agent_name"],
                agent.get("agent_type", "actor"),
                situation_json[:2000],
                available_actions,
            )

            try:
                resp = requests.post(
                    self._completions_url,
                    json={
                        "model": self.model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=self.timeout,
                )

                if resp.status_code == 200:
                    content = _clean_response(
                        resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    )
                    try:
                        parsed = json.loads(content)
                        results.append(AgentDecision(
                            agent_id=agent["agent_id"],
                            actions=parsed.get("actions", []),
                            situation_assessment=parsed.get("situation_assessment", ""),
                        ))
                    except json.JSONDecodeError:
                        results.append(AgentDecision(
                            agent_id=agent["agent_id"],
                            actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": "parse fallback"}],
                        ))
                else:
                    results.append(AgentDecision(
                        agent_id=agent["agent_id"],
                        actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": "API error"}],
                        success=False,
                    ))

            except Exception as e:
                results.append(AgentDecision(
                    agent_id=agent["agent_id"],
                    actions=[{"action_type": "hold_position", "target_actor_id": None, "reasoning": str(e)[:50]}],
                    success=False,
                ))

            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, total)

        return results

    def run_round_sync_wrapper(
        self,
        agents: List[Dict[str, Any]],
        situation_json: str,
        available_actions: str,
        temperature: float = 0.5,
        max_tokens: int = 300,
        progress_callback: Optional[Callable] = None,
    ) -> List[AgentDecision]:
        """Synchronous wrapper for run_round — call this from non-async code."""
        try:
            loop = asyncio.get_running_loop()
            # Already in async context — use sync fallback since asyncio.run()
            # would raise "cannot be called from a running event loop"
            return self._run_round_sync(agents, situation_json, available_actions, temperature, max_tokens, progress_callback)
        except RuntimeError:
            # No running loop — safe to use asyncio.run()
            pass

        return asyncio.run(self.run_round(
            agents, situation_json, available_actions,
            temperature, max_tokens, progress_callback,
        ))

    def health_check(self) -> Dict[str, Any]:
        """Check if the endpoint is responding. Supports both vLLM and Ollama."""
        import requests
        base = self.endpoint_url
        if base.endswith('/v1'):
            base = base[:-3]
        base = base.rstrip('/')

        # Try Ollama format first (/api/tags)
        try:
            resp = requests.get(f"{base}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return {
                    "healthy": True,
                    "models": [m.get("name", "") for m in models],
                    "endpoint": self.endpoint_url,
                    "type": "ollama",
                }
        except Exception:
            pass

        # Try vLLM format (/v1/models)
        try:
            resp = requests.get(f"{self.endpoint_url}/models", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                return {
                    "healthy": True,
                    "models": [m.get("id", "") for m in models],
                    "endpoint": self.endpoint_url,
                    "type": "vllm",
                }
        except Exception:
            pass

        return {"healthy": False, "error": "No response on Ollama or vLLM endpoints"}
