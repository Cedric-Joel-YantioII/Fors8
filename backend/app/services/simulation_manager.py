"""
Simulation Manager
Manages geopolitical conflict simulation with optional OASIS info warfare layer.
Uses LLM-driven profile generation and configurable consequence engine.
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .geopolitical_profile_generator import GeopoliticalProfileGenerator, GeopoliticalActorProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """模拟状态"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # 模拟被手动停止
    COMPLETED = "completed"  # 模拟自然完成
    FAILED = "failed"


class SimulationMode(str, Enum):
    """Simulation mode"""
    GEOPOLITICAL = "geopolitical"  # Geopolitical conflict simulation (default)
    SOCIAL_MEDIA = "social_media"  # Legacy OASIS social media simulation


@dataclass
class SimulationState:
    """Simulation state"""
    simulation_id: str
    project_id: str
    graph_id: str

    # Mode
    mode: SimulationMode = SimulationMode.GEOPOLITICAL

    # Platform enable (for OASIS info warfare layer)
    enable_twitter: bool = True
    enable_reddit: bool = True

    # Status
    status: SimulationStatus = SimulationStatus.CREATED

    # Preparation data
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)

    # Config generation
    config_generated: bool = False
    config_reasoning: str = ""

    # Runtime — geopolitical
    current_round: int = 0
    escalation_level: int = 5
    current_phase: str = "crisis"
    scenario_type: str = ""

    # Runtime — OASIS (info warfare layer)
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"

    # Dual-LLM mode
    dual_llm_enabled: bool = False

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Error
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "mode": self.mode.value,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "escalation_level": self.escalation_level,
            "current_phase": self.current_phase,
            "scenario_type": self.scenario_type,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "dual_llm_enabled": self.dual_llm_enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    def to_simple_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "mode": self.mode.value,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "escalation_level": self.escalation_level,
            "current_phase": self.current_phase,
            "error": self.error,
        }


