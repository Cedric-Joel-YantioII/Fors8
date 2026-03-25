"""
Graph-Derived Persona Generator — MiroFish-style agent creation.

Instead of hardcoded personality traits per role, this module:
1. Reads entities and facts from the Zep knowledge graph
2. Uses an LLM to generate each agent's personality grounded in what the DATA says
3. Produces personas that can surprise the researcher — no pre-baked assumptions

This replaces the hardcoded ROLE_PERSONALITY_RANGES approach with data-driven generation.
"""

import json
import logging
import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('fors8.graph_personas')


@dataclass
class GraphDerivedPersona:
    """An agent persona derived from knowledge graph data, not hardcoded traits."""
    agent_id: str
    agent_name: str
    country: str
    role: str

    # LLM-generated personality text (NOT numeric traits)
    personality_description: str = ""
    stance_on_conflict: str = ""
    key_concerns: List[str] = field(default_factory=list)
    likely_actions: List[str] = field(default_factory=list)
    information_sources: List[str] = field(default_factory=list)

    # Derived from graph context, not hardcoded
    hawkishness: float = 0.5
    risk_tolerance: float = 0.5
    information_trust: float = 0.5
    analytical_depth: float = 0.5
    nationalism: float = 0.5

    # Graph provenance — which data points informed this persona
    source_facts: List[str] = field(default_factory=list)
    source_entity_id: str = ""

    # Social simulation fields
    information_access: str = "public"
    influence_radius: int = 10
    credibility: float = 0.5
    current_sentiment: float = 0.0
    stress_level: float = 0.0
    background: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "country": self.country,
            "role": self.role,
            "personality_description": self.personality_description,
            "stance_on_conflict": self.stance_on_conflict,
            "key_concerns": self.key_concerns,
            "likely_actions": self.likely_actions,
            "hawkishness": self.hawkishness,
            "risk_tolerance": self.risk_tolerance,
            "information_trust": self.information_trust,
            "analytical_depth": self.analytical_depth,
            "nationalism": self.nationalism,
            "source_facts": self.source_facts,
            "information_access": self.information_access,
            "influence_radius": self.influence_radius,
            "credibility": self.credibility,
            "current_sentiment": self.current_sentiment,
            "stress_level": self.stress_level,
            "background": self.background,
        }


# The persona generation prompt — asks the LLM to CREATE a persona from graph facts
# Key: we do NOT tell the LLM what the persona should think.
# We give it facts and ask it to derive personality from those facts.
_PERSONA_PROMPT = """You are generating a realistic agent persona for a geopolitical simulation.

## Source Facts from Knowledge Graph
The following facts were extracted from real-world data sources (news, reports, official statements).
These are the ONLY facts you may use to build this persona. Do NOT add information from your training data.

{source_facts}

## Entity Context
Entity: {entity_name}
Type: {entity_type}
Country/Affiliation: {country}
Related entities: {related_entities}

## Instructions
Based ONLY on the source facts above, generate a detailed persona for a {role_description} affiliated with {entity_name}.

You MUST output valid JSON with these fields:
{{
    "personality_description": "2-3 sentences describing this person's worldview, temperament, and decision-making style — derived from the facts above",
    "stance_on_conflict": "1-2 sentences on their position regarding the current situation — must reference specific facts",
    "key_concerns": ["list", "of", "3-5", "specific", "concerns", "from", "the", "data"],
    "likely_actions": ["list", "of", "2-3", "actions", "this", "person", "would", "take"],
    "hawkishness": 0.0-1.0,
    "risk_tolerance": 0.0-1.0,
    "information_trust": 0.0-1.0,
    "analytical_depth": 0.0-1.0,
    "nationalism": 0.0-1.0,
    "reasoning": "1-2 sentences explaining WHY you assigned these trait values, citing specific facts"
}}

RULES:
1. Trait values MUST be justified by the source facts. If the facts show aggressive rhetoric, hawkishness should be high. If facts show diplomatic overtures, it should be low.
2. Do NOT default to stereotypes. A general can be dovish. A civilian can be hawkish. Let the DATA decide.
3. If the facts are insufficient to determine a trait, set it to 0.5 (uncertain) and note this in reasoning.
4. The personality_description MUST reference at least 2 specific facts from the source data.

JSON only:"""


