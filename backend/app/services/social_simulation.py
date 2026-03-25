"""
Social Simulation Layer — MiroFish-style agent interaction.

Instead of agents independently making decisions in isolation, this layer
simulates social interaction: agents post opinions, argue with each other,
share information, and shift positions based on debate.

Predictions emerge from collective behavior rather than individual decisions.

Architecture:
- Agents are grouped into "forums" (like MiroFish's Twitter/Reddit simulacra)
- Each round, a subset of agents post, respond, and react
- Influence propagates through the social graph
- Sentiment aggregation produces the actual prediction signal
"""

import json
import logging
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger('fors8.social')


@dataclass
class SocialPost:
    """A post/comment in the simulated social environment."""
    post_id: str
    author_id: str
    author_name: str
    author_role: str
    author_country: str
    content: str
    timestamp: str

    # Engagement
    reactions: Dict[str, int] = field(default_factory=lambda: {"agree": 0, "disagree": 0, "alarmed": 0})
    replies: List['SocialPost'] = field(default_factory=list)

    # Metadata
    topic: str = ""  # What aspect of the situation this addresses
    sentiment: float = 0.0  # -1 (anti-escalation) to 1 (pro-escalation)
    credibility_score: float = 0.5
    data_references: List[str] = field(default_factory=list)  # What data points informed this post


@dataclass
class Forum:
    """A discussion space where agents interact."""
    forum_id: str
    name: str
    forum_type: str  # "strategic" (leaders/military), "public" (civilians/media), "market" (traders/economists), "technical" (engineers)
    posts: List[SocialPost] = field(default_factory=list)
    member_ids: List[str] = field(default_factory=list)

    # Topics currently being discussed
    active_topics: List[str] = field(default_factory=list)

    # Aggregate sentiment over time
    sentiment_history: List[Tuple[str, float]] = field(default_factory=list)


