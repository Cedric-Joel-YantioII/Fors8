"""
Population Generator — creates diverse agent populations for social simulation.

Instead of 17 monolithic country actors, generates thousands of individuals per country:
military officials, politicians, journalists, economists, civilians, engineers, etc.

Each agent has unique personality traits, professional background, information access level,
and behavioral tendencies that make them argue, debate, and influence each other differently.
"""

import random
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

logger = logging.getLogger('fors8.population')


class AgentRole(Enum):
    """Specific real-world positions — not generic labels."""
    # Intelligence Services
    CIA_ANALYST = "cia_analyst"
    CIA_OFFICER = "cia_officer"
    PENTAGON_OFFICIAL = "pentagon_official"
    NSA_ANALYST = "nsa_analyst"
    MOSSAD_OFFICER = "mossad_officer"
    SHIN_BET_AGENT = "shin_bet_agent"
    AMAN_ANALYST = "aman_analyst"  # Israeli Military Intelligence
    IRGC_INTELLIGENCE = "irgc_intelligence"
    VEVAK_OFFICER = "vevak_officer"  # Iran Ministry of Intelligence
    GIP_OFFICER = "gip_officer"  # Saudi General Intelligence Presidency
    FSB_ANALYST = "fsb_analyst"
    MSS_OFFICER = "mss_officer"  # China Ministry of State Security

    # Military — specific ranks
    FOUR_STAR_GENERAL = "four_star_general"
    COLONEL = "colonel"
    FIELD_COMMANDER = "field_commander"
    NAVAL_COMMANDER = "naval_commander"
    AIR_FORCE_COMMANDER = "air_force_commander"
    MISSILE_COMMANDER = "missile_commander"
    SPECIAL_FORCES_OFFICER = "special_forces_officer"
    FOOT_SOLDIER = "foot_soldier"
    NAVY_SEAL = "navy_seal"  # US special ops
    IRGC_COMMANDER = "irgc_commander"  # Iran Revolutionary Guard
    QUDS_FORCE_OFFICER = "quds_force_officer"  # Iran external ops
    IDF_OFFICER = "idf_officer"
    CONSCRIPT_SOLDIER = "conscript_soldier"
    MILITARY_CHAPLAIN = "military_chaplain"

    # Political Leaders — specific positions
    PRESIDENT = "president"
    PRIME_MINISTER = "prime_minister"
    SUPREME_LEADER = "supreme_leader"  # Iran
    KING = "king"  # Saudi, Jordan
    CROWN_PRINCE = "crown_prince"  # Saudi MBS, UAE MBZ
    EMIR = "emir"  # Qatar, Kuwait
    DEFENSE_MINISTER = "defense_minister"
    FOREIGN_MINISTER = "foreign_minister"
    FINANCE_MINISTER = "finance_minister"
    ENERGY_MINISTER = "energy_minister"
    SENATOR = "senator"
    CONGRESSMAN = "congressman"
    PARLIAMENT_MEMBER = "parliament_member"
    AMBASSADOR = "ambassador"
    UN_ENVOY = "un_envoy"
    POLITICAL_ADVISOR = "political_advisor"

    # Religious Leaders
    GRAND_AYATOLLAH = "grand_ayatollah"
    IMAM = "imam"
    SENIOR_RABBI = "senior_rabbi"
    MUFTI = "mufti"
    EVANGELICAL_PASTOR = "evangelical_pastor"
    VATICAN_ENVOY = "vatican_envoy"

    # Economic
    CENTRAL_BANKER = "central_banker"
    OIL_TRADER = "oil_trader"
    OPEC_DELEGATE = "opec_delegate"
    SOVEREIGN_WEALTH_FUND_MANAGER = "swf_manager"
    MACRO_ECONOMIST = "macro_economist"
    SANCTIONS_ANALYST = "sanctions_analyst"
    SHIPPING_CEO = "shipping_ceo"
    DEFENSE_CONTRACTOR_EXEC = "defense_contractor_exec"
    INSURANCE_UNDERWRITER = "insurance_underwriter"
    COMMODITY_ANALYST = "commodity_analyst"

    # Media & Information
    WAR_CORRESPONDENT = "war_correspondent"
    STATE_TV_ANCHOR = "state_tv_anchor"
    INVESTIGATIVE_JOURNALIST = "investigative_journalist"
    SOCIAL_MEDIA_INFLUENCER = "social_media_influencer"
    THINK_TANK_ANALYST = "think_tank_analyst"
    HISTORIAN = "historian"
    FOREIGN_POLICY_SCHOLAR = "foreign_policy_scholar"
    OSINT_ANALYST = "osint_analyst"
    PROPAGANDA_OFFICER = "propaganda_officer"

    # Technical
    NUCLEAR_SCIENTIST = "nuclear_scientist"
    NUCLEAR_INSPECTOR = "nuclear_inspector"  # IAEA
    DESALINATION_ENGINEER = "desalination_engineer"
    TELECOM_ENGINEER = "telecom_engineer"  # Undersea cables
    CYBER_WARFARE_SPECIALIST = "cyber_warfare_specialist"
    OIL_REFINERY_ENGINEER = "oil_refinery_engineer"
    MISSILE_ENGINEER = "missile_engineer"
    DRONE_OPERATOR = "drone_operator"

    # Civilian
    URBAN_CIVILIAN = "urban_civilian"
    RURAL_CIVILIAN = "rural_civilian"
    REFUGEE = "refugee"
    DOCTOR = "doctor"
    NURSE = "nurse"
    UNIVERSITY_PROFESSOR = "university_professor"
    STUDENT_ACTIVIST = "student_activist"
    STUDENT = "student"
    EXPAT_WORKER = "expat_worker"
    TAXI_DRIVER = "taxi_driver"
    MARKET_VENDOR = "market_vendor"
    FACTORY_WORKER = "factory_worker"
    FARMER = "farmer"
    TRIBAL_ELDER = "tribal_elder"
    HUMAN_RIGHTS_LAWYER = "human_rights_lawyer"
    AID_WORKER = "aid_worker"
    RED_CROSS_DELEGATE = "red_cross_delegate"