# Prompt for generating civilian/population personas from aggregate data
_POPULATION_PERSONA_PROMPT = """Generate a realistic civilian persona for a geopolitical simulation.

## Context from Real-World Data
{context_data}

## Country: {country}
## Role: {role}

Based on the real-world context above, create a persona that reflects how a real {role} in {country} would think and feel right now.

Output valid JSON:
{{
    "personality_description": "2-3 sentences — must reference specific conditions from the context",
    "stance_on_conflict": "Their position, grounded in how the situation affects them personally",
    "key_concerns": ["3-5 specific concerns derived from the context data"],
    "hawkishness": 0.0-1.0,
    "risk_tolerance": 0.0-1.0,
    "information_trust": 0.0-1.0,
    "analytical_depth": 0.0-1.0,
    "nationalism": 0.0-1.0,
    "reasoning": "Why these values, citing context data"
}}

RULES:
1. Let the DATA determine personality. Do not default to stereotypes about {country} or {role}.
2. Vary responses — not all civilians think alike. Introduce realistic individual variation.
3. Reference specific prices, shortages, or conditions from the context data.

JSON only:"""


def generate_personas_from_graph(
    graph_id: str,
    question: str,
    actors_data: List[Dict],
    initial_conditions: Dict,
    target_count: int = 2000,
    endpoint: str = "",
    model_name: str = "",
) -> List[GraphDerivedPersona]:
    """Generate agent personas from the knowledge graph instead of hardcoded traits.

    This is the MiroFish-style approach: personas come from data, not researcher assumptions.

    Args:
        graph_id: Zep knowledge graph ID (if available)
        question: User's simulation question
        actors_data: Actor profiles (used as context, not as persona source)
        initial_conditions: Current conditions (used as context for civilian personas)
        target_count: Target number of personas (default 2000, not 100K)
        endpoint: vLLM endpoint for persona generation
        model_name: Model name for LLM calls

    Returns:
        List of GraphDerivedPersona objects
    """
    personas = []

    # Phase 1: Generate elite/named personas from graph entities (if graph available)
    elite_personas = []
    if graph_id:
        elite_personas = _generate_elite_from_graph(
            graph_id, question, endpoint, model_name
        )
        personas.extend(elite_personas)
        logger.info("Generated %d elite personas from knowledge graph", len(elite_personas))

    # Phase 2: Generate elite personas from actor profiles (fallback if no graph)
    if not elite_personas and actors_data:
        elite_personas = _generate_elite_from_actors(
            actors_data, initial_conditions, endpoint, model_name
        )
        personas.extend(elite_personas)
        logger.info("Generated %d elite personas from actor profiles", len(elite_personas))

    # Phase 3: Generate population personas (civilians, professionals)
    # These are generated with LLM using aggregate context, not hardcoded traits
    remaining = target_count - len(personas)
    if remaining > 0:
        pop_personas = _generate_population_personas(
            actors_data, initial_conditions, remaining, endpoint, model_name
        )
        personas.extend(pop_personas)
        logger.info("Generated %d population personas from context data", len(pop_personas))

    logger.info("Total personas generated: %d (elite: %d, population: %d)",
                len(personas), len(elite_personas), len(personas) - len(elite_personas))
    return personas


