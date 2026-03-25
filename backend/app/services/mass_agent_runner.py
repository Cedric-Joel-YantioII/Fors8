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


# ---------------------------------------------------------------------------
# Role category mappings for role-specific prompt generation
# ---------------------------------------------------------------------------
_MILITARY_ROLES = frozenset({
    "military_general", "military_officer", "military_analyst",
    "intelligence_officer", "four_star_general", "colonel", "field_commander",
    "naval_commander", "air_force_commander", "missile_commander",
    "special_forces_officer", "foot_soldier", "navy_seal", "irgc_commander",
    "quds_force_officer", "idf_officer", "conscript_soldier", "drone_operator",
    "military_chaplain", "cia_analyst", "cia_officer", "pentagon_official",
    "nsa_analyst", "mossad_officer", "shin_bet_agent", "aman_analyst",
    "irgc_intelligence", "vevak_officer", "gip_officer", "fsb_analyst",
    "mss_officer",
})
_POLITICAL_ROLES = frozenset({
    "head_of_state", "cabinet_minister", "legislator", "diplomat",
    "political_advisor", "president", "prime_minister", "supreme_leader",
    "king", "crown_prince", "emir", "defense_minister", "foreign_minister",
    "finance_minister", "energy_minister", "senator", "congressman",
    "parliament_member", "ambassador", "un_envoy",
})
_ECONOMIC_ROLES = frozenset({
    "central_banker", "oil_trader", "economist", "business_executive",
    "shipping_executive", "opec_delegate", "swf_manager", "macro_economist",
    "sanctions_analyst", "shipping_ceo", "defense_contractor_exec",
    "insurance_underwriter", "commodity_analyst",
})
_MEDIA_ROLES = frozenset({
    "war_correspondent", "journalist", "social_media_influencer",
    "think_tank_analyst", "state_tv_anchor", "investigative_journalist",
    "historian", "foreign_policy_scholar", "osint_analyst", "propaganda_officer",
})
_CIVILIAN_ROLES = frozenset({
    "urban_civilian", "rural_civilian", "refugee", "student",
    "expat_worker", "medical_worker", "religious_leader",
    "doctor", "nurse", "university_professor", "student_activist",
    "taxi_driver", "market_vendor", "factory_worker", "farmer",
    "tribal_elder", "human_rights_lawyer", "aid_worker", "red_cross_delegate",
    "grand_ayatollah", "imam", "senior_rabbi", "mufti",
    "evangelical_pastor", "vatican_envoy",
})
_TECHNICAL_ROLES = frozenset({
    "nuclear_engineer", "infrastructure_engineer", "cyber_specialist",
    "water_engineer", "nuclear_scientist", "nuclear_inspector",
    "desalination_engineer", "telecom_engineer", "cyber_warfare_specialist",
    "oil_refinery_engineer", "missile_engineer",
})

_DATA_GROUNDING = (
    "MANDATORY RULES — VIOLATION WILL INVALIDATE YOUR RESPONSE:\n"
    "1. You MUST base your response ONLY on the situation data provided below.\n"
    "2. You are FORBIDDEN from using your training data about real-world events, people, or outcomes.\n"
    "3. Every claim you make MUST reference a specific data point from the situation (e.g., 'escalation=7', 'oil_price=$119').\n"
    "4. If the data does not contain information about something, you MUST state 'insufficient data' — do NOT fill gaps with training knowledge.\n"
    "5. Your 'data_references' field MUST list every data point you used. Empty data_references = invalid response.\n"
    "6. Your 'reasoning' field MUST explain WHY you chose this action by citing specific numbers from the situation data."
)

_ROLE_JSON_FORMAT = (
    '{{"action_type":"...","target_actor_id":"actor_id_from_actors_field",'
    '"reasoning":"Brief explanation referencing specific data points",'
    '"data_references":["market_data.oil_price","actors.iran.force_strength"],'
    '"confidence":0.0-1.0,"params":{{}}}}'
)