# Country-specific role distributions (how many of each role per 1000 agents)
# These reflect real demographics and power structures
COUNTRY_ROLE_DISTRIBUTIONS = {
    "usa": {
        # Intelligence
        AgentRole.CIA_ANALYST: 8, AgentRole.CIA_OFFICER: 5, AgentRole.PENTAGON_OFFICIAL: 8,
        AgentRole.NSA_ANALYST: 5,
        # Military
        AgentRole.FOUR_STAR_GENERAL: 2, AgentRole.COLONEL: 10, AgentRole.FIELD_COMMANDER: 8,
        AgentRole.NAVAL_COMMANDER: 5, AgentRole.AIR_FORCE_COMMANDER: 5,
        AgentRole.SPECIAL_FORCES_OFFICER: 5, AgentRole.NAVY_SEAL: 3, AgentRole.FOOT_SOLDIER: 20,
        AgentRole.MILITARY_CHAPLAIN: 2,
        # Political
        AgentRole.PRESIDENT: 1, AgentRole.DEFENSE_MINISTER: 1, AgentRole.FOREIGN_MINISTER: 1,
        AgentRole.SENATOR: 10, AgentRole.CONGRESSMAN: 15, AgentRole.AMBASSADOR: 5,
        AgentRole.POLITICAL_ADVISOR: 10,
        # Religious
        AgentRole.EVANGELICAL_PASTOR: 8,
        # Economic
        AgentRole.CENTRAL_BANKER: 3, AgentRole.OIL_TRADER: 15, AgentRole.MACRO_ECONOMIST: 10,
        AgentRole.DEFENSE_CONTRACTOR_EXEC: 10, AgentRole.SANCTIONS_ANALYST: 5,
        AgentRole.COMMODITY_ANALYST: 8,
        # Media
        AgentRole.WAR_CORRESPONDENT: 10, AgentRole.INVESTIGATIVE_JOURNALIST: 15,
        AgentRole.SOCIAL_MEDIA_INFLUENCER: 20, AgentRole.THINK_TANK_ANALYST: 15,
        AgentRole.HISTORIAN: 5, AgentRole.FOREIGN_POLICY_SCHOLAR: 8, AgentRole.OSINT_ANALYST: 5,
        # Technical
        AgentRole.CYBER_WARFARE_SPECIALIST: 8, AgentRole.DRONE_OPERATOR: 5,
        # Civilian
        AgentRole.URBAN_CIVILIAN: 250, AgentRole.RURAL_CIVILIAN: 100,
        AgentRole.DOCTOR: 15, AgentRole.NURSE: 15, AgentRole.UNIVERSITY_PROFESSOR: 10,
        AgentRole.STUDENT: 60, AgentRole.STUDENT_ACTIVIST: 10,
        AgentRole.TAXI_DRIVER: 15, AgentRole.FACTORY_WORKER: 20,
        AgentRole.HUMAN_RIGHTS_LAWYER: 5, AgentRole.AID_WORKER: 5,
    },
    "iran": {
        # Intelligence
        AgentRole.IRGC_INTELLIGENCE: 15, AgentRole.VEVAK_OFFICER: 10,
        AgentRole.QUDS_FORCE_OFFICER: 8,
        # Military
        AgentRole.FOUR_STAR_GENERAL: 3, AgentRole.IRGC_COMMANDER: 15,
        AgentRole.COLONEL: 10, AgentRole.FIELD_COMMANDER: 10,
        AgentRole.MISSILE_COMMANDER: 8, AgentRole.NAVAL_COMMANDER: 5,
        AgentRole.FOOT_SOLDIER: 30, AgentRole.CONSCRIPT_SOLDIER: 20,
        AgentRole.DRONE_OPERATOR: 8,
        # Political
        AgentRole.SUPREME_LEADER: 1, AgentRole.PRESIDENT: 1,
        AgentRole.DEFENSE_MINISTER: 1, AgentRole.FOREIGN_MINISTER: 1,
        AgentRole.PARLIAMENT_MEMBER: 10, AgentRole.AMBASSADOR: 3,
        AgentRole.POLITICAL_ADVISOR: 5,
        # Religious
        AgentRole.GRAND_AYATOLLAH: 3, AgentRole.IMAM: 20, AgentRole.MUFTI: 5,
        # Economic
        AgentRole.CENTRAL_BANKER: 2, AgentRole.OIL_TRADER: 5,
        AgentRole.MACRO_ECONOMIST: 5, AgentRole.SANCTIONS_ANALYST: 5,
        # Media
        AgentRole.STATE_TV_ANCHOR: 15, AgentRole.PROPAGANDA_OFFICER: 10,
        AgentRole.INVESTIGATIVE_JOURNALIST: 3, AgentRole.SOCIAL_MEDIA_INFLUENCER: 10,
        AgentRole.HISTORIAN: 5,
        # Technical
        AgentRole.NUCLEAR_SCIENTIST: 10, AgentRole.MISSILE_ENGINEER: 10,
        AgentRole.CYBER_WARFARE_SPECIALIST: 8, AgentRole.OIL_REFINERY_ENGINEER: 5,
        AgentRole.TELECOM_ENGINEER: 3,
        # Civilian
        AgentRole.URBAN_CIVILIAN: 200, AgentRole.RURAL_CIVILIAN: 150,
        AgentRole.REFUGEE: 20, AgentRole.DOCTOR: 15, AgentRole.NURSE: 15,
        AgentRole.UNIVERSITY_PROFESSOR: 10, AgentRole.STUDENT: 60,
        AgentRole.STUDENT_ACTIVIST: 20, AgentRole.TAXI_DRIVER: 15,
        AgentRole.MARKET_VENDOR: 15, AgentRole.FARMER: 20,
        AgentRole.FACTORY_WORKER: 15, AgentRole.TRIBAL_ELDER: 5,
    },
    "israel": {
        # Intelligence
        AgentRole.MOSSAD_OFFICER: 15, AgentRole.SHIN_BET_AGENT: 10, AgentRole.AMAN_ANALYST: 15,
        # Military
        AgentRole.FOUR_STAR_GENERAL: 2, AgentRole.COLONEL: 15, AgentRole.IDF_OFFICER: 20,
        AgentRole.FIELD_COMMANDER: 10, AgentRole.AIR_FORCE_COMMANDER: 8,
        AgentRole.NAVAL_COMMANDER: 5, AgentRole.SPECIAL_FORCES_OFFICER: 8,
        AgentRole.CONSCRIPT_SOLDIER: 30, AgentRole.DRONE_OPERATOR: 8,
        AgentRole.MISSILE_COMMANDER: 5, AgentRole.MILITARY_CHAPLAIN: 3,
        # Political
        AgentRole.PRIME_MINISTER: 1, AgentRole.DEFENSE_MINISTER: 1,
        AgentRole.FOREIGN_MINISTER: 1, AgentRole.PARLIAMENT_MEMBER: 15,
        AgentRole.AMBASSADOR: 8, AgentRole.POLITICAL_ADVISOR: 10,
        # Religious
        AgentRole.SENIOR_RABBI: 10,
        # Economic
        AgentRole.CENTRAL_BANKER: 2, AgentRole.MACRO_ECONOMIST: 10,
        AgentRole.DEFENSE_CONTRACTOR_EXEC: 15, AgentRole.COMMODITY_ANALYST: 5,
        # Media
        AgentRole.WAR_CORRESPONDENT: 10, AgentRole.INVESTIGATIVE_JOURNALIST: 15,
        AgentRole.SOCIAL_MEDIA_INFLUENCER: 15, AgentRole.THINK_TANK_ANALYST: 15,
        AgentRole.HISTORIAN: 5, AgentRole.OSINT_ANALYST: 10,
        # Technical
        AgentRole.NUCLEAR_SCIENTIST: 5, AgentRole.CYBER_WARFARE_SPECIALIST: 15,
        AgentRole.DRONE_OPERATOR: 5,
        # Civilian
        AgentRole.URBAN_CIVILIAN: 250, AgentRole.DOCTOR: 15, AgentRole.NURSE: 10,
        AgentRole.UNIVERSITY_PROFESSOR: 10, AgentRole.STUDENT: 60,
        AgentRole.STUDENT_ACTIVIST: 15, AgentRole.HUMAN_RIGHTS_LAWYER: 5,
    },
    "saudi_arabia": {
        # Intelligence
        AgentRole.GIP_OFFICER: 5,
        # Military
        AgentRole.FOUR_STAR_GENERAL: 1, AgentRole.COLONEL: 8, AgentRole.FIELD_COMMANDER: 5,
        AgentRole.AIR_FORCE_COMMANDER: 3, AgentRole.NAVAL_COMMANDER: 3, AgentRole.FOOT_SOLDIER: 15,
        # Political
        AgentRole.KING: 1, AgentRole.CROWN_PRINCE: 1, AgentRole.DEFENSE_MINISTER: 1,
        AgentRole.FOREIGN_MINISTER: 1, AgentRole.ENERGY_MINISTER: 1,
        AgentRole.AMBASSADOR: 5, AgentRole.POLITICAL_ADVISOR: 5,
        # Religious
        AgentRole.MUFTI: 5, AgentRole.IMAM: 15,
        # Economic
        AgentRole.CENTRAL_BANKER: 2, AgentRole.OIL_TRADER: 10, AgentRole.OPEC_DELEGATE: 3,
        AgentRole.SOVEREIGN_WEALTH_FUND_MANAGER: 5, AgentRole.MACRO_ECONOMIST: 5,
        AgentRole.SHIPPING_CEO: 3, AgentRole.INSURANCE_UNDERWRITER: 3,
        # Media
        AgentRole.STATE_TV_ANCHOR: 8, AgentRole.SOCIAL_MEDIA_INFLUENCER: 15,
        AgentRole.THINK_TANK_ANALYST: 5,
        # Technical
        AgentRole.DESALINATION_ENGINEER: 10, AgentRole.OIL_REFINERY_ENGINEER: 10,
        AgentRole.TELECOM_ENGINEER: 5,
        # Civilian
        AgentRole.URBAN_CIVILIAN: 200, AgentRole.EXPAT_WORKER: 300,
        AgentRole.DOCTOR: 10, AgentRole.NURSE: 10, AgentRole.STUDENT: 40,
        AgentRole.TAXI_DRIVER: 10, AgentRole.MARKET_VENDOR: 10, AgentRole.FARMER: 10,
        AgentRole.TRIBAL_ELDER: 5,
    },
    "uae": {
        AgentRole.COLONEL: 5, AgentRole.AIR_FORCE_COMMANDER: 3,
        AgentRole.CROWN_PRINCE: 1, AgentRole.FOREIGN_MINISTER: 1,
        AgentRole.ENERGY_MINISTER: 1, AgentRole.AMBASSADOR: 5,
        AgentRole.CENTRAL_BANKER: 2, AgentRole.OIL_TRADER: 10,
        AgentRole.SOVEREIGN_WEALTH_FUND_MANAGER: 8, AgentRole.MACRO_ECONOMIST: 5,
        AgentRole.SHIPPING_CEO: 8, AgentRole.INSURANCE_UNDERWRITER: 5,
        AgentRole.SOCIAL_MEDIA_INFLUENCER: 15,
        AgentRole.DESALINATION_ENGINEER: 15, AgentRole.TELECOM_ENGINEER: 10,
        AgentRole.OIL_REFINERY_ENGINEER: 5, AgentRole.CYBER_WARFARE_SPECIALIST: 5,
        AgentRole.URBAN_CIVILIAN: 150, AgentRole.EXPAT_WORKER: 450,
        AgentRole.DOCTOR: 10, AgentRole.STUDENT: 25,
    },
    "qatar": {
        AgentRole.EMIR: 1, AgentRole.FOREIGN_MINISTER: 1, AgentRole.ENERGY_MINISTER: 1,
        AgentRole.AMBASSADOR: 5,
        AgentRole.CENTRAL_BANKER: 2, AgentRole.OIL_TRADER: 8,
        AgentRole.SOVEREIGN_WEALTH_FUND_MANAGER: 8, AgentRole.OPEC_DELEGATE: 2,
        AgentRole.SHIPPING_CEO: 5,
        AgentRole.STATE_TV_ANCHOR: 15,  # Al Jazeera
        AgentRole.INVESTIGATIVE_JOURNALIST: 10,  # Al Jazeera
        AgentRole.SOCIAL_MEDIA_INFLUENCER: 10,
        AgentRole.DESALINATION_ENGINEER: 15, AgentRole.TELECOM_ENGINEER: 10,
        AgentRole.OIL_REFINERY_ENGINEER: 5,
        AgentRole.URBAN_CIVILIAN: 100, AgentRole.EXPAT_WORKER: 500,
        AgentRole.DOCTOR: 5, AgentRole.STUDENT: 15,
    },
    "hezbollah": {
        AgentRole.FIELD_COMMANDER: 20, AgentRole.FOOT_SOLDIER: 40,
        AgentRole.MISSILE_COMMANDER: 15, AgentRole.SPECIAL_FORCES_OFFICER: 10,
        AgentRole.DRONE_OPERATOR: 10,
        AgentRole.POLITICAL_ADVISOR: 5, AgentRole.PARLIAMENT_MEMBER: 5,
        AgentRole.IMAM: 20, AgentRole.GRAND_AYATOLLAH: 2,
        AgentRole.PROPAGANDA_OFFICER: 15, AgentRole.STATE_TV_ANCHOR: 10,
        AgentRole.SOCIAL_MEDIA_INFLUENCER: 10,
        AgentRole.URBAN_CIVILIAN: 200, AgentRole.RURAL_CIVILIAN: 150,
        AgentRole.REFUGEE: 50, AgentRole.DOCTOR: 10, AgentRole.NURSE: 10,
        AgentRole.STUDENT: 30, AgentRole.FARMER: 20, AgentRole.TRIBAL_ELDER: 10,
    },
    "houthis": {
        AgentRole.FIELD_COMMANDER: 20, AgentRole.FOOT_SOLDIER: 50,
        AgentRole.MISSILE_COMMANDER: 15, AgentRole.DRONE_OPERATOR: 15,
        AgentRole.NAVAL_COMMANDER: 10,
        AgentRole.POLITICAL_ADVISOR: 5,
        AgentRole.IMAM: 20, AgentRole.TRIBAL_ELDER: 15,
        AgentRole.PROPAGANDA_OFFICER: 15, AgentRole.SOCIAL_MEDIA_INFLUENCER: 10,
        AgentRole.URBAN_CIVILIAN: 150, AgentRole.RURAL_CIVILIAN: 200,
        AgentRole.REFUGEE: 80, AgentRole.DOCTOR: 5, AgentRole.AID_WORKER: 10,
        AgentRole.FARMER: 30, AgentRole.MARKET_VENDOR: 15,
    },
    "russia": {
        AgentRole.FSB_ANALYST: 10, AgentRole.FOUR_STAR_GENERAL: 2,
        AgentRole.COLONEL: 8, AgentRole.NAVAL_COMMANDER: 5,
        AgentRole.PRESIDENT: 1, AgentRole.FOREIGN_MINISTER: 1, AgentRole.DEFENSE_MINISTER: 1,
        AgentRole.AMBASSADOR: 5, AgentRole.POLITICAL_ADVISOR: 5,
        AgentRole.OIL_TRADER: 10, AgentRole.MACRO_ECONOMIST: 5, AgentRole.SANCTIONS_ANALYST: 5,
        AgentRole.STATE_TV_ANCHOR: 15, AgentRole.PROPAGANDA_OFFICER: 10,
        AgentRole.HISTORIAN: 5, AgentRole.FOREIGN_POLICY_SCHOLAR: 5,
        AgentRole.NUCLEAR_SCIENTIST: 5, AgentRole.CYBER_WARFARE_SPECIALIST: 8,
        AgentRole.URBAN_CIVILIAN: 400, AgentRole.STUDENT: 50,
        AgentRole.UNIVERSITY_PROFESSOR: 5, AgentRole.FACTORY_WORKER: 20,
    },
    "china": {
        AgentRole.MSS_OFFICER: 10, AgentRole.FOUR_STAR_GENERAL: 2,
        AgentRole.COLONEL: 5, AgentRole.NAVAL_COMMANDER: 5,
        AgentRole.PRESIDENT: 1, AgentRole.FOREIGN_MINISTER: 1,
        AgentRole.AMBASSADOR: 5, AgentRole.POLITICAL_ADVISOR: 5,
        AgentRole.CENTRAL_BANKER: 3, AgentRole.OIL_TRADER: 10,
        AgentRole.MACRO_ECONOMIST: 8, AgentRole.SHIPPING_CEO: 8,
        AgentRole.STATE_TV_ANCHOR: 10, AgentRole.PROPAGANDA_OFFICER: 10,
        AgentRole.HISTORIAN: 5, AgentRole.FOREIGN_POLICY_SCHOLAR: 8,
        AgentRole.CYBER_WARFARE_SPECIALIST: 10, AgentRole.TELECOM_ENGINEER: 5,
        AgentRole.URBAN_CIVILIAN: 400, AgentRole.STUDENT: 60,
        AgentRole.UNIVERSITY_PROFESSOR: 8, AgentRole.FACTORY_WORKER: 30,
    },
}

