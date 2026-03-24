"""
Ontology Generation Service
Analyzes text content and generates entity/relationship type definitions
for geopolitical conflict simulation.
"""

import json
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient


ONTOLOGY_SYSTEM_PROMPT = """You are an expert knowledge graph ontology designer specializing in geopolitical and military conflict analysis. Your task is to analyze the given text content and simulation requirements, and design entity types and relationship types suitable for **geopolitical conflict simulation and prediction**.

**IMPORTANT: You must output valid JSON format data only, nothing else.**

## Core Task Background

We are building a **geopolitical conflict simulation and prediction engine**. In this system:
- Each entity represents a real-world actor that can take strategic, military, diplomatic, economic, or information warfare actions
- Entities interact through alliances, conflicts, commands, negotiations, sanctions, proxy relationships, and information warfare
- We need to simulate how geopolitical actors make decisions and how conflicts escalate or de-escalate

**Entities must be real-world actors capable of strategic action:**

**Can be:**
- Nation-states and their governments (USA, Iran, Israel, Russia, China)
- Military forces, branches, and units (IRGC, IDF, US CENTCOM, Navy, Air Force)
- Non-state armed groups and proxy forces (Hezbollah, Hamas, Houthis, Iraqi PMF)
- Political leaders and military commanders (heads of state, defense ministers, generals)
- Intelligence agencies (CIA, Mossad, IRGC Intelligence)
- Economic entities and markets (OPEC, central banks, energy companies)
- International organizations (UN, EU, NATO, IAEA, GCC)
- Media organizations and information actors (state media, international press)

**Cannot be:**
- Abstract concepts (e.g., "escalation", "deterrence", "geopolitical tension")
- Topics or themes (e.g., "nuclear proliferation", "oil markets")
- Opinions or stances (e.g., "pro-war faction", "peace movement")

## Output Format

Output JSON with this structure:

```json
{
    "entity_types": [
        {
            "name": "EntityTypeName (English, PascalCase)",
            "description": "Brief description (English, max 100 chars)",
            "attributes": [
                {
                    "name": "attribute_name (English, snake_case)",
                    "type": "text",
                    "description": "Attribute description"
                }
            ],
            "examples": ["Example entity 1", "Example entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "RELATIONSHIP_NAME (English, UPPER_SNAKE_CASE)",
            "description": "Brief description (English, max 100 chars)",
            "source_targets": [
                {"source": "SourceEntityType", "target": "TargetEntityType"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Brief analysis of the text content and key geopolitical dynamics identified"
}
```

## Design Guidelines (CRITICAL!)

### 1. Entity Type Design - Must Strictly Follow

**Quantity: Exactly 10 entity types**

**Hierarchical structure (must include both specific and fallback types):**

Your 10 entity types must include:

A. **Fallback types (MUST include, placed last in the list):**
   - `Person`: Fallback for any individual not fitting other specific person types (e.g., analysts, advisors, unnamed officials)
   - `Organization`: Fallback for any organization not fitting other specific types (e.g., think tanks, NGOs, smaller groups)

B. **Specific types (8, designed from text content):**
   - Design specific types for the key actors appearing in the text
   - For geopolitical conflicts, typically include: nation-states, military forces, proxy groups, leaders, intelligence agencies, economic entities, international organizations, media actors

**Design principles for specific types:**
- Identify the most critical actor categories from the text
- Each specific type should have clear boundaries, no overlap
- Description must clearly explain how this type differs from the fallback types
- Focus on actors that TAKE ACTIONS in conflicts (military, diplomatic, economic, intelligence, information)

### 2. Relationship Type Design

- Quantity: 6-10 relationship types
- Relationships should reflect real geopolitical interactions: alliances, conflicts, commands, deployments, sanctions, arms transfers, territorial control, threats, negotiations, funding
- Ensure source_targets cover your defined entity types

### 3. Attribute Design

- 1-3 key attributes per entity type
- **Note**: Attribute names cannot use `name`, `uuid`, `group_id`, `created_at`, `summary` (reserved)
- Recommended: `full_name`, `strategic_role`, `military_capability`, `political_alignment`, `location`, `ideology`, `leadership_style`

## Entity Type Reference (Geopolitical Domain)

**State actors:**
- NationState: Sovereign state (USA, Iran, Israel, Russia, China, Saudi Arabia)
- MilitaryForce: Armed forces branch, unit, or command (IRGC, IDF, US CENTCOM)

**Non-state actors:**
- ProxyGroup: Non-state armed group backed by a state patron (Hezbollah, Hamas, Houthis)

**Individuals:**
- PoliticalLeader: Head of state, senior government official, supreme leader
- MilitaryCommander: General, military branch commander, field commander

**Institutions:**
- IntelligenceAgency: Intelligence and security organization (CIA, Mossad, IRGC Intel)
- EconomicEntity: Economic institution, market, energy company (OPEC, central banks)
- InternationalOrg: International body (UN, EU, NATO, IAEA, GCC)

**Fallback:**
- Person: Any individual not fitting above specific types
- Organization: Any organization not fitting above specific types

## Relationship Type Reference (Geopolitical Domain)

- ALLIES_WITH: Formal or informal alliance between actors
- FIGHTS_AGAINST: Active military engagement or armed conflict
- COMMANDS: Hierarchical military or political control
- DEPLOYS_TO: Force deployment to a region or territory
- SANCTIONS: Economic sanctions or restrictions imposed
- SUPPLIES_WEAPONS_TO: Arms transfer or military equipment supply
- CONTROLS_TERRITORY: De facto control over a geographic area
- THREATENS: Credible threat, deterrence, or ultimatum
- NEGOTIATES_WITH: Diplomatic engagement or peace talks
- FUNDS: Financial support or sponsorship
"""