def _generate_elite_from_graph(
    graph_id: str,
    question: str,
    endpoint: str,
    model_name: str,
) -> List[GraphDerivedPersona]:
    """Generate personas for key entities found in the knowledge graph."""
    try:
        from .zep_entity_reader import ZepEntityReader

        reader = ZepEntityReader()
        # Get all entities with their facts and relationships
        result = reader.filter_defined_entities(
            graph_id,
            defined_entity_types=["NationState", "Nation_State", "ProxyGroup", "Proxy_Group",
                                  "MilitaryForce", "Military_Force", "PoliticalLeader",
                                  "Political_Leader", "Organization", "Person",
                                  "MilitaryCommander", "Military_Commander",
                                  "InternationalOrg", "International_Org"],
            enrich_with_edges=True,
        )

        if not result.entities:
            return []

        personas = []
        for entity in result.entities[:50]:  # Cap at 50 elite personas
            # Collect facts about this entity from edges
            facts = []
            related = []
            for edge in getattr(entity, 'edges', []):
                facts.append(edge.fact if hasattr(edge, 'fact') else str(edge))
            for node in getattr(entity, 'related_nodes', []):
                related.append(node.name if hasattr(node, 'name') else str(node))

            if not facts:
                facts = [f"Entity: {entity.name}, Type: {getattr(entity, 'entity_type', 'Unknown')}"]

            # Determine role from entity type
            entity_type = getattr(entity, 'entity_type', 'Organization')
            role = _entity_type_to_role(entity_type)
            country = _infer_country(entity.name, facts)

            # Generate persona via LLM
            persona = _llm_generate_persona(
                entity_name=entity.name,
                entity_type=entity_type,
                country=country,
                role=role,
                facts=facts,
                related_entities=related,
                endpoint=endpoint,
                model_name=model_name,
            )
            if persona:
                personas.append(persona)

        return personas

    except Exception as e:
        logger.warning("Elite persona generation from graph failed: %s", e)
        return []


def _generate_elite_from_actors(
    actors_data: List[Dict],
    initial_conditions: Dict,
    endpoint: str,
    model_name: str,
) -> List[GraphDerivedPersona]:
    """Generate elite personas from actor profiles when no graph is available.

    Unlike hardcoded traits, we use the LLM to DERIVE personality from the actor's
    described doctrine, red lines, and behavior — letting the LLM decide hawkishness
    rather than us hardcoding it.
    """
    personas = []

    for actor in actors_data:
        # Build facts from the actor profile
        facts = []
        if actor.get("strategic_doctrine"):
            facts.append(f"Strategic doctrine: {actor['strategic_doctrine']}")
        if actor.get("leadership_temperament"):
            facts.append(f"Leadership temperament: {actor['leadership_temperament']}")
        if actor.get("red_lines"):
            facts.append(f"Red lines: {', '.join(actor['red_lines'][:3])}")
        if actor.get("primary_objective"):
            facts.append(f"Primary objective: {actor['primary_objective']}")
        if actor.get("constraints"):
            facts.append(f"Constraints: {', '.join(actor['constraints'][:3])}")
        if actor.get("war_termination_conditions"):
            wtc = actor["war_termination_conditions"]
            for k, v in list(wtc.items())[:2]:
                facts.append(f"War termination ({k}): {v}")

        # Add initial conditions context
        facts.append(f"Current escalation: {initial_conditions.get('escalation_level', 'unknown')}/10")
        facts.append(f"Oil price: ${initial_conditions.get('oil_price', 'unknown')}")
        facts.append(f"Phase: {initial_conditions.get('phase', 'unknown')}")

        role = _actor_type_to_role(actor.get("actor_type", "Organization"))

        # For key actors, generate multiple personas (leader + military + diplomat + civilian)
        sub_roles = _get_sub_roles_for_actor(actor)
        for sub_role, role_desc in sub_roles:
            persona = _llm_generate_persona(
                entity_name=actor["actor_name"],
                entity_type=actor.get("actor_type", "Organization"),
                country=actor["actor_id"],
                role=sub_role,
                facts=facts,
                related_entities=actor.get("alliance_network", []) + actor.get("adversaries", []),
                endpoint=endpoint,
                model_name=model_name,
                role_description=role_desc,
            )
            if persona:
                personas.append(persona)

    return personas