# Default distribution for countries not explicitly defined
DEFAULT_ROLE_DISTRIBUTION = {
    AgentRole.COLONEL: 5, AgentRole.FIELD_COMMANDER: 5, AgentRole.FOOT_SOLDIER: 15,
    AgentRole.PRESIDENT: 1, AgentRole.DEFENSE_MINISTER: 1, AgentRole.FOREIGN_MINISTER: 1,
    AgentRole.PARLIAMENT_MEMBER: 10, AgentRole.AMBASSADOR: 5,
    AgentRole.IMAM: 10, AgentRole.MUFTI: 3,
    AgentRole.MACRO_ECONOMIST: 5, AgentRole.OIL_TRADER: 5, AgentRole.CENTRAL_BANKER: 2,
    AgentRole.INVESTIGATIVE_JOURNALIST: 10, AgentRole.SOCIAL_MEDIA_INFLUENCER: 15,
    AgentRole.THINK_TANK_ANALYST: 5, AgentRole.HISTORIAN: 3,
    AgentRole.DESALINATION_ENGINEER: 5, AgentRole.TELECOM_ENGINEER: 3,
    AgentRole.URBAN_CIVILIAN: 350, AgentRole.RURAL_CIVILIAN: 150,
    AgentRole.DOCTOR: 10, AgentRole.NURSE: 10, AgentRole.STUDENT: 60,
    AgentRole.EXPAT_WORKER: 50, AgentRole.FARMER: 15, AgentRole.MARKET_VENDOR: 10,
    AgentRole.AID_WORKER: 5, AgentRole.TRIBAL_ELDER: 5,
}


# Personality trait ranges by role (min, max) — affects how agents process information
ROLE_PERSONALITY_RANGES = {
    # Intelligence — (hawk_min, hawk_max, risk_min, risk_max, info_trust_min, info_trust_max, analytical_min, analytical_max)
    AgentRole.CIA_ANALYST: (0.3, 0.7, 0.3, 0.6, 0.2, 0.4, 0.8, 1.0),
    AgentRole.CIA_OFFICER: (0.4, 0.8, 0.4, 0.7, 0.2, 0.5, 0.7, 0.9),
    AgentRole.PENTAGON_OFFICIAL: (0.5, 0.8, 0.3, 0.6, 0.3, 0.6, 0.7, 0.9),
    AgentRole.NSA_ANALYST: (0.3, 0.6, 0.2, 0.5, 0.2, 0.4, 0.9, 1.0),
    AgentRole.MOSSAD_OFFICER: (0.5, 0.9, 0.5, 0.8, 0.2, 0.4, 0.8, 1.0),
    AgentRole.SHIN_BET_AGENT: (0.5, 0.8, 0.4, 0.7, 0.2, 0.5, 0.7, 0.9),
    AgentRole.AMAN_ANALYST: (0.4, 0.7, 0.3, 0.6, 0.2, 0.4, 0.8, 1.0),
    AgentRole.IRGC_INTELLIGENCE: (0.6, 0.9, 0.5, 0.8, 0.5, 0.8, 0.5, 0.7),
    AgentRole.VEVAK_OFFICER: (0.5, 0.8, 0.4, 0.7, 0.4, 0.7, 0.6, 0.8),
    AgentRole.GIP_OFFICER: (0.4, 0.7, 0.3, 0.6, 0.4, 0.7, 0.6, 0.8),
    AgentRole.FSB_ANALYST: (0.4, 0.7, 0.3, 0.6, 0.3, 0.6, 0.7, 0.9),
    AgentRole.MSS_OFFICER: (0.3, 0.6, 0.3, 0.5, 0.4, 0.7, 0.8, 1.0),
    # Military
    AgentRole.FOUR_STAR_GENERAL: (0.6, 0.9, 0.4, 0.7, 0.3, 0.6, 0.7, 0.9),
    AgentRole.COLONEL: (0.5, 0.8, 0.4, 0.7, 0.4, 0.6, 0.5, 0.7),
    AgentRole.FIELD_COMMANDER: (0.6, 0.9, 0.5, 0.8, 0.3, 0.5, 0.4, 0.6),
    AgentRole.NAVAL_COMMANDER: (0.5, 0.8, 0.4, 0.7, 0.3, 0.6, 0.6, 0.8),
    AgentRole.AIR_FORCE_COMMANDER: (0.5, 0.8, 0.4, 0.7, 0.3, 0.5, 0.6, 0.8),
    AgentRole.MISSILE_COMMANDER: (0.6, 0.9, 0.5, 0.8, 0.3, 0.5, 0.5, 0.7),
    AgentRole.SPECIAL_FORCES_OFFICER: (0.7, 0.95, 0.6, 0.9, 0.2, 0.4, 0.5, 0.7),
    AgentRole.FOOT_SOLDIER: (0.3, 0.7, 0.3, 0.6, 0.5, 0.8, 0.2, 0.4),
    AgentRole.NAVY_SEAL: (0.7, 0.95, 0.7, 0.95, 0.2, 0.4, 0.5, 0.7),
    AgentRole.IRGC_COMMANDER: (0.7, 0.95, 0.6, 0.9, 0.6, 0.9, 0.4, 0.6),
    AgentRole.QUDS_FORCE_OFFICER: (0.7, 0.95, 0.7, 0.95, 0.5, 0.8, 0.5, 0.7),
    AgentRole.IDF_OFFICER: (0.5, 0.8, 0.5, 0.8, 0.3, 0.5, 0.5, 0.7),
    AgentRole.CONSCRIPT_SOLDIER: (0.2, 0.5, 0.2, 0.5, 0.5, 0.8, 0.2, 0.4),
    AgentRole.DRONE_OPERATOR: (0.4, 0.7, 0.3, 0.6, 0.3, 0.5, 0.6, 0.8),
    # Political
    AgentRole.PRESIDENT: (0.3, 0.7, 0.3, 0.6, 0.3, 0.6, 0.6, 0.9),
    AgentRole.PRIME_MINISTER: (0.3, 0.7, 0.3, 0.6, 0.3, 0.6, 0.6, 0.9),
    AgentRole.SUPREME_LEADER: (0.6, 0.9, 0.4, 0.7, 0.7, 0.95, 0.5, 0.7),
    AgentRole.KING: (0.3, 0.6, 0.2, 0.5, 0.5, 0.8, 0.5, 0.7),
    AgentRole.CROWN_PRINCE: (0.4, 0.7, 0.4, 0.7, 0.4, 0.7, 0.5, 0.7),
    AgentRole.EMIR: (0.2, 0.5, 0.2, 0.5, 0.5, 0.8, 0.5, 0.7),
    AgentRole.DEFENSE_MINISTER: (0.5, 0.8, 0.3, 0.6, 0.3, 0.6, 0.6, 0.8),
    AgentRole.FOREIGN_MINISTER: (0.2, 0.5, 0.2, 0.5, 0.3, 0.6, 0.7, 0.9),
    AgentRole.SENATOR: (0.2, 0.7, 0.2, 0.5, 0.3, 0.7, 0.5, 0.7),
    AgentRole.AMBASSADOR: (0.1, 0.4, 0.2, 0.5, 0.4, 0.7, 0.7, 0.9),
    # Religious
    AgentRole.GRAND_AYATOLLAH: (0.4, 0.9, 0.3, 0.6, 0.7, 0.95, 0.3, 0.5),
    AgentRole.IMAM: (0.2, 0.8, 0.2, 0.5, 0.5, 0.9, 0.2, 0.5),
    AgentRole.SENIOR_RABBI: (0.3, 0.8, 0.2, 0.5, 0.5, 0.8, 0.4, 0.6),
    AgentRole.EVANGELICAL_PASTOR: (0.3, 0.8, 0.2, 0.5, 0.5, 0.9, 0.2, 0.4),
    # Economic
    AgentRole.OIL_TRADER: (0.2, 0.5, 0.5, 0.9, 0.3, 0.5, 0.7, 1.0),
    AgentRole.MACRO_ECONOMIST: (0.1, 0.4, 0.3, 0.6, 0.3, 0.6, 0.8, 1.0),
    AgentRole.CENTRAL_BANKER: (0.1, 0.3, 0.2, 0.4, 0.4, 0.7, 0.8, 1.0),
    AgentRole.SANCTIONS_ANALYST: (0.2, 0.5, 0.2, 0.5, 0.3, 0.5, 0.8, 1.0),
    AgentRole.INSURANCE_UNDERWRITER: (0.1, 0.3, 0.2, 0.4, 0.3, 0.5, 0.8, 1.0),
    AgentRole.COMMODITY_ANALYST: (0.1, 0.4, 0.4, 0.7, 0.3, 0.5, 0.8, 1.0),
    # Media
    AgentRole.WAR_CORRESPONDENT: (0.2, 0.5, 0.4, 0.7, 0.2, 0.5, 0.5, 0.8),
    AgentRole.STATE_TV_ANCHOR: (0.4, 0.8, 0.2, 0.5, 0.7, 0.95, 0.3, 0.5),
    AgentRole.INVESTIGATIVE_JOURNALIST: (0.1, 0.4, 0.3, 0.6, 0.1, 0.3, 0.7, 1.0),
    AgentRole.THINK_TANK_ANALYST: (0.2, 0.6, 0.3, 0.5, 0.3, 0.5, 0.8, 1.0),
    AgentRole.HISTORIAN: (0.1, 0.4, 0.2, 0.4, 0.2, 0.5, 0.8, 1.0),
    AgentRole.OSINT_ANALYST: (0.2, 0.5, 0.3, 0.5, 0.1, 0.3, 0.9, 1.0),
    AgentRole.PROPAGANDA_OFFICER: (0.6, 0.95, 0.3, 0.6, 0.8, 1.0, 0.3, 0.5),
    # Technical
    AgentRole.NUCLEAR_SCIENTIST: (0.2, 0.5, 0.2, 0.4, 0.3, 0.5, 0.9, 1.0),
    AgentRole.DESALINATION_ENGINEER: (0.1, 0.3, 0.1, 0.3, 0.3, 0.5, 0.8, 1.0),
    AgentRole.TELECOM_ENGINEER: (0.1, 0.3, 0.1, 0.3, 0.3, 0.5, 0.8, 1.0),
    AgentRole.MISSILE_ENGINEER: (0.4, 0.7, 0.3, 0.5, 0.4, 0.6, 0.8, 1.0),
    AgentRole.CYBER_WARFARE_SPECIALIST: (0.3, 0.6, 0.4, 0.7, 0.2, 0.4, 0.9, 1.0),
    # Civilian
    AgentRole.URBAN_CIVILIAN: (0.1, 0.7, 0.1, 0.5, 0.3, 0.8, 0.1, 0.6),
    AgentRole.RURAL_CIVILIAN: (0.1, 0.6, 0.1, 0.4, 0.4, 0.9, 0.1, 0.4),
    AgentRole.REFUGEE: (0.0, 0.3, 0.1, 0.3, 0.2, 0.5, 0.1, 0.3),
    AgentRole.STUDENT: (0.1, 0.6, 0.2, 0.6, 0.2, 0.6, 0.3, 0.7),
    AgentRole.STUDENT_ACTIVIST: (0.2, 0.7, 0.3, 0.7, 0.1, 0.4, 0.4, 0.7),
    AgentRole.EXPAT_WORKER: (0.0, 0.3, 0.1, 0.3, 0.3, 0.7, 0.1, 0.4),
    AgentRole.DOCTOR: (0.0, 0.3, 0.2, 0.4, 0.3, 0.5, 0.7, 0.9),
    AgentRole.NURSE: (0.0, 0.3, 0.2, 0.4, 0.3, 0.6, 0.5, 0.7),
    AgentRole.TRIBAL_ELDER: (0.3, 0.7, 0.2, 0.5, 0.6, 0.9, 0.3, 0.5),
    AgentRole.FARMER: (0.1, 0.5, 0.1, 0.4, 0.5, 0.9, 0.1, 0.3),
    AgentRole.TAXI_DRIVER: (0.1, 0.6, 0.2, 0.5, 0.3, 0.7, 0.2, 0.4),
    AgentRole.MARKET_VENDOR: (0.1, 0.5, 0.2, 0.5, 0.3, 0.7, 0.2, 0.4),
    AgentRole.AID_WORKER: (0.0, 0.2, 0.3, 0.6, 0.2, 0.4, 0.6, 0.8),
    AgentRole.HUMAN_RIGHTS_LAWYER: (0.0, 0.2, 0.2, 0.5, 0.1, 0.3, 0.8, 1.0),
}
# Defaults for roles not in the map
_DEFAULT_PERSONALITY = (0.2, 0.6, 0.3, 0.6, 0.3, 0.7, 0.4, 0.7)


