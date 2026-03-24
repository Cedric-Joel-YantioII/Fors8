"""
Geopolitical Actor Profile Generator.

Converts Zep graph entities into detailed geopolitical actor profiles for
the conflict simulation engine. Replaces oasis_profile_generator.py.

Generates profiles with:
- Strategic doctrine, leadership style, red lines
- Military capability, force strength, defense systems
- Ideology/temperament: martyrdom_willingness, eschatological_factor, etc.
- Behavioral parameters: risk_tolerance, escalation_threshold
- Historical behavior patterns from Zep knowledge base
"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader
from .world_state import ActorTier

logger = get_logger('mirofish.geopolitical_profile')


@dataclass
class GeopoliticalActorProfile:
    """Profile for a geopolitical actor in the conflict simulation."""

    # Identity
    actor_id: str = ""
    actor_name: str = ""
    actor_type: str = ""  # NationState, ProxyGroup, PoliticalLeader, etc.
    tier: str = "operational"  # strategic, operational, information
    description: str = ""

    # Strategic
    strategic_doctrine: str = ""
    leadership_style: str = ""
    red_lines: List[str] = field(default_factory=list)
    historical_behavior_patterns: str = ""
    primary_objective: str = ""
    secondary_objectives: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    # Military
    military_capability: Dict[str, Any] = field(default_factory=dict)
    nuclear_status: str = "none"  # none, ambiguous, developing, armed
    defense_systems: List[str] = field(default_factory=list)
    key_weapons: List[str] = field(default_factory=list)

    # Behavioral
    risk_tolerance: float = 0.5
    escalation_threshold: float = 0.5
    negotiation_willingness: float = 0.5
    casualty_threshold: float = 0.5

    # Ideology & Temperament
    belief_system: str = ""
    martyrdom_willingness: float = 0.0
    eschatological_factor: float = 0.0
    regime_survival_priority: float = 0.5
    ideological_commitment: float = 0.5
    leadership_temperament: str = ""

    # Political
    domestic_constraints: str = ""
    public_accountability_level: float = 0.5
    alliance_network: List[str] = field(default_factory=list)
    adversaries: List[str] = field(default_factory=list)

    # Initial state values (fed into ActorState)
    initial_force_strength: float = 50.0
    initial_economic_health: float = 0.5
    initial_domestic_approval: float = 0.5
    initial_interceptor_inventory: float = 1.0
    initial_missile_inventory: float = 1.0

    # Intel visibility toward other actors
    initial_intel_visibility: Dict[str, float] = field(default_factory=dict)

    # LLM persona prompt (detailed text for simulation)
    persona: str = ""

    # Source entity info
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    graph_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "actor_type": self.actor_type,
            "tier": self.tier,
            "description": self.description,
            "strategic_doctrine": self.strategic_doctrine,
            "leadership_style": self.leadership_style,
            "red_lines": self.red_lines,
            "historical_behavior_patterns": self.historical_behavior_patterns,
            "primary_objective": self.primary_objective,
            "secondary_objectives": self.secondary_objectives,
            "constraints": self.constraints,
            "military_capability": self.military_capability,
            "nuclear_status": self.nuclear_status,
            "defense_systems": self.defense_systems,
            "key_weapons": self.key_weapons,
            "risk_tolerance": self.risk_tolerance,
            "escalation_threshold": self.escalation_threshold,
            "negotiation_willingness": self.negotiation_willingness,
            "casualty_threshold": self.casualty_threshold,
            "belief_system": self.belief_system,
            "martyrdom_willingness": self.martyrdom_willingness,
            "eschatological_factor": self.eschatological_factor,
            "regime_survival_priority": self.regime_survival_priority,
            "ideological_commitment": self.ideological_commitment,
            "leadership_temperament": self.leadership_temperament,
            "domestic_constraints": self.domestic_constraints,
            "public_accountability_level": self.public_accountability_level,
            "alliance_network": self.alliance_network,
            "adversaries": self.adversaries,
            "initial_force_strength": self.initial_force_strength,
            "initial_economic_health": self.initial_economic_health,
            "initial_domestic_approval": self.initial_domestic_approval,
            "initial_interceptor_inventory": self.initial_interceptor_inventory,
            "initial_missile_inventory": self.initial_missile_inventory,
            "initial_intel_visibility": self.initial_intel_visibility,
            "persona": self.persona,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "graph_id": self.graph_id,
        }


# Entity types that map to each tier
TIER_1_TYPES = {"nationstate", "nation_state"}
TIER_2_TYPES = {
    "militaryforce", "military_force", "proxygroup", "proxy_group",
    "internationalorg", "international_org", "economicentity", "economic_entity",
}
TIER_3_TYPES = {"mediaoutlet", "media_outlet", "informationactor"}
INDIVIDUAL_TYPES = {"politicalleader", "political_leader", "militarycommander", "military_commander"}


PROFILE_GENERATION_PROMPT = """You are a geopolitical analyst creating a detailed actor profile for a conflict simulation.