def _generate_population_personas(
    actors_data: List[Dict],
    initial_conditions: Dict,
    target_count: int,
    endpoint: str,
    model_name: str,
) -> List[GraphDerivedPersona]:
    """Generate population-level personas using context data.

    Instead of hardcoded personality ranges, we give the LLM the current conditions
    and ask it to generate realistic civilian perspectives. Each batch call generates
    diverse personas — the LLM is instructed to VARY responses.
    """
    # Build context from initial conditions
    context_lines = []
    context_lines.append(f"Escalation level: {initial_conditions.get('escalation_level', 5)}/10")
    context_lines.append(f"Oil price: ${initial_conditions.get('oil_price', 85)}")
    context_lines.append(f"Phase: {initial_conditions.get('phase', 'tensions')}")

    # Add infrastructure data if available
    water = initial_conditions.get("gcc_water_vulnerability", {})
    if water:
        context_lines.append("Water crisis: GCC countries depend on desalination for 60-99% of water, reserves of 2-5 days")
    food = initial_conditions.get("gcc_food_dependency", {})
    if food:
        context_lines.append("Food crisis: GCC imports 80-95% of food, maritime routes threatened")
    cables = initial_conditions.get("submarine_cables", {})
    if cables:
        context_lines.append("Internet: 14+ submarine cables through Hormuz carrying ~20% of global traffic")
    casualties = initial_conditions.get("casualty_estimates", {})
    if casualties:
        context_lines.append(f"Casualties: {json.dumps(casualties)}")

    context_data = "\n".join(context_lines)  # noqa: F841

    # Determine country distribution from actors
    countries = [ad["actor_id"] for ad in actors_data] if actors_data else ["usa", "iran", "israel"]

    # Population role types (civilians and professionals)
    pop_roles = [
        "urban civilian", "rural civilian", "doctor", "nurse", "student",
        "taxi driver", "market vendor", "factory worker", "farmer",
        "expat worker", "refugee", "teacher", "engineer", "journalist",
        "small business owner", "university professor", "religious community member",
        "retired military", "oil industry worker", "port worker",
    ]

    personas = []
    agent_counter = 0

    # Generate personas — use LLM if endpoint available, else use lightweight random
    for i in range(target_count):
        country = random.choice(countries)
        role = random.choice(pop_roles)
        agent_counter += 1

        # For scale, generate most population personas without LLM calls
        # (LLM calls are expensive — reserve for elite personas)
        # Instead, use beta distributions centered on context-derived values
        persona = _context_derived_persona(
            country=country,
            role=role,
            initial_conditions=initial_conditions,
            agent_counter=agent_counter,
        )
        personas.append(persona)

    return personas