@dataclass
class AgentPersona:
    """A single agent in the population."""
    agent_id: str
    agent_name: str
    country: str
    role: AgentRole

    # Personality traits (0.0-1.0)
    hawkishness: float = 0.5       # Preference for aggressive vs peaceful actions
    risk_tolerance: float = 0.5    # Willingness to accept uncertainty
    information_trust: float = 0.5  # Trust in official information vs skepticism
    analytical_depth: float = 0.5   # Shallow reactive vs deep analytical thinking
    emotional_reactivity: float = 0.5  # How much emotions drive decisions
    nationalism: float = 0.5       # Loyalty to national interest

    # Professional context
    information_access: str = "public"  # public, classified, insider, ground_truth
    influence_radius: int = 10          # How many other agents they can influence
    credibility: float = 0.5            # How much weight others give their opinions

    # State
    current_sentiment: float = 0.5  # -1 to 1 (anti-war to pro-war)
    stress_level: float = 0.0

    # Background text for LLM prompt
    background: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "country": self.country,
            "role": self.role.value,
            "hawkishness": self.hawkishness,
            "risk_tolerance": self.risk_tolerance,
            "information_trust": self.information_trust,
            "analytical_depth": self.analytical_depth,
            "emotional_reactivity": self.emotional_reactivity,
            "nationalism": self.nationalism,
            "information_access": self.information_access,
            "influence_radius": self.influence_radius,
            "credibility": self.credibility,
            "current_sentiment": self.current_sentiment,
            "stress_level": self.stress_level,
            "background": self.background,
        }


# Information access by role
ROLE_INFO_ACCESS = {
    # Classified
    AgentRole.PRESIDENT: "classified", AgentRole.PRIME_MINISTER: "classified",
    AgentRole.SUPREME_LEADER: "classified", AgentRole.KING: "classified",
    AgentRole.CROWN_PRINCE: "classified", AgentRole.EMIR: "classified",
    AgentRole.FOUR_STAR_GENERAL: "classified", AgentRole.CIA_OFFICER: "classified",
    AgentRole.CIA_ANALYST: "classified", AgentRole.MOSSAD_OFFICER: "classified",
    AgentRole.IRGC_INTELLIGENCE: "classified", AgentRole.VEVAK_OFFICER: "classified",
    AgentRole.GIP_OFFICER: "classified", AgentRole.FSB_ANALYST: "classified",
    AgentRole.MSS_OFFICER: "classified", AgentRole.NSA_ANALYST: "classified",
    AgentRole.SHIN_BET_AGENT: "classified", AgentRole.AMAN_ANALYST: "classified",
    AgentRole.QUDS_FORCE_OFFICER: "classified",
    # Insider
    AgentRole.DEFENSE_MINISTER: "insider", AgentRole.FOREIGN_MINISTER: "insider",
    AgentRole.FINANCE_MINISTER: "insider", AgentRole.ENERGY_MINISTER: "insider",
    AgentRole.PENTAGON_OFFICIAL: "insider", AgentRole.COLONEL: "insider",
    AgentRole.IRGC_COMMANDER: "insider", AgentRole.IDF_OFFICER: "insider",
    AgentRole.NAVAL_COMMANDER: "insider", AgentRole.AIR_FORCE_COMMANDER: "insider",
    AgentRole.MISSILE_COMMANDER: "insider", AgentRole.SPECIAL_FORCES_OFFICER: "insider",
    AgentRole.NAVY_SEAL: "insider", AgentRole.AMBASSADOR: "insider",
    AgentRole.CENTRAL_BANKER: "insider", AgentRole.NUCLEAR_SCIENTIST: "insider",
    AgentRole.OPEC_DELEGATE: "insider", AgentRole.SOVEREIGN_WEALTH_FUND_MANAGER: "insider",
    AgentRole.POLITICAL_ADVISOR: "insider", AgentRole.CYBER_WARFARE_SPECIALIST: "insider",
    AgentRole.NUCLEAR_INSPECTOR: "insider",
    # Ground truth
    AgentRole.WAR_CORRESPONDENT: "ground_truth", AgentRole.DOCTOR: "ground_truth",
    AgentRole.NURSE: "ground_truth", AgentRole.REFUGEE: "ground_truth",
    AgentRole.AID_WORKER: "ground_truth", AgentRole.RED_CROSS_DELEGATE: "ground_truth",
    AgentRole.DESALINATION_ENGINEER: "ground_truth", AgentRole.FOOT_SOLDIER: "ground_truth",
    AgentRole.CONSCRIPT_SOLDIER: "ground_truth",
}

# Influence radius by role
ROLE_INFLUENCE = {
    AgentRole.PRESIDENT: 10000, AgentRole.PRIME_MINISTER: 10000,
    AgentRole.SUPREME_LEADER: 10000, AgentRole.KING: 10000,
    AgentRole.CROWN_PRINCE: 8000, AgentRole.EMIR: 8000,
    AgentRole.SOCIAL_MEDIA_INFLUENCER: 5000,
    AgentRole.STATE_TV_ANCHOR: 3000, AgentRole.PROPAGANDA_OFFICER: 2000,
    AgentRole.WAR_CORRESPONDENT: 2000, AgentRole.GRAND_AYATOLLAH: 2000,
    AgentRole.INVESTIGATIVE_JOURNALIST: 1000,
    AgentRole.SENIOR_RABBI: 500, AgentRole.IMAM: 500, AgentRole.MUFTI: 500,
    AgentRole.EVANGELICAL_PASTOR: 500,
    AgentRole.FOUR_STAR_GENERAL: 200, AgentRole.THINK_TANK_ANALYST: 200,
    AgentRole.DEFENSE_MINISTER: 150, AgentRole.FOREIGN_MINISTER: 150,
    AgentRole.HISTORIAN: 150, AgentRole.FOREIGN_POLICY_SCHOLAR: 150,
    AgentRole.MACRO_ECONOMIST: 100, AgentRole.SENATOR: 100,
    AgentRole.CONGRESSMAN: 80, AgentRole.PARLIAMENT_MEMBER: 80,
    AgentRole.UNIVERSITY_PROFESSOR: 50, AgentRole.STUDENT_ACTIVIST: 50,
    AgentRole.TRIBAL_ELDER: 50,
}

# Credibility by role
ROLE_CREDIBILITY = {
    AgentRole.PRESIDENT: 0.9, AgentRole.PRIME_MINISTER: 0.9,
    AgentRole.SUPREME_LEADER: 0.9, AgentRole.KING: 0.9,
    AgentRole.FOUR_STAR_GENERAL: 0.85, AgentRole.MOSSAD_OFFICER: 0.85,
    AgentRole.CIA_ANALYST: 0.8, AgentRole.AMAN_ANALYST: 0.8,
    AgentRole.THINK_TANK_ANALYST: 0.75, AgentRole.WAR_CORRESPONDENT: 0.75,
    AgentRole.HISTORIAN: 0.75, AgentRole.FOREIGN_POLICY_SCHOLAR: 0.75,
    AgentRole.NUCLEAR_SCIENTIST: 0.75, AgentRole.NUCLEAR_INSPECTOR: 0.8,
    AgentRole.MACRO_ECONOMIST: 0.7, AgentRole.AMBASSADOR: 0.7,
    AgentRole.INVESTIGATIVE_JOURNALIST: 0.65, AgentRole.OSINT_ANALYST: 0.65,
    AgentRole.DOCTOR: 0.65, AgentRole.DESALINATION_ENGINEER: 0.6,
    AgentRole.TELECOM_ENGINEER: 0.6,
    AgentRole.STATE_TV_ANCHOR: 0.4, AgentRole.PROPAGANDA_OFFICER: 0.3,
    AgentRole.SOCIAL_MEDIA_INFLUENCER: 0.3,
    AgentRole.URBAN_CIVILIAN: 0.2, AgentRole.STUDENT: 0.15,
    AgentRole.FOOT_SOLDIER: 0.2, AgentRole.CONSCRIPT_SOLDIER: 0.15,
    AgentRole.EXPAT_WORKER: 0.15, AgentRole.REFUGEE: 0.2,
    AgentRole.AID_WORKER: 0.7, AgentRole.RED_CROSS_DELEGATE: 0.8,
    AgentRole.HUMAN_RIGHTS_LAWYER: 0.7,
}