class OntologyGenerator:
    """
    Ontology Generator
    Analyzes text content and generates entity/relationship type definitions
    for geopolitical conflict simulation.
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate ontology definition for geopolitical conflict simulation.

        Args:
            document_texts: List of document texts
            simulation_requirement: Simulation requirement description
            additional_context: Additional context

        Returns:
            Ontology definition (entity_types, edge_types, etc.)
        """
        # 构建用户消息
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
        
        # 调用LLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )
        
        # 验证和后处理
        result = self._validate_and_process(result)
        
        return result
    
    MAX_TEXT_LENGTH_FOR_LLM = 50000

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Build user message for ontology generation."""

        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(Original text: {original_length} chars, truncated to {self.MAX_TEXT_LENGTH_FOR_LLM} for ontology analysis)..."

        message = f"""## Simulation Requirement

{simulation_requirement}

## Document Content

{combined_text}
"""

        if additional_context:
            message += f"""
## Additional Context

{additional_context}
"""

        message += """
Based on the above content, design entity types and relationship types suitable for geopolitical conflict simulation and prediction.

**Mandatory Rules:**
1. Output exactly 10 entity types
2. The last 2 must be fallback types: Person (individual fallback) and Organization (org fallback)
3. The first 8 are specific types designed from the text content — focusing on geopolitical actors (states, military forces, proxy groups, leaders, intelligence agencies, economic entities, international organizations, media)
4. All entity types must be real-world actors capable of strategic action, NOT abstract concepts
5. Attribute names cannot use reserved words: name, uuid, group_id, created_at, summary — use full_name, org_name, etc. instead
"""

        return message
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and post-process ontology results."""
        
        # 确保必要字段存在
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # 验证实体类型
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # 确保description不超过100字符
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # 验证关系类型
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # Zep API 限制：最多 10 个自定义实体类型，最多 10 个自定义边类型
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10
        
        person_fallback = {
            "name": "Person",
            "description": "Any individual not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "strategic_role", "type": "text", "description": "Role in the geopolitical context (advisor, analyst, diplomat, etc.)"}
            ],
            "examples": ["unnamed defense analyst", "diplomatic envoy", "regional expert"]
        }

        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "geopolitical_alignment", "type": "text", "description": "Geopolitical alignment or affiliation"}
            ],
            "examples": ["think tank", "defense contractor", "humanitarian NGO"]
        }
        
        # Check if fallback types already exist
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # Fallback types to add
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # If adding would exceed 10, remove some existing types
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # Calculate how many to remove
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # Remove from end (keep more important specific types at front)
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # Add fallback types
            result["entity_types"].extend(fallbacks_to_add)
        
        # Final safety check — never exceed Zep limits
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        将本体定义转换为Python代码（类似ontology.py）
        
        Args:
            ontology: 本体定义
            
        Returns:
            Python代码字符串
        """
        code_lines = [
            '"""',
            'Custom entity type definitions',
            'Auto-generated by MiroFish for geopolitical conflict simulation',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== 实体类型定义 ==============',
            '',
        ]
        
        # 生成实体类型
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== 关系类型定义 ==============')
        code_lines.append('')
        
        # 生成关系类型
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # 转换为PascalCase类名
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # 生成类型字典
        code_lines.append('# ============== 类型配置 ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # 生成边的source_targets映射
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)