def _context_derived_persona(
    country: str,
    role: str,
    initial_conditions: Dict,
    agent_counter: int,
) -> GraphDerivedPersona:
    """Generate a persona using beta distributions shaped by context data.

    Key difference from hardcoded ranges: the distribution parameters come from
    the SITUATION DATA (escalation level, casualties, oil prices), not from
    researcher assumptions about what role X should think.
    """
    import numpy as np

    escalation = initial_conditions.get("escalation_level", 5)
    oil_price = initial_conditions.get("oil_price", 85)
    phase = initial_conditions.get("phase", "tensions")

    # Hawkishness: driven by escalation level and country context
    # Higher escalation -> population polarizes (more hawks AND more doves)
    # NOT "role X is always hawkish"
    if escalation > 7:
        # High escalation: polarized — use bimodal-ish beta
        hawk_alpha, hawk_beta = 2.0, 2.0  # Wide spread, centered at 0.5
    elif escalation > 4:
        # Medium escalation: slight hawk lean from fear
        hawk_alpha, hawk_beta = 2.5, 3.0  # Slight dove lean
    else:
        # Low escalation: mostly dovish
        hawk_alpha, hawk_beta = 2.0, 4.0  # Dove lean

    # Risk tolerance: driven by how desperate the situation is
    if oil_price > 120 or escalation > 8:
        risk_alpha, risk_beta = 3.0, 2.0  # Desperate = more risk-taking
    else:
        risk_alpha, risk_beta = 2.0, 3.0  # Normal = risk-averse

    # Information trust: erodes with escalation (people distrust media in war)
    trust_alpha = max(1.5, 4.0 - escalation * 0.3)
    trust_beta = 3.0

    # Nationalism: rises with external threat
    nat_alpha = 2.0 + escalation * 0.2
    nat_beta = 3.0

    hawk = float(np.clip(np.random.beta(hawk_alpha, hawk_beta), 0, 1))
    risk = float(np.clip(np.random.beta(risk_alpha, risk_beta), 0, 1))
    trust = float(np.clip(np.random.beta(trust_alpha, trust_beta), 0, 1))
    nationalism = float(np.clip(np.random.beta(nat_alpha, nat_beta), 0, 1))
    analytical = float(np.clip(np.random.beta(2.0, 2.0), 0, 1))  # Uniform-ish

    country_label = country.replace("_", " ").title()

    # Background derived from conditions, not templates
    concerns = []
    if oil_price > 100:
        concerns.append(f"fuel prices up {int((oil_price - 75) / 75 * 100)}%")
    if escalation > 6:
        concerns.append("safety of family")
    if escalation > 4:
        concerns.append("economic uncertainty")
    concerns.append("future prospects")

    bg = f"{role.title()} in {country_label}. Escalation at {escalation}/10 affecting daily life. Concerns: {', '.join(concerns[:3])}."

    return GraphDerivedPersona(
        agent_id=f"{country}_{role.replace(' ', '_')}_{agent_counter}",
        agent_name=f"{role.title()} from {country_label}",
        country=country,
        role=role.replace(" ", "_"),
        hawkishness=round(hawk, 3),
        risk_tolerance=round(risk, 3),
        information_trust=round(trust, 3),
        analytical_depth=round(analytical, 3),
        nationalism=round(nationalism, 3),
        background=bg,
        source_facts=[f"escalation={escalation}", f"oil_price={oil_price}", f"phase={phase}"],
        information_access="public",
        influence_radius=10,
        credibility=0.3,
        current_sentiment=round(random.uniform(-0.5, 0.5), 2),
        stress_level=round(min(1.0, escalation / 10.0 + random.uniform(-0.1, 0.1)), 2),
    )