# Country-specific name pools (first names common in each country)
COUNTRY_NAMES = {
    "usa": ["James", "Sarah", "Michael", "Emily", "Robert", "Jennifer", "David", "Lisa", "John", "Maria", "William", "Ashley", "Thomas", "Jessica", "Christopher", "Amanda"],
    "iran": ["Mohammad", "Fatimah", "Ali", "Zahra", "Hossein", "Maryam", "Reza", "Narges", "Ahmad", "Sara", "Mehdi", "Leila", "Amir", "Nasrin", "Hamid", "Parisa"],
    "israel": ["Yosef", "Noa", "David", "Yael", "Moshe", "Tamar", "Avraham", "Shira", "Ilan", "Maya", "Eitan", "Rivka", "Avi", "Michal", "Uri", "Dina"],
    "saudi_arabia": ["Mohammed", "Fatima", "Abdullah", "Noura", "Khalid", "Aisha", "Faisal", "Haya", "Sultan", "Maha", "Turki", "Reem", "Bandar", "Lama", "Saud", "Dana"],
    "uae": ["Ahmed", "Maryam", "Rashid", "Fatima", "Hamdan", "Sheikha", "Saeed", "Alyazia", "Omar", "Hessa", "Majid", "Noura", "Theyab", "Maitha", "Mansour", "Shamsa"],
    "qatar": ["Tamim", "Al-Anoud", "Hamad", "Moza", "Jassim", "Fatima", "Khalifa", "Noura", "Nasser", "Hind", "Faisal", "Sheikha", "Thani", "Aisha", "Abdullah", "Mariam"],
    "hezbollah": ["Hassan", "Fatima", "Hussein", "Zainab", "Ali", "Maryam", "Abbas", "Khadija", "Mujtaba", "Sakina", "Jawad", "Ruqayya", "Hadi", "Zahra", "Mahdi", "Narjis"],
    "houthis": ["Abdul-Malik", "Fatima", "Mohammed", "Zainab", "Ahmed", "Khadija", "Ali", "Aisha", "Hassan", "Maryam", "Ibrahim", "Amina", "Yahya", "Sumayyah", "Hamza", "Ruqayya"],
    "iraq_pmf": ["Muqtada", "Fatima", "Hadi", "Zainab", "Qasim", "Maryam", "Jaafar", "Khadija", "Abu", "Zahra", "Nouri", "Sakina", "Haider", "Ruqayya", "Falih", "Amina"],
    "russia": ["Dmitri", "Natasha", "Sergei", "Olga", "Vladimir", "Anna", "Alexei", "Elena", "Ivan", "Maria", "Andrei", "Tatiana", "Nikolai", "Svetlana", "Pavel", "Irina"],
    "china": ["Wei", "Li Na", "Jun", "Xiu Ying", "Lei", "Fang", "Chao", "Min", "Hao", "Yan", "Jian", "Hui", "Tao", "Xia", "Peng", "Ling"],
    "turkey": ["Mehmet", "Ayse", "Mustafa", "Fatma", "Ahmet", "Emine", "Ali", "Hatice", "Huseyin", "Zeynep", "Hasan", "Elif", "Ibrahim", "Merve", "Ismail", "Esra"],
    "egypt": ["Ahmed", "Fatima", "Mohamed", "Nour", "Mahmoud", "Mona", "Ali", "Heba", "Omar", "Dina", "Hassan", "Yasmine", "Khaled", "Rana", "Tarek", "Salma"],
    "jordan": ["Abdullah", "Rania", "Hussein", "Fatima", "Omar", "Noor", "Faisal", "Haya", "Zaid", "Dina", "Hamza", "Lina", "Tariq", "Rana", "Nasser", "Muna"],
    "kuwait": ["Sabah", "Fatima", "Jaber", "Noura", "Ahmad", "Maha", "Nasser", "Hessa", "Mubarak", "Bibi", "Fahad", "Sheikha", "Salem", "Munira", "Hamad", "Reem"],
}


# Role-specific background templates
ROLE_BACKGROUNDS = {
    # Intelligence
    AgentRole.CIA_ANALYST: "CIA analyst at {facility_cia}, {years} years. Specializes in {region} desk. Currently tracking {focus}. Clearance: TS/SCI.",
    AgentRole.CIA_OFFICER: "CIA case officer, {years} years field experience in {region}. Ran networks in {postings}. Currently managing {focus} operations.",
    AgentRole.PENTAGON_OFFICIAL: "Pentagon official in the Office of {pentagon_office}. {years} years DoD service. Advising on {focus}.",
    AgentRole.NSA_ANALYST: "NSA signals intelligence analyst. {years} years intercepting {nsa_target} communications. TS/SCI clearance.",
    AgentRole.MOSSAD_OFFICER: "Mossad operations officer, {years} years. Served in {postings}. Specializes in {focus}. Currently running {responsibility}.",
    AgentRole.SHIN_BET_AGENT: "Shin Bet domestic security agent, {years} years. Focused on {focus}. Currently monitoring {responsibility}.",
    AgentRole.AMAN_ANALYST: "IDF Military Intelligence (Aman) analyst, Unit 8200 veteran. {years} years signals/analysis. Currently assessing {focus}.",
    AgentRole.IRGC_INTELLIGENCE: "IRGC Intelligence Organization officer, {years} years. Reports to Supreme Leader's office. Focused on {focus}. Ideologically committed to the revolution.",
    AgentRole.VEVAK_OFFICER: "VEVAK (Ministry of Intelligence) officer, {years} years. Specializes in {region}. Currently investigating {focus}.",
    AgentRole.GIP_OFFICER: "General Intelligence Presidency officer, {years} years. Serves the Crown Prince directly. Monitoring {focus}.",
    AgentRole.FSB_ANALYST: "FSB analyst, {years} years. Specializes in Middle East operations. Currently assessing {focus} for Moscow.",
    AgentRole.MSS_OFFICER: "Ministry of State Security officer, {years} years. Focused on {region} energy security. Monitoring {focus}.",
    # Military
    AgentRole.FOUR_STAR_GENERAL: "Four-star general, {years} years of service. Commands {command}. Has led forces in {experience}. Strategic doctrine: {perspective}.",
    AgentRole.COLONEL: "Colonel in the {branch}, {years} years. Commands a {unit_type}. Stationed at {location}. Responsible for {responsibility}.",
    AgentRole.FIELD_COMMANDER: "Field commander leading troops in active operations. {years} years combat experience. Currently engaged in {responsibility}. Seeing {trauma_level} action daily.",
    AgentRole.NAVAL_COMMANDER: "Naval commander, {years} years. Commands {naval_unit}. Currently patrolling {naval_area}. Watching for {focus}.",
    AgentRole.AIR_FORCE_COMMANDER: "Air Force commander, {years} years. Oversees {air_ops} operations. Currently flying {air_missions} sorties/day.",
    AgentRole.MISSILE_COMMANDER: "Missile forces commander, {years} years. Controls {missile_type} batteries. Current readiness: {readiness}.",
    AgentRole.SPECIAL_FORCES_OFFICER: "Special forces officer, {years} years. {sf_unit} veteran. Has operated behind enemy lines. Risk tolerance: extreme.",
    AgentRole.FOOT_SOLDIER: "Enlisted soldier, {years} years. Rank: {enlisted_rank}. Currently deployed at {location}. Morale: {morale}. Worried about {concerns_mil}.",
    AgentRole.NAVY_SEAL: "Navy SEAL, {years} years. Multiple deployments. Currently on standby for {responsibility}. Has conducted operations in {postings}.",
    AgentRole.IRGC_COMMANDER: "IRGC Revolutionary Guards commander, {years} years. Leads {irgc_unit}. Reports to Supreme Leader. Believes in exporting the revolution.",
    AgentRole.QUDS_FORCE_OFFICER: "Quds Force officer, {years} years overseas operations. Has coordinated with {proxy_group}. Currently running {responsibility} in {region}.",
    AgentRole.IDF_OFFICER: "IDF officer, {years} years. Serves in {idf_unit}. Has served in {experience}. Currently {responsibility}.",
    AgentRole.CONSCRIPT_SOLDIER: "Conscript soldier, {conscript_months} months into service. Rank: Private. Did not choose to be here. Worried about {concerns_mil}. Morale: {morale}.",
    AgentRole.DRONE_OPERATOR: "Drone operator, {years} years. Flies {drone_type}. Has conducted {drone_missions} missions. Views targets through a screen from {location}.",
    AgentRole.MILITARY_CHAPLAIN: "Military chaplain ({tradition}), {years} years. Counsels troops dealing with {trauma_level} combat. Struggles with moral questions of {moral_dilemma}.",
    # Political Leaders
    AgentRole.PRESIDENT: "President of {country_name}. Facing {challenge}. Domestic approval: {approval}%. Must balance {domestic} with {international}. Election pressure: {election_pressure}.",
    AgentRole.PRIME_MINISTER: "Prime Minister of {country_name}. Coalition of {coalition_size} parties. Approval: {approval}%. {challenge} dominating agenda.",
    AgentRole.SUPREME_LEADER: "Supreme Leader. Ultimate authority over military, judiciary, and foreign policy. Sees conflict through {lens}. Will not compromise on {red_line}.",
    AgentRole.KING: "King of {country_name}. Absolute monarch. Balancing {challenge} with regime stability. Oil revenues {oil_status}. Concerned about {concern}.",
    AgentRole.CROWN_PRINCE: "Crown Prince of {country_name}. De facto ruler. Driving {reform_agenda}. Reputation at stake. Concerned about {concern}.",
    AgentRole.EMIR: "Emir of {country_name}. Small state navigating between great powers. Dependent on {dependency}. Worried about {concern}.",
    AgentRole.DEFENSE_MINISTER: "Defense Minister of {country_name}. {years} years in government. Managing {defense_challenge}. Reporting to {reports_to}.",
    AgentRole.FOREIGN_MINISTER: "Foreign Minister of {country_name}. Career diplomat. Currently managing {current_work}. Speaking with {counterparts} daily.",
    AgentRole.FINANCE_MINISTER: "Finance Minister. Watching budget hemorrhage from war costs. Oil at ${oil_price} {oil_direction}. Currency under {currency_pressure}.",
    AgentRole.ENERGY_MINISTER: "Energy Minister of {country_name}. Managing {energy_challenge}. OPEC coordination critical. Production at {production_level}.",
    AgentRole.SENATOR: "US Senator ({party}), {years} years in office. On {committee} committee. Constituent pressure: {constituent_mood}. {war_stance} on the conflict.",
    AgentRole.CONGRESSMAN: "US Representative ({party}), {years} years. District: {district_type}. Constituent mood: {constituent_mood}. Facing {election_pressure}.",
    AgentRole.PARLIAMENT_MEMBER: "Parliament member, {years} years. Party: {party}. Position on war: {war_stance}. Representing {district_type} constituency.",
    AgentRole.AMBASSADOR: "Ambassador to {posted_to}. Career diplomat with {years} years. Currently delivering {diplomatic_message}. Back-channeling on {current_work}.",
    AgentRole.UN_ENVOY: "UN Special Envoy for the conflict. Mediating between all parties. {years} years in international diplomacy. Frustrated by {frustration}.",
    AgentRole.POLITICAL_ADVISOR: "Political advisor to {advises}. {years} years in politics. Specializes in {specialty}. Currently advising on {current_work}.",
    # Religious
    AgentRole.GRAND_AYATOLLAH: "Grand Ayatollah in {city}. Millions of followers. Issues fatwas on {fatwa_topic}. Views war as {war_view}. Answers only to God.",
    AgentRole.IMAM: "Imam at {mosque} mosque in {city}. Congregation of {size}. Preaches {message}. Community looks to him for {guidance_type}.",
    AgentRole.SENIOR_RABBI: "Senior Rabbi in {city}. {years} years leading community. Views conflict through {lens}. {war_stance} on military operations.",
    AgentRole.MUFTI: "Grand Mufti. Issues religious rulings on {fatwa_topic}. Aligned with {alignment}. Influential across {region}.",
    AgentRole.EVANGELICAL_PASTOR: "Evangelical pastor with {size} congregation. Sees Israel through {lens}. Politically {war_stance}. Influences {community} voters.",
    # Economic
    AgentRole.CENTRAL_BANKER: "Central bank governor, {years} years. Managing {currency_pressure} on currency. Interest rate decisions critical. Watching {indicators}.",
    AgentRole.OIL_TRADER: "Oil trader at {firm}. ${portfolio} book. Brent at ${oil_price}. Watching {indicators}. {years} years in energy markets. Position: {position}.",
    AgentRole.OPEC_DELEGATE: "OPEC delegate for {country_name}. Negotiating production quotas. Balancing {oil_balance}. Price target: ${oil_target}.",
    AgentRole.SOVEREIGN_WEALTH_FUND_MANAGER: "SWF manager, ${swf_aum}B under management. Repositioning portfolio for {war_scenario}. Concerned about {concern}.",
    AgentRole.MACRO_ECONOMIST: "Economist at {institution}. Specializes in {specialty}. Publishing on {topic}. Forecasting {forecast}.",
    AgentRole.SANCTIONS_ANALYST: "Sanctions compliance analyst at {firm}. Tracking {sanctions_target} sanctions. {years} years in compliance.",
    AgentRole.SHIPPING_CEO: "CEO of {shipping_company}. Fleet of {fleet_size} vessels. Rerouting around {chokepoint}. Insurance costs up {insurance_pct}%.",
    AgentRole.DEFENSE_CONTRACTOR_EXEC: "Executive at {defense_company}. Stock up {stock_change}% since conflict began. Backlog of orders for {product}.",
    AgentRole.INSURANCE_UNDERWRITER: "War risk insurance underwriter. Premiums for Gulf transit up {insurance_pct}%. Assessing {risk_assessment}.",
    AgentRole.COMMODITY_ANALYST: "Commodity analyst at {firm}. Covering {commodity}. Forecasting {forecast}. {years} years in markets.",
    # Media
    AgentRole.WAR_CORRESPONDENT: "War correspondent for {outlet}. Currently in {city}. Has covered {conflicts}. {years} years. Seeing {trauma_level} devastation.",
    AgentRole.STATE_TV_ANCHOR: "Anchor for {state_outlet}. Delivers {alignment} narrative. {years} years on air. Audience of {audience_size}.",
    AgentRole.INVESTIGATIVE_JOURNALIST: "Investigative journalist for {outlet}. Currently investigating {investigation}. Sources say {rumor}. {years} years experience.",
    AgentRole.SOCIAL_MEDIA_INFLUENCER: "{platform} influencer with {follower_count} followers. Posts about {beat}. Engagement rate high on {content_type}.",
    AgentRole.THINK_TANK_ANALYST: "Senior fellow at {think_tank}. Expert on {specialty}. Published {publication_count} papers on {topic}. Frequently consulted by {consulted_by}.",
    AgentRole.HISTORIAN: "Historian specializing in {history_period}. Professor at {university}. Author of books on {topic}. Sees parallels to {historical_parallel}.",
    AgentRole.FOREIGN_POLICY_SCHOLAR: "Foreign policy scholar at {institution}. Expert on {region}. Argues for {policy_position}. Published in {publication}.",
    AgentRole.OSINT_ANALYST: "Open-source intelligence analyst. Tracks satellite imagery, flight data, shipping movements. {years} years. Currently monitoring {focus}.",
    AgentRole.PROPAGANDA_OFFICER: "Information warfare officer. Creates and distributes {propaganda_type} content. {years} years in influence operations.",
    # Technical
    AgentRole.NUCLEAR_SCIENTIST: "Nuclear scientist at {facility}. {years} years in {nuclear_specialty}. Clearance: {clearance}. Assessment of program: {assessment}.",
    AgentRole.NUCLEAR_INSPECTOR: "IAEA inspector. {years} years. Last inspected {facility}. Findings: {findings}. Concerned about {concern}.",
    AgentRole.DESALINATION_ENGINEER: "Desalination plant engineer at {desal_plant}. {capacity} m³/day capacity. If this plant goes down, {impact}. Reserves: {reserves} days.",
    AgentRole.TELECOM_ENGINEER: "Telecom engineer managing {cable_name} submarine cable. Landing station at {landing_station}. If severed: {impact}.",
    AgentRole.CYBER_WARFARE_SPECIALIST: "Cyber warfare specialist in {cyber_unit}. {years} years. Capable of {cyber_capability}. Currently {cyber_mission}.",
    AgentRole.OIL_REFINERY_ENGINEER: "Refinery engineer at {refinery}. {capacity} bpd capacity. Damage assessment: {damage}. Repair timeline: {repair_time}.",
    AgentRole.MISSILE_ENGINEER: "Missile systems engineer. {years} years on {missile_program}. Technical assessment: {assessment}.",
    AgentRole.DRONE_OPERATOR: "Drone operator, {years} years. Flies {drone_type}. Has conducted {drone_missions} missions. Views targets through a screen from {location}.",
    # Civilian
    AgentRole.URBAN_CIVILIAN: "Lives in {city}. Works as {occupation}. Family of {family_size}. Primary concerns: {concerns}.",
    AgentRole.RURAL_CIVILIAN: "Lives in rural {region}. {occupation}. Family of {family_size}. Water supply: {water_status}. Food: {food_status}.",
    AgentRole.REFUGEE: "Displaced from {origin_city} due to {cause}. Now in {refugee_location}. Family: {family}. Needs: {needs}. Days displaced: {days_displaced}.",
    AgentRole.DOCTOR: "Doctor at {hospital}. Specialty: {medical_specialty}. Treating {patient_type}. {trauma_level} casualties daily. Supplies: {supply_status}.",
    AgentRole.NURSE: "Nurse at {hospital}. {years} years. Working {hours_per_day} hour shifts. Treating {patient_type}. Emotionally: {emotional_state}.",
    AgentRole.UNIVERSITY_PROFESSOR: "Professor of {major} at {university}. {years} years. Students: {student_concern}. Research: paused. Views: {war_stance}.",
    AgentRole.STUDENT_ACTIVIST: "Student activist at {university}. Organizing {activity}. Political leaning: {leaning}. Arrested {arrest_count} times. Social media following: {follower_count}.",
    AgentRole.STUDENT: "Student studying {major} at {university}. {student_concern}. Political leaning: {leaning}.",
    AgentRole.EXPAT_WORKER: "Expatriate from {origin} working in {host_country} as {occupation}. {years} years here. Family depends on remittances. Worried about {concern}.",
    AgentRole.TAXI_DRIVER: "Taxi driver in {city}. Hears everything from passengers. Fuel costs up {fuel_increase}%. Income down {income_decrease}%. {family_size} mouths to feed.",
    AgentRole.MARKET_VENDOR: "Market vendor in {city} selling {goods}. Prices up {price_increase}% this month. Customers buying only essentials. Worried about {concern}.",
    AgentRole.FACTORY_WORKER: "Factory worker at {factory_type} plant. {hours_per_day} hour shifts. Pay delayed {pay_delay} weeks. Union {union_status}.",
    AgentRole.FARMER: "Farmer in {region}. Grows {crop}. Water supply: {water_status}. Can't export due to {export_block}. Family of {family_size}.",
    AgentRole.TRIBAL_ELDER: "Tribal elder of the {tribe_name} tribe. {age} years old. {tribal_members} families under his authority. Views conflict as {war_view}.",
    AgentRole.HUMAN_RIGHTS_LAWYER: "Human rights lawyer, {years} years. Documenting {documentation}. Filed cases at {court}. Threatened {threat_count} times.",
    AgentRole.AID_WORKER: "Aid worker for {aid_org}. Currently in {city}. Managing {aid_type} distribution. Access: {access_level}. Seeing {trauma_level} conditions.",
    AgentRole.RED_CROSS_DELEGATE: "ICRC delegate, {years} years. Currently in {city}. Negotiating {current_work}. Neutral mandate. Documenting {documentation}.",
}