class SimulationManager:
    """
    模拟管理器
    
    核心功能：
    1. 从Zep图谱读取实体并过滤
    2. 生成OASIS Agent Profile
    3. 使用LLM智能生成模拟配置参数
    4. 准备预设脚本所需的所有文件
    """
    
    # 模拟数据存储目录
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # 确保目录存在
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # 内存中的模拟状态缓存
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """获取模拟数据目录"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """保存模拟状态到文件"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """从文件加载模拟状态"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        mode_str = data.get("mode", "geopolitical")
        try:
            mode = SimulationMode(mode_str)
        except ValueError:
            mode = SimulationMode.GEOPOLITICAL

        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            mode=mode,
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            escalation_level=data.get("escalation_level", 5),
            current_phase=data.get("current_phase", "crisis"),
            scenario_type=data.get("scenario_type", ""),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            dual_llm_enabled=data.get("dual_llm_enabled", False),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        mode: str = "geopolitical",
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        dual_llm_enabled: bool = False,
        scenario_type: str = "",
    ) -> SimulationState:
        """
        Create a new simulation.

        Args:
            project_id: Project ID
            graph_id: Zep graph ID
            mode: "geopolitical" (default) or "social_media" (legacy)
            enable_twitter: Enable OASIS Twitter (info warfare layer)
            enable_reddit: Enable OASIS Reddit (info warfare layer)
            dual_llm_enabled: Use dual-LLM cross-validation (Mode B)
            scenario_type: Scenario template name (e.g., "iran_conflict")
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"

        sim_mode = SimulationMode(mode) if mode in [m.value for m in SimulationMode] else SimulationMode.GEOPOLITICAL

        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            mode=sim_mode,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            dual_llm_enabled=dual_llm_enabled,
            scenario_type=scenario_type,
            status=SimulationStatus.CREATED,
        )

        self._save_simulation_state(state)
        logger.info(f"Created simulation: {simulation_id}, mode={mode}, project={project_id}")

        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3
    ) -> SimulationState:
        """
        准备模拟环境（全程自动化）
        
        步骤：
        1. 从Zep图谱读取并过滤实体
        2. 为每个实体生成OASIS Agent Profile（可选LLM增强，支持并行）
        3. 使用LLM智能生成模拟配置参数（时间、活跃度、发言频率等）
        4. 保存配置文件和Profile文件
        5. 复制预设脚本到模拟目录
        
        Args:
            simulation_id: 模拟ID
            simulation_requirement: 模拟需求描述（用于LLM生成配置）
            document_text: 原始文档内容（用于LLM理解背景）
            defined_entity_types: 预定义的实体类型（可选）
            use_llm_for_profiles: 是否使用LLM生成详细人设
            progress_callback: 进度回调函数 (stage, progress, message)
            parallel_profile_count: 并行生成人设的数量，默认3
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            
            # ========== 阶段1: 读取并过滤实体 ==========
            if progress_callback:
                progress_callback("reading", 0, "正在连接Zep图谱...")
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, "正在读取节点数据...")
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            
            if progress_callback:
                progress_callback(
                    "reading", 100, 
                    f"完成，共 {filtered.filtered_count} 个实体",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "没有找到符合条件的实体，请检查图谱是否正确构建"
                self._save_simulation_state(state)
                return state
            
            # ========== Phase 2: Generate Actor Profiles ==========
            total_entities = len(filtered.entities)

            if progress_callback:
                progress_callback(
                    "generating_profiles", 0,
                    "Starting profile generation...",
                    current=0,
                    total=total_entities
                )

            if state.mode == SimulationMode.GEOPOLITICAL:
                # Geopolitical profile generation
                from zep_cloud.client import Zep
                zep_client = Zep(api_key=Config.ZEP_API_KEY) if Config.ZEP_API_KEY else None

                geo_generator = GeopoliticalProfileGenerator(
                    graph_id=state.graph_id,
                    zep_client=zep_client,
                )

                def profile_progress(current, total):
                    if progress_callback:
                        progress_callback(
                            "generating_profiles",
                            int(current / total * 100),
                            f"Profile {current}/{total}",
                            current=current,
                            total=total,
                        )

                geo_profiles = geo_generator.generate_profiles(
                    entities=filtered.entities,
                    simulation_requirement=simulation_requirement,
                    progress_callback=profile_progress,
                )

                state.profiles_count = len(geo_profiles)

                # Save geopolitical profiles as JSON
                profiles_path = os.path.join(sim_dir, "actor_profiles.json")
                profiles_data = [p.to_dict() for p in geo_profiles]
                with open(profiles_path, 'w', encoding='utf-8') as f:
                    json.dump(profiles_data, f, ensure_ascii=False, indent=2)

            else:
                # Legacy OASIS profile generation
                from .oasis_profile_generator import OasisProfileGenerator
                generator = OasisProfileGenerator(graph_id=state.graph_id)

                def profile_progress(current, total, msg):
                    if progress_callback:
                        progress_callback(
                            "generating_profiles",
                            int(current / total * 100),
                            msg,
                            current=current,
                            total=total,
                            item_name=msg
                        )

                realtime_output_path = None
                realtime_platform = "reddit"
                if state.enable_reddit:
                    realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                elif state.enable_twitter:
                    realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                    realtime_platform = "twitter"

                profiles = generator.generate_profiles_from_entities(
                    entities=filtered.entities,
                    use_llm=use_llm_for_profiles,
                    progress_callback=profile_progress,
                    graph_id=state.graph_id,
                    parallel_count=parallel_profile_count,
                    realtime_output_path=realtime_output_path,
                    output_platform=realtime_platform
                )

                state.profiles_count = len(profiles)

                if state.enable_reddit:
                    generator.save_profiles(
                        profiles=profiles,
                        file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                        platform="reddit"
                    )
                if state.enable_twitter:
                    generator.save_profiles(
                        profiles=profiles,
                        file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                        platform="twitter"
                    )

            if progress_callback:
                progress_callback(
                    "generating_profiles", 100,
                    f"Complete: {state.profiles_count} profiles",
                    current=state.profiles_count,
                    total=state.profiles_count
                )
            
            # ========== 阶段3: LLM智能生成模拟配置 ==========
            if progress_callback:
                progress_callback(
                    "generating_config", 0, 
                    "正在分析模拟需求...",
                    current=0,
                    total=3
                )
            
            config_generator = SimulationConfigGenerator()
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30, 
                    "正在调用LLM生成配置...",
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70, 
                    "正在保存配置文件...",
                    current=2,
                    total=3
                )
            
            # 保存配置文件
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())
            
            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100, 
                    "配置生成完成",
                    current=3,
                    total=3
                )
            
            # 注意：运行脚本保留在 backend/scripts/ 目录，不再复制到模拟目录
            # 启动模拟时，simulation_runner 会从 scripts/ 目录运行脚本
            
            # 更新状态
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"模拟准备完成: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"模拟准备失败: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """获取模拟状态"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """列出所有模拟"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # 跳过隐藏文件（如 .DS_Store）和非目录文件
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """获取模拟的Agent Profile"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """获取模拟配置"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """获取运行说明"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. 激活conda环境: conda activate MiroFish\n"
                f"2. 运行模拟 (脚本位于 {scripts_dir}):\n"
                f"   - 单独运行Twitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - 单独运行Reddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - 并行运行双平台: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