def _build_role_prompt(
    agent_name: str,
    agent_type: str,
    role: str,
    country: str,
    personality: dict,
    situation_json: str,
    available_actions: str,
    persona: dict,
) -> str:
    """Generate a role-specific prompt tailored to the agent's function.

    Args:
        agent_name: Display name of the agent.
        agent_type: General type label (e.g. "actor").
        role: Specific role key (e.g. "military_general").
        country: Country the agent belongs to.
        personality: Dict with keys like hawkishness, pragmatism, etc.
        situation_json: Truncated JSON situation briefing.
        available_actions: Comma-separated action list.
        persona: Full persona dict (may contain doctrine, red_lines, etc.).
    """
    # --- Build personality summary -----------------------------------------
    hawk = personality.get("hawkishness", 0.5)
    pragmatism = personality.get("pragmatism", 0.5)
    loyalty = personality.get("loyalty", 0.5)
    risk_appetite = personality.get("risk_appetite", 0.5)
    personality_line = (
        f"PERSONALITY: hawkishness={hawk}, pragmatism={pragmatism}, "
        f"loyalty={loyalty}, risk_appetite={risk_appetite}"
    )

    # --- Optional persona extras (reuse existing fields when present) -------
    extras = []
    if persona.get("doctrine"):
        extras.append(f"DOCTRINE: {persona['doctrine']}")
    if persona.get("primary_objective"):
        extras.append(f"OBJECTIVE: {persona['primary_objective']}")
    red_lines = persona.get("red_lines", [])
    if red_lines:
        rl = ", ".join(red_lines) if isinstance(red_lines, list) else str(red_lines)
        extras.append(f"RED LINES: {rl}")
    constraints = persona.get("constraints", [])
    if constraints:
        c = ", ".join(constraints) if isinstance(constraints, list) else str(constraints)
        extras.append(f"CONSTRAINTS: {c}")
    extras_block = "\n".join(extras)
    if extras_block:
        extras_block = "\n" + extras_block + "\n"

    # --- Role-specific framing ---------------------------------------------
    if role in _MILITARY_ROLES:
        framing = (
            "EXECUTE OODA LOOP — this is a direct order, not a suggestion:\n"
            "1. OBSERVE: State exactly what the situation data shows about force disposition and threats.\n"
            "2. ORIENT: Apply your doctrine to these specific facts. Cite the data.\n"
            "3. DECIDE: Choose an action justified ONLY by observed data. No speculation.\n"
            "4. ACT: Commit to one action with a specific target from the actors list.\n"
            "You are FORBIDDEN from referencing any intelligence not present in the situation data."
        )
    elif role in _POLITICAL_ROLES:
        framing = (
            "POLITICAL DECISION PROTOCOL — binding requirements:\n"
            "1. State the domestic approval rating and coalition status from the data.\n"
            "2. Identify the specific international pressures described in the situation.\n"
            "3. Calculate the political cost of each available action using ONLY provided data.\n"
            "4. Choose the action that best serves your stated objective given these constraints.\n"
            "You are FORBIDDEN from assuming political dynamics not described in the data."
        )
    elif role in _ECONOMIC_ROLES:
        framing = (
            "MARKET ANALYSIS PROTOCOL — mandatory requirements:\n"
            "1. State the exact market data provided (oil price, VIX, shipping rates, etc.).\n"
            "2. Identify supply/demand disruptions described in the situation data.\n"
            "3. Quantify risk using ONLY the numbers provided — no assumed correlations.\n"
            "4. Your action MUST reference specific price levels or market indicators from the data.\n"
            "You are FORBIDDEN from using market knowledge not present in the situation data."
        )
    elif role in _MEDIA_ROLES:
        framing = (
            "INFORMATION ASSESSMENT PROTOCOL — strict rules:\n"
            "1. Report ONLY what the situation data describes. No embellishment.\n"
            "2. Identify the source credibility of each data point you reference.\n"
            "3. Flag any claims in the data that lack corroboration.\n"
            "4. Your output MUST distinguish between confirmed facts and unverified reports.\n"
            "You are FORBIDDEN from adding narrative color based on training knowledge."
        )
    elif role in _CIVILIAN_ROLES:
        framing = (
            "PERSONAL SITUATION ASSESSMENT — respond from lived experience:\n"
            "1. Describe how the specific conditions in the data affect your daily life.\n"
            "2. React to the exact prices, shortages, and threats described in the situation.\n"
            "3. Your emotional response MUST be proportional to the data — not dramatized.\n"
            "4. Reference specific infrastructure status, casualty figures, or prices from the data.\n"
            "You are FORBIDDEN from inventing conditions not described in the situation data."
        )
    elif role in _TECHNICAL_ROLES:
        framing = (
            "TECHNICAL ASSESSMENT PROTOCOL — engineering standards apply:\n"
            "1. State the specific infrastructure status described in the data.\n"
            "2. Calculate cascading failure risks using ONLY provided capacity/damage figures.\n"
            "3. Your timeline estimates MUST be based on the engineering data provided.\n"
            "4. Distinguish between physical constraints (immutable) and political promises (unreliable).\n"
            "You are FORBIDDEN from assuming technical capabilities not described in the data."
        )
    else:
        framing = (
            "ASSESSMENT PROTOCOL:\n"
            "1. State what the situation data shows about your area of concern.\n"
            "2. Choose an action justified ONLY by the provided data.\n"
            "3. Your reasoning MUST cite specific data points.\n"
            "You are FORBIDDEN from using knowledge not present in the situation data."
        )

    return f"""You are {agent_name}, a {role} from {country} ({agent_type}).
{personality_line}
{extras_block}
{_DATA_GROUNDING}

{framing}

Use actor IDs from the "actors" field as target_actor_id. Output ONLY valid JSON.

Format: {{"situation_assessment":"1 sentence","actions":[{_ROLE_JSON_FORMAT}]}}

Actions: {available_actions}

Situation:
{situation_json}

Given your role and the current situation, what action does {agent_name} take? JSON only:"""