# Specialty pools for background generation
MILITARY_SPECIALTIES = ["armored warfare", "air defense", "missile systems", "cyber operations", "naval warfare", "special operations", "logistics", "intelligence", "electronic warfare", "drone warfare"]
MILITARY_BRANCHES = ["Army", "Navy", "Air Force", "Revolutionary Guards", "Special Forces", "Naval Infantry", "Missile Command", "Air Defense"]
ECONOMIC_CONCERNS = ["supply chain disruption", "energy price volatility", "currency devaluation", "trade route closure", "sanctions impact", "food price inflation", "insurance market stress", "sovereign debt risk"]
CIVILIAN_CONCERNS = ["family safety", "food prices", "water supply", "electricity reliability", "job security", "children's education", "medical access", "evacuation plans"]
STUDENT_MAJORS = ["political science", "engineering", "economics", "journalism", "computer science", "international relations", "medicine", "Islamic studies", "law", "business"]


def generate_population(
    countries: List[str],
    total_target: int = 100000,
    country_weights: Optional[Dict[str, float]] = None,
) -> List[AgentPersona]:
    """Generate a heterogeneous agent population across specified countries.

    Args:
        countries: List of country IDs (matching actors.json actor_ids)
        total_target: Target total population size
        country_weights: Optional weight per country (defaults to equal distribution)

    Returns:
        List of AgentPersona objects ready for simulation
    """
    if not country_weights:
        # Default weights: larger/more involved countries get more agents
        default_weights = {
            "usa": 1.5, "iran": 2.0, "israel": 1.2, "saudi_arabia": 1.0,
            "uae": 0.8, "qatar": 0.6, "hezbollah": 0.8, "houthis": 0.6,
            "russia": 0.7, "china": 0.7, "turkey": 0.5, "egypt": 0.5,
            "iraq_pmf": 0.5, "jordan": 0.3, "kuwait": 0.3,
        }
        country_weights = {c: default_weights.get(c, 0.5) for c in countries}

    # Normalize weights
    total_weight = sum(country_weights.get(c, 0.5) for c in countries)

    population = []
    agent_counter = 0

    for country in countries:
        weight = country_weights.get(country, 0.5)
        country_count = max(10, int(total_target * weight / total_weight))

        role_dist = COUNTRY_ROLE_DISTRIBUTIONS.get(country, DEFAULT_ROLE_DISTRIBUTION)
        dist_total = sum(role_dist.values())

        names = COUNTRY_NAMES.get(country, COUNTRY_NAMES["usa"])

        for role, role_count_per_1000 in role_dist.items():
            num_agents = max(1, int(country_count * role_count_per_1000 / dist_total))

            for i in range(num_agents):
                agent_counter += 1

                # Generate personality traits with role-appropriate ranges
                personality_range = ROLE_PERSONALITY_RANGES.get(role, _DEFAULT_PERSONALITY)
                # Unpack as (hawk_min, hawk_max, risk_min, risk_max, info_min, info_max, anal_min, anal_max)
                hawk = random.uniform(personality_range[0], personality_range[1])
                risk = random.uniform(personality_range[2], personality_range[3])
                info_trust = random.uniform(personality_range[4], personality_range[5]) if len(personality_range) > 5 else random.uniform(0.3, 0.7)
                analytical = random.uniform(personality_range[6], personality_range[7]) if len(personality_range) > 7 else random.uniform(0.4, 0.7)

                # Country-specific nationalism modifier
                nationalism_base = {
                    "iran": 0.7, "israel": 0.7, "usa": 0.5, "hezbollah": 0.8,
                    "houthis": 0.8, "saudi_arabia": 0.6, "russia": 0.6,
                }.get(country, 0.5)
                nationalism = min(1.0, max(0.0, nationalism_base + random.uniform(-0.2, 0.2)))

                name = random.choice(names)
                agent_id = f"{country}_{role.value}_{agent_counter}"

                # Generate background
                background = _generate_background(role, country, i)

                persona = AgentPersona(
                    agent_id=agent_id,
                    agent_name=f"{name} ({role.value.replace('_', ' ').title()})",
                    country=country,
                    role=role,
                    hawkishness=round(hawk, 2),
                    risk_tolerance=round(risk, 2),
                    information_trust=round(info_trust, 2),
                    analytical_depth=round(analytical, 2),
                    emotional_reactivity=round(random.uniform(0.2, 0.8), 2),
                    nationalism=round(nationalism, 2),
                    information_access=ROLE_INFO_ACCESS.get(role, "public"),
                    influence_radius=ROLE_INFLUENCE.get(role, 10),
                    credibility=ROLE_CREDIBILITY.get(role, 0.3),
                    current_sentiment=round(random.uniform(-0.5, 0.5), 2),
                    stress_level=round(random.uniform(0.0, 0.5), 2),
                    background=background,
                )
                population.append(persona)

    logger.info("Generated population: %d agents across %d countries", len(population), len(countries))
    return population