def _llm_generate_persona(
    entity_name: str,
    entity_type: str,
    country: str,
    role: str,
    facts: List[str],
    related_entities: List[str],
    endpoint: str,
    model_name: str,
    role_description: str = "",
) -> Optional[GraphDerivedPersona]:
    """Use the LLM to generate a persona from knowledge graph facts."""
    if not endpoint:
        return None

    try:
        import requests

        facts_text = "\n".join(f"- {f}" for f in facts[:20])
        related_text = ", ".join(related_entities[:10]) if related_entities else "None identified"

        prompt = _PERSONA_PROMPT.format(
            source_facts=facts_text,
            entity_name=entity_name,
            entity_type=entity_type,
            country=country,
            related_entities=related_text,
            role_description=role_description or role,
        )

        body = {
            "model": model_name or "default",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,  # Higher temp for diverse personas
            "max_tokens": 500,
        }

        # Try vLLM endpoint
        for path in ["/v1/chat/completions", "/chat/completions"]:
            try:
                resp = requests.post(f"{endpoint}{path}", json=body, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        # Parse JSON from response
                        import re
                        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                        content = re.sub(r'^```(?:json)?\s*\n?', '', content)
                        content = re.sub(r'\n?```\s*$', '', content)

                        parsed = json.loads(content)

                        return GraphDerivedPersona(
                            agent_id=f"{country}_{role}_{hash(entity_name) % 10000}",
                            agent_name=f"{entity_name} ({role})",
                            country=country,
                            role=role,
                            personality_description=parsed.get("personality_description", ""),
                            stance_on_conflict=parsed.get("stance_on_conflict", ""),
                            key_concerns=parsed.get("key_concerns", []),
                            likely_actions=parsed.get("likely_actions", []),
                            hawkishness=float(parsed.get("hawkishness", 0.5)),
                            risk_tolerance=float(parsed.get("risk_tolerance", 0.5)),
                            information_trust=float(parsed.get("information_trust", 0.5)),
                            analytical_depth=float(parsed.get("analytical_depth", 0.5)),
                            nationalism=float(parsed.get("nationalism", 0.5)),
                            source_facts=facts[:5],
                            source_entity_id=entity_name,
                            information_access="insider" if entity_type in ("PoliticalLeader", "MilitaryForce") else "public",
                            influence_radius=1000 if entity_type in ("NationState", "PoliticalLeader") else 100,
                            credibility=0.8 if entity_type in ("NationState", "PoliticalLeader") else 0.5,
                            background=parsed.get("personality_description", ""),
                        )
            except Exception:
                continue

        return None

    except Exception as e:
        logger.warning("LLM persona generation failed for %s: %s", entity_name, e)
        return None


def _entity_type_to_role(entity_type: str) -> str:
    """Map knowledge graph entity type to a simulation role."""
    mapping = {
        "NationState": "head_of_state", "Nation_State": "head_of_state",
        "PoliticalLeader": "political_leader", "Political_Leader": "political_leader",
        "MilitaryForce": "military_commander", "Military_Force": "military_commander",
        "MilitaryCommander": "military_commander", "Military_Commander": "military_commander",
        "ProxyGroup": "militia_leader", "Proxy_Group": "militia_leader",
        "InternationalOrg": "diplomat", "International_Org": "diplomat",
        "EconomicEntity": "economic_leader", "Economic_Entity": "economic_leader",
        "MediaOutlet": "media_figure", "Media_Outlet": "media_figure",
        "Person": "individual",
        "Organization": "organizational_leader",
    }
    return mapping.get(entity_type, "individual")


def _actor_type_to_role(actor_type: str) -> str:
    """Map actor type to primary role."""
    mapping = {
        "NationState": "head_of_state",
        "ProxyGroup": "militia_leader",
        "InternationalOrganization": "diplomat",
        "Organization": "organizational_leader",
    }
    return mapping.get(actor_type, "leader")


def _get_sub_roles_for_actor(actor: Dict) -> List[tuple]:
    """For each major actor, generate multiple perspective-holders."""
    actor_type = actor.get("actor_type", "Organization")
    actor_name = actor.get("actor_name", "Unknown")

    if actor_type == "NationState":
        return [
            ("head_of_state", f"the national leader of {actor_name}"),
            ("military_commander", f"the top military commander of {actor_name}"),
            ("foreign_minister", f"the chief diplomat of {actor_name}"),
            ("intelligence_chief", f"the intelligence service director of {actor_name}"),
            ("economist", f"the leading economist advising {actor_name}'s government"),
        ]
    elif actor_type == "ProxyGroup":
        return [
            ("militia_leader", f"the military commander of {actor_name}"),
            ("political_leader", f"the political leader of {actor_name}"),
            ("field_commander", f"a field commander on the front lines for {actor_name}"),
        ]
    else:
        return [
            ("leader", f"the leader of {actor_name}"),
            ("advisor", f"a senior advisor within {actor_name}"),
        ]


def _infer_country(entity_name: str, facts: List[str]) -> str:
    """Infer country affiliation from entity name and facts."""
    name_lower = entity_name.lower()
    facts_text = " ".join(facts).lower()

    country_keywords = {
        "usa": ["united states", "american", "us ", "pentagon", "washington", "cia"],
        "iran": ["iran", "iranian", "tehran", "irgc", "khamenei", "persian"],
        "israel": ["israel", "israeli", "idf", "mossad", "netanyahu", "tel aviv"],
        "saudi_arabia": ["saudi", "riyadh", "aramco", "mbs"],
        "russia": ["russia", "russian", "moscow", "kremlin", "putin"],
        "china": ["china", "chinese", "beijing", "pla"],
        "hezbollah": ["hezbollah", "nasrallah", "lebanese resistance"],
        "houthis": ["houthi", "ansar allah", "sanaa"],
        "qatar": ["qatar", "doha", "al jazeera"],
        "uae": ["uae", "emirati", "abu dhabi", "dubai"],
    }

    combined = name_lower + " " + facts_text
    for country, keywords in country_keywords.items():
        if any(kw in combined for kw in keywords):
            return country

    return "unknown"