class SocialSimulation:
    """Manages the social interaction layer for agent populations."""

    def __init__(self, population: List[Any], situation_data: Dict[str, Any]):
        """
        Args:
            population: List of AgentPersona objects from population_generator
            situation_data: Current world state (escalation, oil price, events, etc.)
        """
        if not population:
            self.population = {}
        elif hasattr(population[0], 'agent_id'):
            self.population = {a.agent_id: a for a in population}
        else:
            self.population = {a['agent_id']: a for a in population}
        self.situation = situation_data
        self.forums: Dict[str, Forum] = {}
        self.social_graph: Dict[str, List[str]] = defaultdict(list)  # agent_id -> followed agent_ids
        self.round_posts: List[SocialPost] = []
        self.post_counter = 0

        self._initialize_forums()
        self._build_social_graph()

    def _initialize_forums(self):
        """Create discussion forums based on agent roles."""
        forum_configs = [
            ("strategic_command", "Strategic Command Channel", "strategic"),
            ("public_discourse", "Public Discourse", "public"),
            ("market_floor", "Market Analysis", "market"),
            ("technical_ops", "Technical Operations", "technical"),
            ("humanitarian", "Humanitarian Situation", "humanitarian"),
            ("media_wire", "Media Wire", "media"),
        ]

        # Role to forum mapping
        role_forums = {
            # Intelligence -> strategic
            "cia_analyst": ["strategic_command"], "cia_officer": ["strategic_command"],
            "pentagon_official": ["strategic_command"], "nsa_analyst": ["strategic_command"],
            "mossad_officer": ["strategic_command"], "shin_bet_agent": ["strategic_command"],
            "aman_analyst": ["strategic_command"], "irgc_intelligence": ["strategic_command"],
            "vevak_officer": ["strategic_command"], "gip_officer": ["strategic_command"],
            "fsb_analyst": ["strategic_command"], "mss_officer": ["strategic_command"],
            # Military -> strategic
            "four_star_general": ["strategic_command"],
            "colonel": ["strategic_command"],
            "field_commander": ["strategic_command"],
            "naval_commander": ["strategic_command"],
            "air_force_commander": ["strategic_command"],
            "missile_commander": ["strategic_command"],
            "special_forces_officer": ["strategic_command"],
            "navy_seal": ["strategic_command"],
            "irgc_commander": ["strategic_command"],
            "quds_force_officer": ["strategic_command"],
            "idf_officer": ["strategic_command"],
            "foot_soldier": ["public_discourse"],
            "conscript_soldier": ["public_discourse"],
            "drone_operator": ["strategic_command"],
            "military_chaplain": ["humanitarian", "public_discourse"],
            # Political leaders
            "president": ["strategic_command", "public_discourse"],
            "prime_minister": ["strategic_command", "public_discourse"],
            "supreme_leader": ["strategic_command", "public_discourse"],
            "king": ["strategic_command", "public_discourse"],
            "crown_prince": ["strategic_command", "public_discourse"],
            "emir": ["strategic_command", "public_discourse"],
            "defense_minister": ["strategic_command"],
            "foreign_minister": ["strategic_command", "public_discourse"],
            "finance_minister": ["market_floor", "strategic_command"],
            "energy_minister": ["market_floor", "strategic_command"],
            "senator": ["public_discourse"],
            "congressman": ["public_discourse"],
            "parliament_member": ["public_discourse"],
            "ambassador": ["strategic_command", "public_discourse"],
            "un_envoy": ["strategic_command", "humanitarian"],
            "political_advisor": ["strategic_command"],
            # Religious
            "grand_ayatollah": ["public_discourse", "humanitarian"],
            "imam": ["public_discourse", "humanitarian"],
            "senior_rabbi": ["public_discourse"],
            "mufti": ["public_discourse"],
            "evangelical_pastor": ["public_discourse"],
            "vatican_envoy": ["humanitarian", "public_discourse"],
            # Economic
            "central_banker": ["market_floor"],
            "oil_trader": ["market_floor"],
            "opec_delegate": ["market_floor"],
            "swf_manager": ["market_floor"],
            "macro_economist": ["market_floor", "public_discourse"],
            "sanctions_analyst": ["market_floor"],
            "shipping_ceo": ["market_floor"],
            "defense_contractor_exec": ["market_floor"],
            "insurance_underwriter": ["market_floor"],
            "commodity_analyst": ["market_floor"],
            # Media
            "war_correspondent": ["media_wire", "public_discourse", "humanitarian"],
            "state_tv_anchor": ["media_wire", "public_discourse"],
            "investigative_journalist": ["media_wire", "public_discourse"],
            "social_media_influencer": ["public_discourse"],
            "think_tank_analyst": ["media_wire", "strategic_command"],
            "historian": ["media_wire", "public_discourse"],
            "foreign_policy_scholar": ["media_wire", "strategic_command"],
            "osint_analyst": ["media_wire", "strategic_command"],
            "propaganda_officer": ["media_wire", "public_discourse"],
            # Technical
            "nuclear_scientist": ["technical_ops"],
            "nuclear_inspector": ["technical_ops", "strategic_command"],
            "desalination_engineer": ["technical_ops", "humanitarian"],
            "telecom_engineer": ["technical_ops"],
            "cyber_warfare_specialist": ["technical_ops", "strategic_command"],
            "oil_refinery_engineer": ["technical_ops"],
            "missile_engineer": ["technical_ops"],
            # Civilian
            "urban_civilian": ["public_discourse"],
            "rural_civilian": ["public_discourse"],
            "refugee": ["humanitarian", "public_discourse"],
            "doctor": ["humanitarian"],
            "nurse": ["humanitarian"],
            "university_professor": ["public_discourse", "media_wire"],
            "student_activist": ["public_discourse"],
            "student": ["public_discourse"],
            "expat_worker": ["public_discourse", "humanitarian"],
            "taxi_driver": ["public_discourse"],
            "market_vendor": ["public_discourse"],
            "factory_worker": ["public_discourse"],
            "farmer": ["public_discourse"],
            "tribal_elder": ["public_discourse"],
            "human_rights_lawyer": ["humanitarian", "public_discourse"],
            "aid_worker": ["humanitarian"],
            "red_cross_delegate": ["humanitarian"],
        }

        for forum_id, name, forum_type in forum_configs:
            self.forums[forum_id] = Forum(
                forum_id=forum_id,
                name=name,
                forum_type=forum_type,
            )

        # Assign agents to forums
        for agent_id, agent in self.population.items():
            role = agent.role if hasattr(agent, 'role') else getattr(agent, 'role', 'urban_civilian')
            role_str = role.value if hasattr(role, 'value') else str(role)

            forums_for_role = role_forums.get(role_str, ["public_discourse"])
            for forum_id in forums_for_role:
                if forum_id in self.forums:
                    self.forums[forum_id].member_ids.append(agent_id)

    def _build_social_graph(self):
        """Build a social graph where agents follow others based on role and country."""
        agents_by_country = defaultdict(list)
        agents_by_role = defaultdict(list)

        for agent_id, agent in self.population.items():
            country = agent.country if hasattr(agent, 'country') else getattr(agent, 'country', '')
            role = agent.role if hasattr(agent, 'role') else getattr(agent, 'role', '')
            role_str = role.value if hasattr(role, 'value') else str(role)
            agents_by_country[country].append(agent_id)
            agents_by_role[role_str].append(agent_id)

        # Each agent follows:
        # 1. High-influence agents from their country (leaders, generals, media)
        # 2. Some agents with similar roles from other countries
        # 3. Random civilians for diversity
        for agent_id, agent in self.population.items():
            country = agent.country if hasattr(agent, 'country') else getattr(agent, 'country', '')
            follows = set()

            # Follow country leaders and influencers
            country_agents = agents_by_country.get(country, [])
            high_influence = [a for a in country_agents if a != agent_id]
            if high_influence:
                follows.update(random.sample(high_influence, min(20, len(high_influence))))

            # Follow some cross-country peers
            role_str = (agent.role.value if hasattr(agent, 'role') and hasattr(agent.role, 'value')
                        else getattr(agent, 'role', '') if hasattr(agent, 'role')
                        else getattr(agent, 'role', '') if hasattr(agent, 'get') else '')
            peers = [a for a in agents_by_role.get(role_str, []) if a != agent_id]
            if peers:
                follows.update(random.sample(peers, min(10, len(peers))))

            self.social_graph[agent_id] = list(follows)

    def run_social_round(
        self,
        round_num: int,
        situation_update: Dict[str, Any],
        sample_size: int = 5000,
        llm_callback=None,
    ) -> Dict[str, Any]:
        """Run one round of social interaction.

        Args:
            round_num: Current simulation round
            situation_update: Latest world state
            sample_size: Number of agents who post this round (not all 100K post every round)
            llm_callback: Optional async function(prompt, agent) -> response for LLM-generated posts.
                         If None, uses rule-based post generation.

        Returns:
            Dict with forum summaries, sentiment shifts, emerging narratives, and prediction signals.
        """
        self.situation = situation_update
        self.round_posts = []

        # Select which agents post this round (weighted by influence and stress)
        posting_agents = self._select_posting_agents(sample_size)

        # Phase 1: Generate posts (agents react to situation)
        for agent_id in posting_agents:
            agent = self.population[agent_id]
            post = self._generate_post(agent, round_num, llm_callback)
            if post:
                self.round_posts.append(post)
                # Add to appropriate forum
                role_str = (agent.role.value if hasattr(agent, 'role') and hasattr(agent.role, 'value')
                            else getattr(agent, 'role', 'urban_civilian'))
                for forum in self.forums.values():
                    if agent_id in forum.member_ids:
                        forum.posts.append(post)
                        break  # Post to primary forum only

        # Phase 2: Reactions and replies (agents respond to each other)
        self._process_reactions(round_num)

        # Phase 3: Influence propagation (opinions shift based on exposure)
        sentiment_shifts = self._propagate_influence()

        # Phase 4: Aggregate signals
        result = self._aggregate_round(round_num)
        result["sentiment_shifts"] = sentiment_shifts

        return result

    def _select_posting_agents(self, sample_size: int) -> List[str]:
        """Select which agents post this round, weighted by influence and stress."""
        agent_ids = list(self.population.keys())

        if len(agent_ids) <= sample_size:
            return agent_ids

        # Weight by influence_radius * (1 + stress_level)
        weights = []
        for aid in agent_ids:
            agent = self.population[aid]
            influence = (agent.influence_radius if hasattr(agent, 'influence_radius')
                         else getattr(agent, 'influence_radius', 10))
            stress = (agent.stress_level if hasattr(agent, 'stress_level')
                      else getattr(agent, 'stress_level', 0.0))
            weights.append(max(1, influence * (1 + stress)))

        total = sum(weights)
        probs = [w / total for w in weights]

        # Weighted sampling without replacement
        selected = set()
        while len(selected) < sample_size:
            idx = random.choices(range(len(agent_ids)), weights=probs, k=1)[0]
            selected.add(agent_ids[idx])

        return list(selected)

    def _generate_post(self, agent, round_num: int, llm_callback=None) -> Optional[SocialPost]:
        """Generate a social post for an agent based on their role and personality."""
        self.post_counter += 1

        agent_id = agent.agent_id if hasattr(agent, 'agent_id') else agent['agent_id']
        agent_name = agent.agent_name if hasattr(agent, 'agent_name') else agent['agent_name']
        role = agent.role if hasattr(agent, 'role') else getattr(agent, 'role', 'civilian')
        role_str = role.value if hasattr(role, 'value') else str(role)
        country = agent.country if hasattr(agent, 'country') else getattr(agent, 'country', 'unknown')

        hawk = agent.hawkishness if hasattr(agent, 'hawkishness') else getattr(agent, 'hawkishness', 0.5)
        risk_tol = agent.risk_tolerance if hasattr(agent, 'risk_tolerance') else getattr(agent, 'risk_tolerance', 0.5)
        nationalism = agent.nationalism if hasattr(agent, 'nationalism') else getattr(agent, 'nationalism', 0.5)
        info_trust = agent.information_trust if hasattr(agent, 'information_trust') else getattr(agent, 'information_trust', 0.5)
        credibility = agent.credibility if hasattr(agent, 'credibility') else getattr(agent, 'credibility', 0.3)
        background = agent.background if hasattr(agent, 'background') else getattr(agent, 'background', '')

        # Determine sentiment based on personality + situation
        escalation = self.situation.get("escalation", 5)
        oil_price = self.situation.get("oil_price", 85)

        # Hawks become more vocal at higher escalation, doves become more vocal too (protest)
        sentiment = (hawk - 0.5) * 2  # Center around 0
        sentiment += (escalation - 5) * 0.05 * (1 if hawk > 0.5 else -1)  # Situation pressure
        sentiment = max(-1.0, min(1.0, sentiment))

        # Topic selection based on role
        topic = self._select_topic(role_str, country)

        # Rule-based post content (fast, no LLM needed)
        content = self._rule_based_content(role_str, country, topic, sentiment, hawk,
                                           nationalism, escalation, oil_price, background)

        data_refs = []
        if "oil" in topic.lower() or "economic" in topic.lower():
            data_refs.append("market_data.oil_price")
        if "military" in topic.lower() or "strike" in topic.lower():
            data_refs.append("situation.escalation_level")
        if "humanitarian" in topic.lower() or "civilian" in topic.lower():
            data_refs.append("situation.casualties")

        return SocialPost(
            post_id=f"post_{round_num}_{self.post_counter}",
            author_id=agent_id,
            author_name=agent_name,
            author_role=role_str,
            author_country=country,
            content=content,
            timestamp=datetime.now().isoformat(),
            topic=topic,
            sentiment=round(sentiment, 2),
            credibility_score=credibility,
            data_references=data_refs,
        )

    def _select_topic(self, role: str, country: str) -> str:
        """Select a discussion topic based on role and country context."""
        role_topics = {
            # Intelligence
            "cia_analyst": ["threat_assessment", "enemy_capabilities", "proxy_activity", "intelligence_gaps"],
            "cia_officer": ["source_network_status", "covert_operations", "enemy_intentions", "back_channel_contacts"],
            "pentagon_official": ["force_readiness", "logistics", "coalition_coordination", "escalation_options"],
            "mossad_officer": ["iran_nuclear_program", "proxy_network_disruption", "intelligence_operations", "threat_neutralization"],
            "irgc_intelligence": ["resistance_axis_coordination", "asymmetric_response_options", "sanctions_evasion", "proxy_mobilization"],
            "aman_analyst": ["missile_threat_assessment", "air_defense_gaps", "enemy_force_disposition", "tunnel_network_activity"],
            # Military
            "four_star_general": ["strategic_options", "force_deployment", "escalation_ladder", "coalition_burden_sharing"],
            "colonel": ["unit_readiness", "tactical_situation", "logistics_status", "morale"],
            "field_commander": ["contact_with_enemy", "casualty_situation", "ammunition_status", "reinforcement_needs"],
            "naval_commander": ["strait_patrol_status", "submarine_threats", "shipping_protection", "mine_countermeasures"],
            "missile_commander": ["launch_readiness", "target_list_priority", "interceptor_stock", "counterstrike_options"],
            "foot_soldier": ["daily_survival", "morale", "leadership_trust", "casualty_fears"],
            "conscript_soldier": ["fear", "confusion", "desire_to_go_home", "questioning_orders"],
            "drone_operator": ["target_identification", "collateral_damage_assessment", "mission_tempo", "psychological_toll"],
            # Political
            "president": ["war_strategy", "domestic_pressure", "alliance_management", "exit_options"],
            "prime_minister": ["coalition_stability", "public_opinion", "international_pressure", "military_strategy"],
            "supreme_leader": ["regime_survival", "revolutionary_principles", "divine_mandate", "nuclear_decision"],
            "king": ["regime_stability", "regional_power_balance", "oil_strategy", "succession_security"],
            "crown_prince": ["modernization_at_risk", "diplomatic_positioning", "defense_spending", "international_reputation"],
            "defense_minister": ["military_budget", "weapons_procurement", "casualty_management", "force_readiness"],
            "senator": ["constituent_pressure", "defense_authorization", "diplomatic_solution", "election_calculus"],
            "ambassador": ["diplomatic_channels", "ceasefire_prospects", "humanitarian_access", "alliance_strain"],
            # Religious
            "grand_ayatollah": ["divine_will", "martyrdom_doctrine", "peace_fatwa", "moral_authority"],
            "imam": ["community_welfare", "moral_guidance", "peace_or_resistance", "humanitarian_duty"],
            "senior_rabbi": ["security_imperative", "moral_limits_of_war", "community_safety", "peace_prospects"],
            # Economic
            "oil_trader": ["oil_price_forecast", "supply_disruption", "hedge_strategy", "strait_closure_probability"],
            "macro_economist": ["gdp_impact", "inflation_forecast", "trade_disruption", "recession_risk"],
            "shipping_ceo": ["route_safety", "insurance_costs", "fleet_redeployment", "contractual_obligations"],
            "insurance_underwriter": ["war_risk_premium", "total_loss_scenarios", "claims_exposure", "reinsurance_capacity"],
            # Media
            "war_correspondent": ["civilian_casualties", "infrastructure_damage", "frontline_reality", "government_lies"],
            "state_tv_anchor": ["official_narrative", "enemy_atrocities", "national_heroism", "victory_messaging"],
            "investigative_journalist": ["hidden_casualties", "corruption", "intelligence_failures", "cover_ups"],
            "historian": ["historical_parallels", "pattern_recognition", "long_term_consequences", "lessons_ignored"],
            "osint_analyst": ["satellite_evidence", "flight_tracking", "shipping_movements", "social_media_verification"],
            # Technical
            "nuclear_scientist": ["enrichment_status", "facility_damage_assessment", "proliferation_risk", "program_timeline"],
            "desalination_engineer": ["plant_vulnerability", "water_reserves", "backup_systems", "emergency_protocols"],
            "telecom_engineer": ["cable_vulnerability", "internet_disruption_risk", "backup_routes", "repair_capability"],
            "cyber_warfare_specialist": ["attack_surface", "defensive_gaps", "offensive_options", "infrastructure_targets"],
            # Civilian
            "urban_civilian": ["daily_survival", "food_prices", "safety_concerns", "family_welfare"],
            "refugee": ["shelter_needs", "family_separation", "aid_access", "return_prospects"],
            "doctor": ["casualty_influx", "supply_shortage", "triage_decisions", "moral_injury"],
            "student_activist": ["regime_critique", "protest_organizing", "information_sharing", "repression_fear"],
            "expat_worker": ["evacuation_plans", "job_security", "remittance_disruption", "safety"],
            "taxi_driver": ["fuel_prices", "passenger_stories", "street_mood", "income_collapse"],
            "farmer": ["water_shortage", "crop_failure", "market_access", "land_damage"],
            "tribal_elder": ["tribal_allegiance", "territorial_defense", "negotiation_with_all_sides", "community_survival"],
            "aid_worker": ["access_denied", "humanitarian_crisis_scale", "donor_fatigue", "staff_safety"],
        }

        topics = role_topics.get(role, ["general_situation", "personal_impact", "future_outlook"])
        return random.choice(topics)

    def _rule_based_content(self, role: str, country: str, topic: str, sentiment: float,
                            hawk: float, nationalism: float, escalation: float,
                            oil_price: float, background: str) -> str:
        """Generate post content using rules (no LLM needed — fast for 100K agents)."""

        country_label = country.replace("_", " ").title()

        # Categorize roles for content generation
        intel_military = {"cia_analyst", "cia_officer", "pentagon_official", "nsa_analyst",
            "mossad_officer", "shin_bet_agent", "aman_analyst", "irgc_intelligence",
            "vevak_officer", "gip_officer", "fsb_analyst", "mss_officer",
            "four_star_general", "colonel", "field_commander", "naval_commander",
            "air_force_commander", "missile_commander", "special_forces_officer",
            "navy_seal", "irgc_commander", "quds_force_officer", "idf_officer",
            "drone_operator", "military_general", "military_officer", "military_analyst",
            "intelligence_officer"}

        political = {"president", "prime_minister", "supreme_leader", "king",
            "crown_prince", "emir", "defense_minister", "foreign_minister",
            "finance_minister", "energy_minister", "senator", "congressman",
            "parliament_member", "ambassador", "un_envoy", "political_advisor",
            "head_of_state", "cabinet_minister", "legislator", "diplomat"}

        economic = {"central_banker", "oil_trader", "opec_delegate", "swf_manager",
            "macro_economist", "sanctions_analyst", "shipping_ceo",
            "defense_contractor_exec", "insurance_underwriter", "commodity_analyst",
            "economist", "business_executive", "shipping_executive"}

        media = {"war_correspondent", "state_tv_anchor", "investigative_journalist",
            "social_media_influencer", "think_tank_analyst", "historian",
            "foreign_policy_scholar", "osint_analyst", "propaganda_officer",
            "state_media_journalist", "independent_journalist"}

        religious = {"grand_ayatollah", "imam", "senior_rabbi", "mufti",
            "evangelical_pastor", "vatican_envoy", "religious_leader",
            "military_chaplain"}

        enlisted = {"foot_soldier", "conscript_soldier"}

        technical = {"nuclear_scientist", "nuclear_inspector", "desalination_engineer",
            "telecom_engineer", "cyber_warfare_specialist", "oil_refinery_engineer",
            "missile_engineer", "nuclear_engineer", "infrastructure_engineer",
            "water_engineer", "cyber_specialist"}

        medical = {"doctor", "nurse", "medical_worker", "red_cross_delegate", "aid_worker"}

        if role in intel_military:
            if sentiment > 0.3:
                templates = [
                    f"SITREP: Escalation at {escalation}/10. Force readiness adequate. Intelligence indicates enemy repositioning. Recommend maintaining pressure on {topic.replace('_', ' ')}.",
                    f"Assessment: Current operational tempo sustainable. {country_label} forces holding advantage. {topic.replace('_', ' ')} remains critical priority.",
                    f"Intel update on {topic.replace('_', ' ')}: adversary capabilities degraded but adapting. Window for decisive action narrowing. Recommend immediate {topic.replace('_', ' ')}.",
                ]
            elif sentiment < -0.3:
                templates = [
                    f"SITREP: Casualties mounting beyond projections. Current trajectory unsustainable. Recommend political track engagement on {topic.replace('_', ' ')}.",
                    f"Assessment: Forces overstretched. Ammunition expenditure exceeding resupply by 40%. Need operational pause for {topic.replace('_', ' ')}.",
                    f"Intel indicates adversary still has significant reserves. Our assumptions about quick victory were wrong. Must reassess {topic.replace('_', ' ')}.",
                ]
            else:
                templates = [
                    f"SITREP: Situation fluid. Escalation {escalation}/10. Monitoring {topic.replace('_', ' ')}. Maintaining defensive posture pending further intelligence.",
                    f"Assessment: Intelligence picture incomplete on {topic.replace('_', ' ')}. Multiple scenarios possible. Recommend caution until data improves.",
                ]

        elif role in political:
            if sentiment > 0.3:
                templates = [
                    f"{country_label} will not back down. National security demands firm response. Our allies and our people expect nothing less than decisive action.",
                    f"The threat to {country_label}'s security is existential. We have exhausted diplomatic options on {topic.replace('_', ' ')}. Further restraint would be dangerous.",
                    f"I have consulted with military and intelligence leadership. {country_label} is prepared for all scenarios. Our resolve is absolute.",
                ]
            elif sentiment < -0.3:
                templates = [
                    f"The cost of this conflict to {country_label}'s people is too high. Oil at ${oil_price}, inflation crushing families. We must find a path to {topic.replace('_', ' ')}.",
                    f"I am hearing from constituents every day — they want this to end. The economic damage, the casualties. We need diplomatic solutions, not more strikes.",
                    f"The international community is calling for restraint. {country_label} must show leadership. Continued escalation serves no one's interest.",
                ]
            else:
                templates = [
                    f"Monitoring situation carefully. {country_label} prepared for all scenarios but prefers diplomatic resolution. Escalation at {escalation}/10 demands measured response.",
                    f"In close consultation with allies on {topic.replace('_', ' ')}. All options remain on the table. We seek de-escalation but will defend our interests.",
                ]

        elif role in economic:
            templates = [
                f"Oil at ${oil_price}/bbl — {'unsustainable' if oil_price > 100 else 'elevated but manageable'}. Strait closure risk pricing at {escalation*10}%. Adjusting positions on {topic.replace('_', ' ')}.",
                f"Supply chain stress indicators: {topic.replace('_', ' ')}. Shipping insurance premiums up {int(escalation*50)}%. GCC markets under {'severe' if escalation > 7 else 'moderate'} pressure.",
                f"Economic impact: trade disruption through Hormuz affecting {'critical' if escalation > 7 else 'significant'} portion of global supply chains. GDP forecasts revised down {escalation}%.",
                f"Markets pricing in {'extended conflict' if escalation > 6 else 'near-term resolution'}. Key risk: {topic.replace('_', ' ')}. Position accordingly.",
            ]

        elif role in media:
            if role == "state_tv_anchor" or role == "propaganda_officer":
                templates = [
                    f"Our brave forces advancing on all fronts. {country_label} standing strong. Enemy propaganda cannot hide the truth of our victories.",
                    f"Official: {topic.replace('_', ' ')} situation under control. {country_label} responding with measured strength. Victory is certain.",
                    f"Breaking: Enemy forces suffering catastrophic losses. {country_label}'s military demonstrating superior capability in {topic.replace('_', ' ')}.",
                ]
            elif role == "osint_analyst":
                templates = [
                    f"Satellite imagery from {topic.replace('_', ' ')}: confirms {'damage to facilities' if escalation > 6 else 'military repositioning'}. Shipping data shows {'disruption' if escalation > 5 else 'altered routes'}.",
                    f"OSINT thread: Tracking {topic.replace('_', ' ')} using open sources. Flight data, AIS tracking, and social media geolocations paint {'alarming' if escalation > 7 else 'complex'} picture.",
                ]
            elif role == "historian":
                templates = [
                    f"Historical parallel: Current situation echoes {'1973 oil crisis' if oil_price > 100 else '2019 Hormuz tensions'}. Key lesson: {topic.replace('_', ' ')} tends to escalate before resolution.",
                    f"From a historical perspective, {topic.replace('_', ' ')} has precedent. No modern power has sustained {'>8/10 escalation' if escalation > 8 else 'this level of confrontation'} indefinitely.",
                ]
            else:
                templates = [
                    f"Reporting from {'the ground' if role == 'war_correspondent' else 'sources'}: {topic.replace('_', ' ')}. Civilian impact {'devastating' if escalation > 7 else 'significant'}. Escalation: {escalation}/10.",
                    f"Sources confirm: {topic.replace('_', ' ')} situation {'worse than officially stated' if role == 'investigative_journalist' else 'developing rapidly'}. Independent verification ongoing.",
                    f"{'BREAKING' if role == 'war_correspondent' else 'Analysis'}: {topic.replace('_', ' ')} developments signal {'major shift' if escalation > 7 else 'continued uncertainty'}.",
                ]

        elif role in enlisted:
            templates = [
                f"Day {int(escalation * 3)} at the front. Heard explosions again. {'Scared' if sentiment < 0 else 'Holding strong'} but morale is {'low' if sentiment < 0 else 'holding'}. Missing home.",
                f"Rations running low. Mail delayed 2 weeks. Sergeant says {'we push forward' if sentiment > 0 else 'hold position'}. Just want this to end.",
                f"Lost two guys from my unit yesterday. {'For what?' if sentiment < 0 else 'We will avenge them.'}. They {'had families' if sentiment < 0 else 'died heroes'}.",
            ]

        elif role in religious:
            if sentiment > 0:
                templates = [
                    f"God commands us to defend our land and our people. This is a {'divine test' if hawk > 0.6 else 'time of trial'}. {country_label} will prevail by {'divine will' if hawk > 0.7 else 'faith and perseverance'}.",
                    f"Our {'martyrs light the path' if hawk > 0.7 else 'faith sustains us'}. {topic.replace('_', ' ')} is {'Gods plan' if hawk > 0.8 else 'a test we must endure'}.",
                ]
            else:
                templates = [
                    f"Every life is sacred — Muslim, Jewish, Christian, all. This violence must end. We call on ALL sides for immediate ceasefire and {topic.replace('_', ' ')}.",
                    f"Our duty is to protect the innocent. The suffering demands peace. I call on leaders to find the courage for {topic.replace('_', ' ')} before more children die.",
                ]

        elif role in technical:
            templates = [
                f"TECHNICAL ASSESSMENT: {topic.replace('_', ' ')} {'critically compromised' if escalation > 7 else 'under stress'}. Backup systems at {'30%' if escalation > 7 else '60%'} capacity. {'3-5 day reserves' if 'water' in topic or 'desal' in topic else 'Repair timeline: weeks'}.",
                f"Engineering reality: {topic.replace('_', ' ')} cannot be fixed by political promises. Physical constraints are absolute. {'If this fails, millions lose water' if 'water' in topic or 'desal' in topic else 'Cascading failures likely at current damage levels'}.",
                f"Infrastructure report: {topic.replace('_', ' ')} damage assessment shows {'irreversible in short term' if escalation > 8 else 'repairable with resources'}. {'Internet cables at risk' if 'cable' in topic or 'telecom' in topic else 'Critical systems degrading'}.",
            ]

        elif role in medical:
            templates = [
                f"{'Field hospital' if role in ('aid_worker', 'red_cross_delegate') else 'Hospital'} overwhelmed. {int(escalation * 12)} new casualties today. Medical supplies: {'critically low' if escalation > 6 else 'adequate for now'}. Staff working {int(12 + escalation)} hour shifts.",
                f"What I'm seeing: {'children with burn injuries' if escalation > 7 else 'mostly blast injuries'}. Water for sterilization: {'running out' if escalation > 7 else 'sufficient'}. We need {'immediate humanitarian access' if escalation > 6 else 'more supplies'}.",
                f"Humanitarian situation: {'catastrophic' if escalation > 8 else 'severe' if escalation > 5 else 'concerning'}. {topic.replace('_', ' ')} directly affecting patient outcomes. {'People are dying of treatable injuries' if escalation > 7 else 'Managing with what we have'}.",
            ]

        elif role == "expat_worker":
            templates = [
                f"Embassy says leave if you can. Flights are ${'3000+' if escalation > 6 else '1500'}. My contract, my family depends on remittances. {'Desalination plant near us was hit — thats our water' if escalation > 7 else 'Water still running but for how long?'}",
                f"Half the workers in my compound already left. Company says operations continuing but {'I dont believe them' if sentiment < 0 else 'we are trying to stay'}. Sending money home is {'impossible now' if escalation > 7 else 'getting harder'}.",
            ]

        elif role in ("student", "student_activist"):
            templates = [
                f"University {'closed indefinitely' if escalation > 6 else 'partially open'}. {'Organizing protests — this generation will not be silent' if role == 'student_activist' else 'Future feels impossible'}. Information contradicts state media. Who to believe?",
                f"{'We demand accountability from leadership' if role == 'student_activist' else 'Just want to graduate and have a future'}. {topic.replace('_', ' ')} affects everything. {'Arrested 2 classmates yesterday' if role == 'student_activist' and escalation > 7 else 'Campus mood is bleak'}.",
            ]

        else:
            templates = [
                f"{'Cannot find bread at the market' if escalation > 7 else 'Prices doubled this week'}. {'Water supply intermittent' if escalation > 6 else 'Basic services strained'}. When does this end?",
                f"Heard {'explosions all night' if escalation > 7 else 'news reports'}. Kids {'cannot sleep' if escalation > 6 else 'asking questions I cannot answer'}. Fuel {'unavailable' if escalation > 8 else 'lines stretching for kilometers'}.",
                f"Family in {country_label} reporting {'severe shortages' if escalation > 7 else 'rising costs'}. {'Trying to send money but transfers blocked' if escalation > 6 else 'Worried about what comes next'}.",
            ]

        return random.choice(templates)

    def _process_reactions(self, round_num: int):
        """Agents react to posts from agents they follow."""
        # Each agent sees a few posts from their feed and reacts
        for agent_id, followed in self.social_graph.items():
            if not followed:
                continue

            agent = self.population.get(agent_id)
            if not agent:
                continue

            hawk = agent.hawkishness if hasattr(agent, 'hawkishness') else getattr(agent, 'hawkishness', 0.5)

            # Find posts from followed agents this round
            followed_set = set(followed)
            visible_posts = [p for p in self.round_posts if p.author_id in followed_set]

            for post in visible_posts[:5]:  # React to up to 5 posts
                # Agreement based on sentiment alignment
                alignment = 1.0 - abs(hawk - 0.5 - post.sentiment)
                if alignment > 0.6:
                    post.reactions["agree"] += 1
                elif alignment < 0.3:
                    post.reactions["disagree"] += 1
                if post.sentiment > 0.5 or post.sentiment < -0.5:
                    post.reactions["alarmed"] += 1

    def _propagate_influence(self) -> Dict[str, float]:
        """Shift agent sentiments based on exposure to posts."""
        shifts = {}

        for agent_id, followed in self.social_graph.items():
            if not followed:
                continue

            agent = self.population.get(agent_id)
            if not agent:
                continue

            # Find posts this agent saw
            followed_set = set(followed)
            visible = [p for p in self.round_posts if p.author_id in followed_set]

            if not visible:
                continue

            # Weight by credibility
            weighted_sentiment = sum(p.sentiment * p.credibility_score for p in visible)
            total_cred = sum(p.credibility_score for p in visible)
            if total_cred == 0:
                continue

            avg_sentiment = weighted_sentiment / total_cred

            # How susceptible is this agent to influence?
            info_trust = (agent.information_trust if hasattr(agent, 'information_trust')
                          else getattr(agent, 'information_trust', 0.5))
            analytical = (agent.analytical_depth if hasattr(agent, 'analytical_depth')
                          else getattr(agent, 'analytical_depth', 0.5))

            # Analytical agents resist influence more; trusting agents accept it more
            susceptibility = info_trust * (1.0 - analytical * 0.5) * 0.1  # Max 10% shift per round

            current = (agent.current_sentiment if hasattr(agent, 'current_sentiment')
                       else getattr(agent, 'current_sentiment', 0.0))

            shift = (avg_sentiment - current) * susceptibility
            new_sentiment = max(-1.0, min(1.0, current + shift))

            if hasattr(agent, 'current_sentiment'):
                agent.current_sentiment = round(new_sentiment, 3)
            else:
                agent['current_sentiment'] = round(new_sentiment, 3)

            if abs(shift) > 0.01:
                shifts[agent_id] = round(shift, 4)

        return shifts

    def _aggregate_round(self, round_num: int) -> Dict[str, Any]:
        """Aggregate social signals into prediction-relevant data."""

        # Per-forum sentiment
        forum_sentiments = {}
        for forum_id, forum in self.forums.items():
            round_posts = [p for p in forum.posts if p.post_id.startswith(f"post_{round_num}_")]
            if round_posts:
                avg = sum(p.sentiment for p in round_posts) / len(round_posts)
                forum_sentiments[forum_id] = {
                    "avg_sentiment": round(avg, 3),
                    "post_count": len(round_posts),
                    "top_topics": self._top_topics(round_posts),
                }
                forum.sentiment_history.append((str(round_num), avg))

        # Per-country sentiment
        country_sentiments = defaultdict(list)
        for agent in self.population.values():
            country = agent.country if hasattr(agent, 'country') else getattr(agent, 'country', '')
            sentiment = (agent.current_sentiment if hasattr(agent, 'current_sentiment')
                         else getattr(agent, 'current_sentiment', 0.0))
            country_sentiments[country].append(sentiment)

        country_avg = {
            c: round(sum(s) / len(s), 3)
            for c, s in country_sentiments.items() if s
        }

        # Emerging narratives (most common topics this round)
        all_topics = [p.topic for p in self.round_posts]
        topic_counts = defaultdict(int)
        for t in all_topics:
            topic_counts[t] += 1
        top_narratives = sorted(topic_counts.items(), key=lambda x: -x[1])[:5]

        # Prediction signals: aggregate hawkish vs dovish sentiment
        total_agents = len(self.population)
        hawk_count = sum(1 for a in self.population.values()
                         if (a.current_sentiment if hasattr(a, 'current_sentiment')
                             else a.get('current_sentiment', 0)) > 0.2)
        dove_count = sum(1 for a in self.population.values()
                         if (a.current_sentiment if hasattr(a, 'current_sentiment')
                             else a.get('current_sentiment', 0)) < -0.2)

        escalation_pressure = hawk_count / max(total_agents, 1)
        deescalation_pressure = dove_count / max(total_agents, 1)

        return {
            "round": round_num,
            "total_posts": len(self.round_posts),
            "forum_sentiments": forum_sentiments,
            "country_sentiments": country_avg,
            "top_narratives": top_narratives,
            "escalation_pressure": round(escalation_pressure, 3),
            "deescalation_pressure": round(deescalation_pressure, 3),
            "net_pressure": round(escalation_pressure - deescalation_pressure, 3),
            "high_engagement_posts": [
                {
                    "author": p.author_name,
                    "country": p.author_country,
                    "role": p.author_role,
                    "content": p.content[:200],
                    "sentiment": p.sentiment,
                    "reactions": p.reactions,
                }
                for p in sorted(self.round_posts,
                                key=lambda x: sum(x.reactions.values()), reverse=True)[:10]
            ],
        }

    def _top_topics(self, posts: List[SocialPost]) -> List[str]:
        """Get the most discussed topics."""
        counts = defaultdict(int)
        for p in posts:
            counts[p.topic] += 1
        return [t for t, _ in sorted(counts.items(), key=lambda x: -x[1])[:3]]

    def get_population_state(self) -> Dict[str, Any]:
        """Get current state of the entire population for analysis."""
        return {
            "total_agents": len(self.population),
            "forums": {fid: {"members": len(f.member_ids), "total_posts": len(f.posts)}
                       for fid, f in self.forums.items()},
            "sentiment_distribution": {
                "very_hawkish": sum(1 for a in self.population.values()
                                    if (a.current_sentiment if hasattr(a, 'current_sentiment')
                                        else a.get('current_sentiment', 0)) > 0.5),
                "hawkish": sum(1 for a in self.population.values()
                               if 0.2 < (a.current_sentiment if hasattr(a, 'current_sentiment')
                                          else a.get('current_sentiment', 0)) <= 0.5),
                "neutral": sum(1 for a in self.population.values()
                               if -0.2 <= (a.current_sentiment if hasattr(a, 'current_sentiment')
                                            else a.get('current_sentiment', 0)) <= 0.2),
                "dovish": sum(1 for a in self.population.values()
                              if -0.5 <= (a.current_sentiment if hasattr(a, 'current_sentiment')
                                           else a.get('current_sentiment', 0)) < -0.2),
                "very_dovish": sum(1 for a in self.population.values()
                                   if (a.current_sentiment if hasattr(a, 'current_sentiment')
                                       else a.get('current_sentiment', 0)) < -0.5),
            },
        }