def _generate_background(role: AgentRole, country: str, index: int) -> str:
    """Generate a short background string for an agent."""
    template = ROLE_BACKGROUNDS.get(role, "Professional in {country}. Concerned about the current geopolitical situation.")

    # Fill in template with randomized but plausible values
    years = random.randint(3, 35)

    fill = {
        "years": years,
        "country": country.replace("_", " ").title(),
        "country_name": country.replace("_", " ").title(),
        "specialty": random.choice(MILITARY_SPECIALTIES),
        "branch": random.choice(MILITARY_BRANCHES),
        "experience": random.choice(["combat operations", "peacekeeping", "border defense", "coalition operations", "counterinsurgency", "naval blockade"]),
        "perspective": random.choice(["strategic deterrence", "force projection", "homeland defense", "asymmetric warfare", "combined arms", "missile defense"]),
        "location": random.choice(["forward operating base", "headquarters", "training facility", "border region", "naval base", "air base", "underground command post"]),
        "responsibility": random.choice(["unit readiness", "logistics", "intelligence briefings", "tactical planning", "force protection", "air defense", "special operations"]),
        "region": random.choice(["Middle East", "Persian Gulf", "Levant", "Central Asia", "Red Sea", "Mediterranean"]),
        "focus": random.choice(["missile capabilities", "proxy networks", "cyber threats", "nuclear proliferation", "naval movements", "air defense gaps", "supply routes", "underground facilities"]),
        "challenge": random.choice(["war fatigue", "coalition pressure", "domestic opposition", "economic strain", "casualty sensitivity", "election pressure", "sanctions bite"]),
        "domestic": random.choice(["political pressure", "public opinion", "economic concerns", "security demands", "protest movements", "media criticism"]),
        "international": random.choice(["alliance obligations", "UN pressure", "trade relationships", "military commitments", "sanctions enforcement", "humanitarian demands"]),
        "approval": random.randint(20, 70),
        "postings": random.choice(["Washington, Geneva", "Tehran, Ankara", "Riyadh, Cairo", "Beijing, Moscow", "London, Paris", "Beirut, Damascus", "Baghdad, Amman"]),
        "current_work": random.choice(["ceasefire negotiations", "sanctions enforcement", "humanitarian corridors", "hostage talks", "back-channel diplomacy", "coalition coordination"]),
        "firm": random.choice(["Goldman Sachs", "Vitol", "Trafigura", "local trading desk", "sovereign wealth fund", "Morgan Stanley", "BP Trading", "Glencore"]),
        "portfolio": f"{random.randint(10, 500)}M",
        "indicators": random.choice(["Hormuz transit rates", "tanker insurance premiums", "OPEC signals", "strategic reserve levels", "VIX spikes", "defense stock moves"]),
        "institution": random.choice(["central bank", "IMF", "World Bank", "university", "private consultancy", "Chatham House", "RAND Corporation", "Brookings"]),
        "concern": random.choice(ECONOMIC_CONCERNS),
        "topic": random.choice(["sanctions economics", "oil market dynamics", "war economics", "trade disruption", "conflict termination", "nuclear deterrence"]),
        "outlet": random.choice(["BBC", "CNN", "Al Jazeera", "Reuters", "AP", "IRNA", "TASS", "Xinhua", "Haaretz", "NYT", "Washington Post"]),
        "conflicts": random.choice(["Syria, Iraq, Yemen", "Afghanistan, Libya", "Ukraine, Gaza", "Lebanon, Sudan", "2006 Lebanon War", "Iraq War"]),
        "beat": random.choice(["defense", "politics", "foreign affairs", "economy", "human rights", "nuclear"]),
        "alignment": random.choice(["government narrative", "national interest", "revolutionary values", "state position", "regime messaging"]),
        "city": random.choice(["Tehran", "Tel Aviv", "Riyadh", "Dubai", "Doha", "Baghdad", "Beirut", "Cairo", "Amman", "Washington DC", "New York", "Moscow", "Beijing", "Ankara", "Kuwait City", "Sanaa"]),
        "occupation": random.choice(["teacher", "shop owner", "taxi driver", "office worker", "construction worker", "engineer", "nurse", "accountant"]),
        "family_size": random.randint(2, 8),
        "concerns": ", ".join(random.sample(CIVILIAN_CONCERNS, 3)),
        "origin": random.choice(["South Asia", "Southeast Asia", "East Africa", "Egypt", "Jordan", "Pakistan", "Philippines", "Bangladesh", "Nepal", "India"]),
        "host_country": country.replace("_", " ").title(),
        "title": random.choice(["Imam", "Sheikh", "Ayatollah", "Rabbi", "Pastor", "Cleric"]),
        "tradition": random.choice(["Sunni Islam", "Shia Islam", "Judaism", "Christianity", "interfaith"]),
        "size": random.choice(["hundreds", "thousands", "tens of thousands"]),
        "lens": random.choice(["moral duty", "divine justice", "peace imperative", "just war doctrine", "biblical prophecy", "revolutionary Islam"]),
        "community": random.choice(["local community", "diaspora networks", "online following", "tribal networks"]),
        "facility": random.choice(["Natanz", "Fordow", "Dimona", "Bushehr", "research lab", "Isfahan", "Parchin"]),
        "clearance": random.choice(["top secret", "secret", "confidential", "TS/SCI"]),
        "capacity": random.choice(["500,000", "1,000,000", "200,000", "800,000"]),
        "vulnerability": random.choice(["power grid dependency", "intake pipe exposure", "chemical supply chain", "spare parts shortage"]),
        "major": random.choice(STUDENT_MAJORS),
        "university": random.choice(["Tehran University", "Tel Aviv University", "Georgetown", "King Saud University", "AUB", "Cairo University", "Sharif University", "Hebrew University", "MIT", "Oxford"]),
        "leaning": random.choice(["reformist", "conservative", "progressive", "nationalist", "apolitical", "revolutionary"]),
        "activity": random.choice(["protests", "student government", "online activism", "volunteer work", "debate clubs", "hunger strikes"]),
        "cause": random.choice(["airstrikes", "economic collapse", "sectarian violence", "infrastructure destruction"]),
        "family": random.choice(["separated from family", "traveling with children", "alone", "with elderly parents"]),
        "needs": random.choice(["shelter, food, medical care", "documentation, work permit", "family reunification", "psychological support"]),
        "role": random.choice(["surgeon", "nurse", "paramedic", "emergency physician"]),
        "hospital": random.choice(["central hospital", "field hospital", "refugee clinic", "military hospital"]),
        "patient_type": random.choice(["blast injuries", "burn victims", "displaced civilians", "combat casualties", "chemical exposure"]),
        "trauma_level": random.choice(["severe", "moderate", "overwhelming", "manageable"]),
        # New keys for expanded roles
        "facility_cia": random.choice(["Langley HQ", "CENTCOM fusion center", "Doha station", "Amman station"]),
        "pentagon_office": random.choice(["the Secretary of Defense", "CENTCOM J2", "the Joint Staff", "Policy (OSD-P)", "ISA"]),
        "nsa_target": random.choice(["IRGC", "Hezbollah", "Syrian", "Russian military", "Chinese naval"]),
        "command": random.choice(["CENTCOM forces", "theater air operations", "naval task force", "ground forces", "joint special operations"]),
        "unit_type": random.choice(["brigade combat team", "battalion", "air wing", "naval squadron", "special operations group"]),
        "naval_unit": random.choice(["carrier strike group", "destroyer squadron", "submarine flotilla", "patrol boat squadron", "coastal defense battery"]),
        "naval_area": random.choice(["Strait of Hormuz", "Persian Gulf", "Red Sea", "Eastern Mediterranean", "Arabian Sea"]),
        "air_ops": random.choice(["air superiority", "close air support", "strategic bombing", "ISR", "drone strike"]),
        "air_missions": random.randint(5, 50),
        "missile_type": random.choice(["Patriot", "THAAD", "Arrow-3", "S-300", "Sejjil", "Shahab-3", "Fateh-110"]),
        "readiness": random.choice(["high alert", "ready to fire", "partial readiness", "maintenance stand-down"]),
        "sf_unit": random.choice(["SEAL Team 6", "Delta Force", "Sayeret Matkal", "Shayetet 13", "Quds Force", "IRGC Saberin"]),
        "enlisted_rank": random.choice(["Private", "Corporal", "Sergeant", "Staff Sergeant", "PFC"]),
        "morale": random.choice(["high", "declining", "fragile", "strong", "mixed"]),
        "concerns_mil": random.choice(["family back home", "running out of ammo", "IEDs", "friendly fire", "no clear mission", "being captured"]),
        "irgc_unit": random.choice(["Khatam al-Anbiya", "Tharallah", "Fajr Corps", "Saheb al-Amr", "Beit al-Moqaddas"]),
        "proxy_group": random.choice(["Hezbollah", "Iraqi PMF", "Houthis", "Palestinian Islamic Jihad", "Afghan Fatemiyoun"]),
        "idf_unit": random.choice(["Golani Brigade", "Unit 8200", "Sayeret Matkal", "Maglan", "Shaldag", "Navy Shayetet 13"]),
        "conscript_months": random.randint(3, 24),
        "drone_type": random.choice(["MQ-9 Reaper", "Hermes 900", "Shahed-136", "Mohajer-6", "Bayraktar TB2"]),
        "drone_missions": random.randint(10, 500),
        "moral_dilemma": random.choice(["civilian casualties", "proportionality of force", "killing from a distance", "sanctity of life vs duty"]),
        "election_pressure": random.choice(["high — election year", "moderate — midterms distant", "low — no elections soon", "extreme — campaign in crisis"]),
        "coalition_size": random.randint(2, 6),
        "red_line": random.choice(["regime change", "nuclear capability", "territorial integrity", "Jerusalem", "oil access"]),
        "reform_agenda": random.choice(["Vision 2030 modernization", "economic diversification", "military reform", "diplomatic realignment"]),
        "dependency": random.choice(["LNG exports", "US security umbrella", "desalinated water", "food imports", "migrant labor"]),
        "reports_to": random.choice(["the President", "the Prime Minister", "the Supreme Leader", "the King", "the Crown Prince"]),
        "counterparts": random.choice(["US, EU, and Arab counterparts", "P5 foreign ministers", "Gulf state counterparts", "NATO allies"]),
        "oil_price": random.randint(70, 140),
        "oil_direction": random.choice(["and rising", "and volatile", "but falling", "and stable"]),
        "currency_pressure": random.choice(["severe devaluation pressure", "moderate stress", "capital flight", "sanctions-driven collapse"]),
        "energy_challenge": random.choice(["production cuts", "refinery damage", "export disruption", "tanker insurance crisis"]),
        "production_level": random.choice(["full capacity", "70% capacity", "emergency reduced", "sanctions-limited"]),
        "party": random.choice(["R-TX", "D-CA", "R-FL", "D-NY", "R-OH", "D-MI", "I-VT"]),
        "committee": random.choice(["Armed Services", "Foreign Relations", "Intelligence", "Appropriations"]),
        "constituent_mood": random.choice(["war-weary", "hawkish", "divided", "anxious about gas prices", "demanding action"]),
        "war_stance": random.choice(["hawkish", "dovish", "cautiously supportive", "opposed", "calling for restraint"]),
        "district_type": random.choice(["military-heavy", "suburban swing", "rural", "urban coastal", "border"]),
        "posted_to": random.choice(["Washington", "Tehran", "Riyadh", "Beijing", "Moscow", "UN New York", "London"]),
        "diplomatic_message": random.choice(["ceasefire demands", "sanctions warnings", "alliance reassurance", "humanitarian access requests"]),
        "advises": random.choice(["the President", "the Prime Minister", "the Defense Minister", "the Crown Prince", "the Supreme Leader"]),
        "frustration": random.choice(["both sides refusing to talk", "spoiler attacks", "lack of international consensus", "humanitarian access blocked"]),
        "mosque": random.choice(["Grand", "Central", "Al-Aqsa", "Imam Reza", "Jameh"]),
        "fatwa_topic": random.choice(["self-defense", "nuclear weapons", "targeting civilians", "jihad", "peace negotiations"]),
        "war_view": random.choice(["divine test", "necessary defense", "sinful aggression", "just war", "apocalyptic sign"]),
        "message": random.choice(["patience and faith", "resistance", "peace and reconciliation", "obedience to authority", "justice for the oppressed"]),
        "guidance_type": random.choice(["moral guidance", "practical survival", "political direction", "spiritual comfort"]),
        "oil_balance": random.choice(["revenue maximization vs market stability", "Saudi-Iran rivalry", "US pressure vs OPEC unity"]),
        "oil_target": random.randint(70, 120),
        "swf_aum": random.randint(50, 900),
        "war_scenario": random.choice(["extended conflict", "quick resolution", "escalation to regional war", "nuclear threshold"]),
        "forecast": random.choice(["recession in 6 months", "oil at $150 by Q3", "GCC GDP contraction", "shipping rates +500%", "global inflation spike"]),
        "sanctions_target": random.choice(["Iran IRGC", "Russian energy", "Hezbollah financial", "North Korea", "Iran central bank"]),
        "shipping_company": random.choice(["Maersk", "MSC", "CMA CGM", "Hapag-Lloyd", "regional Gulf carrier"]),
        "fleet_size": random.randint(10, 200),
        "chokepoint": random.choice(["Hormuz", "Bab el-Mandeb", "Suez", "all three chokepoints"]),
        "insurance_pct": random.randint(100, 1000),
        "defense_company": random.choice(["Lockheed Martin", "Raytheon", "Northrop Grumman", "General Dynamics", "BAE Systems", "Rafael", "Elbit", "IAI"]),
        "stock_change": random.randint(5, 40),
        "product": random.choice(["Patriot missiles", "Iron Dome interceptors", "F-35 parts", "precision munitions", "JDAM kits"]),
        "risk_assessment": random.choice(["total loss risk for Gulf-transiting vessels", "war risk premium calculations", "force majeure claims"]),
        "commodity": random.choice(["crude oil", "natural gas", "wheat", "gold", "shipping futures"]),
        "state_outlet": random.choice(["IRNA", "Press TV", "Al Arabiya", "RT", "CGTN", "TRT", "Al Mayadeen"]),
        "audience_size": random.choice(["millions", "tens of millions", "hundreds of thousands"]),
        "investigation": random.choice(["civilian casualties", "weapons transfers", "war profiteering", "intelligence failures", "banned weapons use"]),
        "rumor": random.choice(["back-channel talks are underway", "a major offensive is planned", "nuclear threshold has been crossed", "ceasefire deal is close"]),
        "platform": random.choice(["Twitter/X", "Telegram", "Instagram", "TikTok", "YouTube"]),
        "follower_count": random.choice(["50K", "200K", "1M", "5M", "10M"]),
        "content_type": random.choice(["breaking news threads", "analysis threads", "emotional appeals", "memes and satire", "leaked documents"]),
        "think_tank": random.choice(["RAND Corporation", "Brookings", "CSIS", "Chatham House", "IISS", "Carnegie", "Hudson Institute", "WINEP", "Belfer Center"]),
        "publication_count": random.randint(5, 50),
        "consulted_by": random.choice(["the White House", "Congressional committees", "Pentagon", "State Department", "media"]),
        "history_period": random.choice(["20th century Middle East", "Iran-Iraq War", "Cold War proxy conflicts", "Ottoman decline", "Crusades", "Persian Empire"]),
        "historical_parallel": random.choice(["1973 Yom Kippur War", "Cuban Missile Crisis", "Gulf War 1991", "Iran-Iraq War", "Suez Crisis 1956"]),
        "policy_position": random.choice(["strategic restraint", "maximum pressure", "diplomatic engagement", "regional containment", "offshore balancing"]),
        "publication": random.choice(["Foreign Affairs", "Foreign Policy", "The Economist", "RUSI Journal", "Survival"]),
        "nuclear_specialty": random.choice(["uranium enrichment", "plutonium reprocessing", "centrifuge design", "weapons physics", "reactor engineering"]),
        "assessment": random.choice(["program advancing despite strikes", "set back 2-3 years", "breakout capability within months", "heavily damaged but recoverable"]),
        "findings": random.choice(["enrichment above declared levels", "new undeclared sites detected", "IAEA access restricted", "compliance with safeguards"]),
        "desal_plant": random.choice(["Jebel Ali", "Ras Al-Khair", "Umm Al Houl", "Fujairah", "Shoaiba", "Az-Zour", "Al-Dur"]),
        "reserves": random.randint(1, 5),
        "impact": random.choice(["3 million people lose water within 48 hours", "city water supply drops 60%", "hospitals lose sterile water", "emergency rationing begins"]),
        "cable_name": random.choice(["FLAG/FALCON", "SEA-ME-WE 5", "AAE-1", "EIG", "Gulf Bridge International"]),
        "landing_station": random.choice(["Fujairah", "Muscat", "Jeddah", "Mumbai", "Djibouti"]),
        "cyber_unit": random.choice(["US Cyber Command", "Unit 8200", "IRGC Cyber Corps", "NSA TAO", "GRU Unit 74455"]),
        "cyber_capability": random.choice(["critical infrastructure disruption", "financial system attacks", "communications interception", "SCADA system exploitation"]),
        "cyber_mission": random.choice(["defending national networks", "offensive operations against enemy C2", "monitoring adversary communications", "protecting financial systems"]),
        "refinery": random.choice(["Abqaiq", "Ras Tanura", "Ruwais", "Jubail", "Mina Al-Ahmadi", "Asaluyeh"]),
        "damage": random.choice(["30% capacity reduction from missile strikes", "minor damage, operational", "severe damage, offline", "undamaged but at risk"]),
        "repair_time": random.choice(["6-12 months", "2-3 months", "unknown — parts under sanctions", "already in progress"]),
        "missile_program": random.choice(["Sejjil-2", "Shahab-3", "Fateh-313", "Arrow-3", "David's Sling", "Iron Dome", "Patriot PAC-3"]),
        "water_status": random.choice(["intermittent", "rationed", "normal", "emergency reserves only", "trucked in"]),
        "food_status": random.choice(["prices doubled", "shortages of basics", "stable but expensive", "aid-dependent", "subsistence only"]),
        "origin_city": random.choice(["Tehran", "Beirut", "Sanaa", "Damascus", "Aleppo", "Gaza", "southern Lebanon"]),
        "refugee_location": random.choice(["refugee camp", "relative's house", "border crossing", "UN shelter", "makeshift camp"]),
        "days_displaced": random.randint(3, 180),
        "medical_specialty": random.choice(["trauma surgery", "burns", "orthopedics", "emergency medicine", "pediatrics"]),
        "supply_status": random.choice(["critically low", "adequate for now", "running out of blood products", "no anesthetics left"]),
        "hours_per_day": random.randint(12, 20),
        "emotional_state": random.choice(["exhausted but determined", "breaking down", "numb", "angry at leadership", "focused on patients"]),
        "student_concern": random.choice(["campus closed", "drafted classmates", "future destroyed", "research abandoned", "cannot graduate"]),
        "arrest_count": random.randint(0, 5),
        "fuel_increase": random.randint(20, 200),
        "income_decrease": random.randint(30, 80),
        "goods": random.choice(["fruits and vegetables", "electronics", "clothing", "bread and grain", "household goods"]),
        "price_increase": random.randint(20, 150),
        "factory_type": random.choice(["textile", "food processing", "automotive parts", "electronics assembly", "petrochemical"]),
        "pay_delay": random.randint(1, 8),
        "union_status": random.choice(["active", "banned", "weak", "striking"]),
        "crop": random.choice(["wheat", "rice", "dates", "pistachios", "saffron", "olives"]),
        "export_block": random.choice(["port closure", "sanctions", "shipping insurance costs", "road damage"]),
        "tribe_name": random.choice(["Bakhtiari", "Qashqai", "Shammar", "Aniza", "Hashid", "Zaidi"]),
        "age": random.randint(55, 85),
        "tribal_members": random.randint(50, 5000),
        "documentation": random.choice(["war crimes", "civilian targeting", "illegal detention", "use of cluster munitions", "forced displacement"]),
        "court": random.choice(["ICC", "ICJ", "national courts", "military tribunal"]),
        "threat_count": random.randint(0, 10),
        "aid_org": random.choice(["MSF", "UNHCR", "WFP", "ICRC", "Save the Children", "Oxfam"]),
        "aid_type": random.choice(["food", "medical supplies", "water purification", "shelter", "child protection"]),
        "access_level": random.choice(["restricted", "partial", "denied in some areas", "negotiated access"]),
        "position": random.choice(["long Brent", "short WTI", "long gold hedge", "spread trade", "options straddle"]),
    }

    try:
        return template.format(**fill)
    except (KeyError, IndexError):
        return f"{role.value.replace('_', ' ').title()} from {country.replace('_', ' ').title()}"