Based on the entity information below, generate a comprehensive geopolitical actor profile.

## Entity Information
- Name: {entity_name}
- Type: {entity_type}
- Attributes: {entity_attributes}
- Relationships: {entity_relationships}
- Additional Context from Knowledge Base: {zep_context}

## Generate the following profile (output valid JSON only):

```json
{{
    "description": "2-3 sentence description of this actor's role in the conflict",
    "strategic_doctrine": "Their overall strategic approach (e.g., 'maximum pressure', 'forward defense', 'axis of resistance', 'strategic patience')",
    "leadership_style": "How decisions are made (e.g., 'centralized authoritarian', 'consensus-based democratic', 'IRGC-dominated theocratic')",
    "red_lines": ["List of actions that would trigger maximum response"],
    "historical_behavior_patterns": "How this actor has behaved in past crises — specific examples",
    "primary_objective": "Main strategic goal in this conflict",
    "secondary_objectives": ["Other goals"],
    "constraints": ["What limits their actions — domestic politics, resources, alliances, etc."],
    "military_capability": {{
        "branches": ["list of military branches/forces"],
        "key_systems": ["notable weapons systems"],
        "personnel_estimate": "approximate force size",
        "notable_capabilities": ["special capabilities"],
        "known_weaknesses": ["vulnerabilities"]
    }},
    "nuclear_status": "none/ambiguous/developing/armed",
    "defense_systems": ["missile defense, air defense systems"],
    "key_weapons": ["notable offensive weapons"],
    "risk_tolerance": 0.0-1.0,
    "escalation_threshold": 0.0-1.0,
    "negotiation_willingness": 0.0-1.0,
    "casualty_threshold": 0.0-1.0,
    "belief_system": "Religious, ideological, or political belief system that shapes decisions",
    "martyrdom_willingness": 0.0-1.0,
    "eschatological_factor": 0.0-1.0,
    "regime_survival_priority": 0.0-1.0,
    "ideological_commitment": 0.0-1.0,
    "leadership_temperament": "Brief characterization (e.g., 'unpredictable deal-maker', 'radical IRGC-aligned hardliner')",
    "domestic_constraints": "What domestic factors constrain this actor",
    "public_accountability_level": 0.0-1.0,
    "alliance_network": ["allied actor names"],
    "adversaries": ["adversary actor names"],
    "initial_force_strength": 0-100,
    "initial_economic_health": 0.0-1.0,
    "initial_domestic_approval": 0.0-1.0,
    "persona": "A detailed 500+ word persona prompt for the LLM to role-play as this actor. Include: identity, doctrine, communication style, historical precedents, ideology, temperament, and decision-making framework. For religious actors, include relevant theological doctrines. For state actors, include their leader's personal style."
}}
```