def _build_agent_prompt(agent_name: str, agent_type: str, situation_json: str, available_actions: str, persona: dict = None) -> str:
    """Build the decision prompt for a single agent.

    When the persona contains role-specific fields (role, country, hawkishness)
    the new role-aware prompt is used. Otherwise falls back to the original
    generic 17-actor prompt for backward compatibility.
    """

    # --- Check if we have role/personality data for the new prompt path -----
    if persona and all(k in persona for k in ("role", "country", "hawkishness")):
        personality = {
            "hawkishness": persona.get("hawkishness", 0.5),
            "pragmatism": persona.get("pragmatism", 0.5),
            "loyalty": persona.get("loyalty", 0.5),
            "risk_appetite": persona.get("risk_appetite", 0.5),
        }
        return _build_role_prompt(
            agent_name=agent_name,
            agent_type=agent_type,
            role=persona["role"],
            country=persona["country"],
            personality=personality,
            situation_json=situation_json,
            available_actions=available_actions,
            persona=persona,
        )

    # --- Legacy generic prompt (17-actor mode) -----------------------------
    persona_block = ""
    if persona:
        red_lines = ", ".join(persona.get("red_lines", [])) if isinstance(persona.get("red_lines"), list) else str(persona.get("red_lines", ""))
        constraints = ", ".join(persona.get("constraints", [])) if isinstance(persona.get("constraints"), list) else str(persona.get("constraints", ""))
        allies = ", ".join(persona.get("alliance_network", [])) if isinstance(persona.get("alliance_network"), list) else str(persona.get("alliance_network", ""))
        enemies = ", ".join(persona.get("adversaries", [])) if isinstance(persona.get("adversaries"), list) else str(persona.get("adversaries", ""))
        weapons = ", ".join(persona.get("key_weapons", [])) if isinstance(persona.get("key_weapons"), list) else str(persona.get("key_weapons", ""))

        # Build optional vulnerability and termination condition lines
        vuln_block = ""
        vulnerabilities = persona.get("vulnerabilities", {})
        if vulnerabilities:
            vuln_items = [f"{k}: {v}" for k, v in vulnerabilities.items() if v]
            vuln_block = f"\nVULNERABILITIES: {'; '.join(vuln_items)}"

        termination_block = ""
        termination = persona.get("termination_conditions", {})
        if termination:
            term_items = [f"{k}: {v}" for k, v in termination.items() if v]
            termination_block = f"\nWAR TERMINATION CONDITIONS: {'; '.join(term_items)}"

        persona_block = f"""
DOCTRINE: {persona.get('doctrine', '')}
TEMPERAMENT: {persona.get('temperament', '')}
RED LINES: {red_lines}
BELIEF SYSTEM: {persona.get('belief_system', '')}
HISTORICAL PATTERNS: {persona.get('historical_patterns', '')}
OBJECTIVE: {persona.get('primary_objective', '')}
CONSTRAINTS: {constraints}
ALLIES: {allies}
ENEMIES: {enemies}
KEY WEAPONS: {weapons}
NUCLEAR: {persona.get('nuclear_status', 'none')}
RISK TOLERANCE: {persona.get('risk_tolerance', 0.5)} ESCALATION THRESHOLD: {persona.get('escalation_threshold', 0.5)} MARTYRDOM: {persona.get('martyrdom_willingness', 0.0)}{vuln_block}{termination_block}

"""

    return f"""You are {agent_name} ({agent_type}).
{persona_block}
{_DATA_GROUNDING}

You are in an active military conflict. Choose actions consistent with your doctrine, temperament, and red lines. Use actor IDs from "actors" field as target_actor_id. Output ONLY valid JSON.

Format: {{"situation_assessment":"1 sentence","actions":[{{"action_type":"name","target_actor_id":"actor_id_from_actors_field","reasoning":"1 sentence"}}]}}

Actions: {available_actions}

Situation:
{situation_json}

Given the active conflict, what decisive action does {agent_name} take? JSON only:"""


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
                persona=agent.get("persona"),
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
                persona=agent.get("persona"),
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