def get_agents_by_role(population: List[AgentPersona], role: AgentRole) -> List[AgentPersona]:
    """Filter population by role."""
    return [a for a in population if a.role == role]


def get_agents_by_country(population: List[AgentPersona], country: str) -> List[AgentPersona]:
    """Filter population by country."""
    return [a for a in population if a.country == country]


def get_high_influence_agents(population: List[AgentPersona], top_n: int = 100) -> List[AgentPersona]:
    """Get the most influential agents (leaders, media, generals)."""
    return sorted(population, key=lambda a: a.influence_radius * a.credibility, reverse=True)[:top_n]


def population_summary(population: List[AgentPersona]) -> Dict[str, Any]:
    """Generate summary statistics for a population."""
    countries = {}
    roles = {}
    for a in population:
        countries[a.country] = countries.get(a.country, 0) + 1
        roles[a.role.value] = roles.get(a.role.value, 0) + 1

    return {
        "total_agents": len(population),
        "countries": len(countries),
        "country_counts": dict(sorted(countries.items(), key=lambda x: -x[1])),
        "role_counts": dict(sorted(roles.items(), key=lambda x: -x[1])),
        "avg_hawkishness": sum(a.hawkishness for a in population) / max(len(population), 1),
        "avg_risk_tolerance": sum(a.risk_tolerance for a in population) / max(len(population), 1),
    }