Be specific and grounded in real-world data. For Iran/IRGC, include Shia martyrdom doctrine, Mahdist eschatology, and Ashura warfare concepts. For Israel, include security-first doctrine and preemptive strike philosophy. For USA under Trump, include deal-making orientation and maximum pressure approach.
"""


class GeopoliticalProfileGenerator:
    """Generates geopolitical actor profiles from Zep graph entities."""

    def __init__(
        self,
        openai_client: Optional[OpenAI] = None,
        zep_client: Optional[Zep] = None,
        graph_id: Optional[str] = None,
    ):
        self.openai_client = openai_client or OpenAI(
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )
        self.zep_client = zep_client
        self.graph_id = graph_id
        self.model_name = Config.LLM_MODEL_NAME

    def generate_profiles(
        self,
        entities: List[EntityNode],
        simulation_requirement: str = "",
        progress_callback=None,
    ) -> List[GeopoliticalActorProfile]:
        """Generate profiles for all entities.

        Args:
            entities: List of entities from Zep graph
            simulation_requirement: Description of what we're simulating
            progress_callback: Optional callback(current, total) for progress tracking

        Returns:
            List of GeopoliticalActorProfile objects
        """
        profiles = []
        total = len(entities)

        for i, entity in enumerate(entities):
            try:
                profile = self._generate_single_profile(entity, simulation_requirement)
                profiles.append(profile)
                logger.info(f"Generated profile for {entity.name} ({i + 1}/{total})")
            except Exception as e:
                logger.error(f"Failed to generate profile for {entity.name}: {e}")
                # Create a minimal profile
                profiles.append(self._create_minimal_profile(entity))

            if progress_callback:
                progress_callback(i + 1, total)

            # Rate limiting
            if i < total - 1:
                time.sleep(0.5)

        return profiles

    def _generate_single_profile(
        self, entity: EntityNode, simulation_requirement: str
    ) -> GeopoliticalActorProfile:
        """Generate a single actor profile using LLM."""

        # Gather Zep context
        zep_context = self._get_zep_context(entity)

        # Build attributes string
        attrs_str = json.dumps(entity.attributes, ensure_ascii=False) if entity.attributes else "{}"

        # Build relationships string
        rels = []
        for rel in (entity.relationships or []):
            rels.append(f"{rel.get('type', 'RELATED_TO')} → {rel.get('target_name', 'unknown')}")
        rels_str = ", ".join(rels) if rels else "No relationships found"

        prompt = PROFILE_GENERATION_PROMPT.format(
            entity_name=entity.name,
            entity_type=entity.entity_type,
            entity_attributes=attrs_str,
            entity_relationships=rels_str,
            zep_context=zep_context or "No additional context available",
        )

        response = self.openai_client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Generate the geopolitical actor profile for {entity.name}. "
                    f"Simulation context: {simulation_requirement}",
                },
            ],
            temperature=0.5,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)

        # Determine tier
        entity_type_lower = entity.entity_type.lower().replace("_", "")
        if entity_type_lower in TIER_1_TYPES or entity_type_lower in {t.replace("_", "") for t in TIER_1_TYPES}:
            tier = "strategic"
        elif entity_type_lower in TIER_3_TYPES or entity_type_lower in {t.replace("_", "") for t in TIER_3_TYPES}:
            tier = "information"
        else:
            tier = "operational"

        profile = GeopoliticalActorProfile(
            actor_id=entity.uuid or entity.name.lower().replace(" ", "_"),
            actor_name=entity.name,
            actor_type=entity.entity_type,
            tier=tier,
            description=data.get("description", ""),
            strategic_doctrine=data.get("strategic_doctrine", ""),
            leadership_style=data.get("leadership_style", ""),
            red_lines=data.get("red_lines", []),
            historical_behavior_patterns=data.get("historical_behavior_patterns", ""),
            primary_objective=data.get("primary_objective", ""),
            secondary_objectives=data.get("secondary_objectives", []),
            constraints=data.get("constraints", []),
            military_capability=data.get("military_capability", {}),
            nuclear_status=data.get("nuclear_status", "none"),
            defense_systems=data.get("defense_systems", []),
            key_weapons=data.get("key_weapons", []),
            risk_tolerance=float(data.get("risk_tolerance", 0.5)),
            escalation_threshold=float(data.get("escalation_threshold", 0.5)),
            negotiation_willingness=float(data.get("negotiation_willingness", 0.5)),
            casualty_threshold=float(data.get("casualty_threshold", 0.5)),
            belief_system=data.get("belief_system", ""),
            martyrdom_willingness=float(data.get("martyrdom_willingness", 0.0)),
            eschatological_factor=float(data.get("eschatological_factor", 0.0)),
            regime_survival_priority=float(data.get("regime_survival_priority", 0.5)),
            ideological_commitment=float(data.get("ideological_commitment", 0.5)),
            leadership_temperament=data.get("leadership_temperament", ""),
            domestic_constraints=data.get("domestic_constraints", ""),
            public_accountability_level=float(data.get("public_accountability_level", 0.5)),
            alliance_network=data.get("alliance_network", []),
            adversaries=data.get("adversaries", []),
            initial_force_strength=float(data.get("initial_force_strength", 50)),
            initial_economic_health=float(data.get("initial_economic_health", 0.5)),
            initial_domestic_approval=float(data.get("initial_domestic_approval", 0.5)),
            persona=data.get("persona", ""),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity.entity_type,
            graph_id=self.graph_id,
        )

        return profile

    def _create_minimal_profile(self, entity: EntityNode) -> GeopoliticalActorProfile:
        """Create a minimal profile when LLM generation fails."""
        return GeopoliticalActorProfile(
            actor_id=entity.uuid or entity.name.lower().replace(" ", "_"),
            actor_name=entity.name,
            actor_type=entity.entity_type,
            tier="operational",
            description=f"Geopolitical actor: {entity.name}",
            persona=f"You are {entity.name}, a {entity.entity_type} actor in this conflict.",
            source_entity_uuid=entity.uuid,
            source_entity_type=entity.entity_type,
            graph_id=self.graph_id,
        )

    def _get_zep_context(self, entity: EntityNode) -> Optional[str]:
        """Retrieve additional context from Zep for this entity."""
        if not self.zep_client or not self.graph_id:
            return None

        try:
            results = self.zep_client.graph.search(
                graph_id=self.graph_id,
                query=f"{entity.name} capabilities doctrine strategy military economic",
                limit=15,
            )

            if results and hasattr(results, 'results'):
                facts = []
                for r in results.results[:15]:
                    if hasattr(r, 'fact'):
                        facts.append(f"- {r.fact}")
                return "\n".join(facts) if facts else None
        except Exception as e:
            logger.warning(f"Zep context retrieval failed for {entity.name}: {e}")

        return None
