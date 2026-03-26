<template>
  <div class="workspace">
    <!-- Header -->
    <header class="ws-header">
      <div class="header-left">
        <div class="brand" @click="router.push('/')">
          <span class="brand-mark">F8</span>
          <span class="brand-text">FORS8</span>
        </div>
      </div>

      <div class="header-center">
        <nav class="tab-rail">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: viewMode === tab.key }"
            @click="viewMode = tab.key"
          >
            <span class="tab-icon" v-html="tab.icon"></span>
            <span class="tab-label">{{ tab.label }}</span>
          </button>
        </nav>
      </div>

      <div class="header-right">
        <div class="step-pill">
          <span class="step-num">{{ currentStep }}/5</span>
          <span class="step-name">{{ stepNames[currentStep - 1] }}</span>
        </div>
        <span class="status-badge" :class="statusClass">
          <span class="status-dot"></span>
          {{ statusText }}
        </span>
      </div>
    </header>

    <!-- Content -->
    <main class="ws-content">
      <!-- Graph Panel -->
      <div class="panel panel-graph" :class="{ hidden: !showGraph, half: viewMode === 'split' }">
        <GraphPanel
          :graphData="graphData"
          :loading="graphLoading"
          :currentPhase="currentPhase"
          :isSimulating="isProjectMode && currentStep === 3 && projectStatus === 'processing'"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <div v-if="viewMode === 'split'" class="panel-divider"></div>

      <!-- Main Panel -->
      <div class="panel panel-main" :class="{ hidden: viewMode === 'graph', half: viewMode === 'split' }">
        <Transition name="fade" mode="out-in">
          <!-- Project workflow mode -->
          <template v-if="isProjectMode && (viewMode === 'workbench' || viewMode === 'split')">
            <Step1GraphBuild
              v-if="currentStep === 1"
              key="step1"
              :currentPhase="currentPhase"
              :projectData="projectData"
              :ontologyProgress="ontologyProgress"
              :buildProgress="buildProgress"
              :graphData="graphData"
              :systemLogs="systemLogs"
              @next-step="handleNextStep"
            />
            <Step2EnvSetup
              v-else-if="currentStep === 2"
              key="step2"
              :projectData="projectData"
              :graphData="graphData"
              :systemLogs="systemLogs"
              @go-back="handleGoBack"
              @next-step="handleNextStep"
              @add-log="addLog"
            />
            <Step3Simulation
              v-else-if="currentStep === 3"
              key="step3"
              :simulationId="currentSimulationId"
              :maxRounds="simMaxRounds"
              :minutesPerRound="simMinutesPerRound"
              :projectData="projectData"
              :graphData="graphData"
              :systemLogs="systemLogs"
              @go-back="handleGoBack"
              @next-step="handleNextStep"
              @add-log="addLog"
              @update-status="updateProjectStatus"
            />
            <Step4Report
              v-else-if="currentStep === 4"
              key="step4"
              :reportId="currentReportId"
              :simulationId="currentSimulationId"
              :systemLogs="systemLogs"
              @add-log="addLog"
              @update-status="updateProjectStatus"
            />
            <Step5Interaction
              v-else-if="currentStep === 5"
              key="step5"
              :reportId="currentReportId"
              :simulationId="currentSimulationId"
              :systemLogs="systemLogs"
              @add-log="addLog"
              @update-status="updateProjectStatus"
            />
          </template>

          <!-- Prediction mode (existing behavior) -->
          <PredictionPanel
            v-else-if="!isProjectMode && (viewMode === 'workbench' || viewMode === 'split')"
            key="prediction"
            :predictionData="predictionData"
            :loading="isPredictionLoading"
            :loadingStage="loadingStage"
            :error="errorMessage"
            :conversationId="conversationId"
            @retry="retryPrediction"
            @switch-tab="(tab) => viewMode = tab"
            @conversation-created="(id) => conversationId = id"
          />
          <SettingsPanel v-else-if="viewMode === 'settings'" key="settings" />
          <ChatHistoryPanel v-else-if="viewMode === 'chat-history'" key="chat-history" @conversation-selected="onConversationSelected" />
        </Transition>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import GraphPanel from '../components/GraphPanel.vue'
import PredictionPanel from '../components/PredictionPanel.vue'
import ChatHistoryPanel from '../components/ChatHistoryPanel.vue'
import SettingsPanel from '../components/SettingsPanel.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import Step2EnvSetup from '../components/Step2EnvSetup.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import Step4Report from '../components/Step4Report.vue'
import Step5Interaction from '../components/Step5Interaction.vue'
import { generateOntology, getProject, buildGraph, getTaskStatus, getGraphData } from '../api/graph'
import { getSimulation, getSimulationConfig } from '../api/simulation'
import { getReport } from '../api/report'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'

const route = useRoute()
const router = useRouter()

const props = defineProps({
  predictionId: { type: String, default: '' },
  projectId: { type: String, default: '' },
  simulationId: { type: String, default: '' },
  reportId: { type: String, default: '' },
  initialStep: { type: Number, default: 0 },
  maxRounds: { type: Number, default: null }
})

// ─── Layout ───
const tabs = [
  { key: 'graph', label: 'Graph', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M6.5 7.5L11 16"/><path d="M17.5 7.5L13 16"/><path d="M7 6h10"/></svg>' },
  { key: 'split', label: 'Split', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="3" x2="12" y2="21"/></svg>' },
  { key: 'workbench', label: 'Workbench', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>' },
  { key: 'settings', label: 'Settings', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>' },
  { key: 'chat-history', label: 'History', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>' },
]

const viewMode = ref('workbench')
const showGraph = computed(() => viewMode.value === 'graph' || viewMode.value === 'split')

// ─── Mode Detection ───
const isProjectMode = computed(() => {
  return !!(props.projectId || props.simulationId || props.reportId)
})

// ─── Shared State ───
const currentStep = ref(1)
const stepNames = ['Graph Build', 'Environment', 'Simulation', 'Report', 'Interaction']
const graphData = ref(null)
const graphLoading = ref(false)
const currentPhase = ref(-1)

// ─── Project Workflow State ───
const currentProjectId = ref('')
const currentSimulationId = ref('')
const currentReportId = ref('')
const projectData = ref(null)
const ontologyProgress = ref(null)
const buildProgress = ref(null)
const systemLogs = ref([])
const projectLoading = ref(false)
const projectError = ref('')
const projectStatus = ref('initializing') // initializing | processing | completed | error | ready
const simMaxRounds = ref(null)
const simMinutesPerRound = ref(30)

let graphBuildPollTimer = null
let graphDataPollTimer = null

// ─── Prediction State ───
const predictionStatus = ref('pending')
const predictionData = ref(null)
const errorMessage = ref('')
const loadingStage = ref('')
const conversationId = ref('')

let predictionPollTimer = null
let predictionFetchFailCount = 0

// ─── Computed ───
const isPredictionLoading = computed(() => {
  const s = predictionStatus.value
  return s !== 'complete' && s !== 'error' && s !== 'failed' && !errorMessage.value
})

const statusClass = computed(() => {
  if (isProjectMode.value) {
    if (projectError.value || projectStatus.value === 'error') return 'error'
    if (projectStatus.value === 'completed' || projectStatus.value === 'ready') return 'complete'
    return 'active'
  }
  // Prediction mode
  if (errorMessage.value || predictionStatus.value === 'error' || predictionStatus.value === 'failed') return 'error'
  if (predictionStatus.value === 'complete') return 'complete'
  return 'active'
})

const statusText = computed(() => {
  if (isProjectMode.value) {
    if (projectError.value) return 'Error'
    if (projectStatus.value === 'completed' || projectStatus.value === 'ready') return 'Ready'
    if (currentStep.value === 1) {
      if (currentPhase.value === 1) return 'Building Graph'
      if (currentPhase.value === 0) return 'Generating Ontology'
      if (currentPhase.value >= 2) return 'Graph Ready'
      return 'Initializing'
    }
    if (currentStep.value === 2) return 'Environment Setup'
    if (currentStep.value === 3) return projectStatus.value === 'processing' ? 'Simulating' : 'Simulation'
    if (currentStep.value === 4) return projectStatus.value === 'processing' ? 'Generating Report' : 'Report'
    if (currentStep.value === 5) return 'Interaction'
    return 'Initializing'
  }
  // Prediction mode
  if (errorMessage.value) return 'Error'
  const map = { complete: 'Complete', failed: 'Failed', error: 'Failed', pending: 'Queued', queued: 'Queued', running: 'Simulating', simulating: 'Simulating', aggregating: 'Aggregating', answering: 'Generating', provisioning: 'GPU Starting', loading_model: 'Loading Model', building_graph: 'Building Graph', extracting_actors: 'Extracting Actors', scraping_data: 'Scraping Data' }
  return map[predictionStatus.value] || 'Initializing'
})

// ─── Layout Helpers ───
const toggleMaximize = () => { viewMode.value = viewMode.value === 'graph' ? 'split' : 'graph' }
const onConversationSelected = async (id) => {
  conversationId.value = id
  if (!id) return

  // Fetch the conversation to find the latest prediction_id
  try {
    const resp = await fetch(`/api/conversations/${id}`)
    if (!resp.ok) return
    const conv = await resp.json()
    const msgs = conv.messages || []

    // Find the latest message that has a prediction_id
    let latestPredictionId = null
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].prediction_id) {
        latestPredictionId = msgs[i].prediction_id
        break
      }
    }

    if (latestPredictionId) {
      // Fetch the prediction data
      const predResp = await fetch(`/api/predict/${latestPredictionId}`)
      if (!predResp.ok) return
      const data = await predResp.json()

      if (data.status === 'complete') {
        // Load completed prediction into the PredictionPanel
        predictionStatus.value = 'complete'
        errorMessage.value = ''
        predictionData.value = {
          question: data.question,
          prediction_id: data.prediction_id,
          outcomes: data.outcomes || {},
          actor_results: data.actor_results || {},
          answers: data.answers || {},
          gpu_cost: data.gpu_cost || 0,
          num_runs: data.num_runs || 0,
          num_agents: data.num_agents || 0,
          graph_id: data.graph_id || '',
          grounding_score: data.grounding_score,
          grounding_report: data.grounding_report,
          social_results: data.social_results,
          agent_decisions: data.agent_decisions,
          scenario_type: data.scenario_type,
        }
        currentStep.value = 5
        if (data.graph_id) {
          loadGraphForPrediction(data.graph_id)
          viewMode.value = 'split'  // Show graph + prediction side by side
        } else {
          viewMode.value = 'workbench'
        }
      } else if (data.status === 'failed' || data.status === 'error') {
        predictionStatus.value = 'error'
        errorMessage.value = data.error || 'Prediction failed.'
        predictionData.value = null
        viewMode.value = 'workbench'
      } else {
        // Still running — start polling for this prediction
        predictionStatus.value = data.status || 'pending'
        loadingStage.value = data.progress_message || ''
        predictionData.value = null
        errorMessage.value = ''
        stopPredictionPolling()
        predictionFetchFailCount = 0

        // Temporarily set predictionId-like behavior via direct polling
        const pollExisting = async () => {
          try {
            const r = await fetch(`/api/predict/${latestPredictionId}`)
            if (!r.ok) { predictionFetchFailCount++; if (predictionFetchFailCount >= 5) { errorMessage.value = 'Server error.'; stopPredictionPolling() }; return }
            predictionFetchFailCount = 0
            const d = await r.json()
            predictionStatus.value = d.status || 'pending'
            loadingStage.value = d.progress_message || ''
            if (d.status === 'failed') { errorMessage.value = d.error || 'Failed.'; stopPredictionPolling() }
            if (d.status === 'complete') {
              predictionData.value = { question: d.question, prediction_id: d.prediction_id, outcomes: d.outcomes || {}, actor_results: d.actor_results || {}, answers: d.answers || {}, gpu_cost: d.gpu_cost || 0, num_runs: d.num_runs || 0, num_agents: d.num_agents || 0, graph_id: d.graph_id || '', grounding_score: d.grounding_score, grounding_report: d.grounding_report, social_results: d.social_results, agent_decisions: d.agent_decisions, scenario_type: d.scenario_type }
              if (d.graph_id) loadGraphForPrediction(d.graph_id)
              if (d.conversation_id) conversationId.value = d.conversation_id
              currentStep.value = 5
              stopPredictionPolling()
            }
          } catch (e) { predictionFetchFailCount++; if (predictionFetchFailCount >= 5) { errorMessage.value = 'Network error.'; stopPredictionPolling() } }
        }
        pollExisting()
        predictionPollTimer = setInterval(pollExisting, 2000)
        viewMode.value = 'workbench'
      }
    }
  } catch (e) {
    console.error('Failed to load conversation prediction:', e)
  }
}

// ═══════════════════════════════════════════════
// PROJECT WORKFLOW LOGIC
// ═══════════════════════════════════════════════

const addLog = (msg) => {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + new Date().getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg })
  if (systemLogs.value.length > 200) systemLogs.value.shift()
}

const updateProjectStatus = (status) => {
  projectStatus.value = status
}

const handleNextStep = (params = {}) => {
  if (currentStep.value < 5) {
    currentStep.value++
    addLog(`Entering Step ${currentStep.value}: ${stepNames[currentStep.value - 1]}`)
    if (currentStep.value === 3 && params.maxRounds) {
      addLog(`Custom simulation rounds: ${params.maxRounds} rounds`)
    }
  }
}

const handleGoBack = () => {
  if (currentStep.value > 1) {
    currentStep.value--
    addLog(`Returning to Step ${currentStep.value}: ${stepNames[currentStep.value - 1]}`)
  }
}

// ─── Project Init ───
const initProject = async () => {
  addLog('Project view initialized.')

  // Determine mode from props
  if (props.reportId) {
    // Step 4 or 5 — load from report
    currentReportId.value = props.reportId
    currentStep.value = props.initialStep || 4
    await loadFromReport(props.reportId)
  } else if (props.simulationId) {
    // Step 2 or 3 — load from simulation
    currentSimulationId.value = props.simulationId
    currentStep.value = props.initialStep || 2
    simMaxRounds.value = props.maxRounds
    await loadFromSimulation(props.simulationId)
  } else if (props.projectId) {
    // Step 1 — load or create project
    currentProjectId.value = props.projectId
    currentStep.value = props.initialStep || 1
    if (props.projectId === 'new') {
      await handleNewProject()
    } else {
      await loadProject()
    }
  }
}

const handleNewProject = async () => {
  const pending = getPendingUpload()
  if (!pending.isPending || (pending.files.length === 0 && !pending.simulationRequirement)) {
    projectError.value = 'No pending data found.'
    addLog('Error: No pending files or question found for new project.')
    return
  }

  try {
    projectLoading.value = true
    currentPhase.value = 0
    ontologyProgress.value = { message: 'Uploading and analyzing docs...' }
    addLog('Starting ontology generation: Uploading files...')

    const formData = new FormData()
    pending.files.forEach(f => formData.append('files', f))
    formData.append('simulation_requirement', pending.simulationRequirement)
    if (pending.mode) {
      formData.append('mode', pending.mode)
    }

    const res = await generateOntology(formData)
    if (res.success) {
      clearPendingUpload()
      currentProjectId.value = res.data.project_id
      projectData.value = res.data

      router.replace({ name: 'Process', params: { projectId: res.data.project_id } })
      ontologyProgress.value = null
      addLog(`Ontology generated successfully for project ${res.data.project_id}`)
      await startBuildGraph()
    } else {
      projectError.value = res.error || 'Ontology generation failed'
      addLog(`Error generating ontology: ${projectError.value}`)
    }
  } catch (err) {
    projectError.value = err.message
    addLog(`Exception in handleNewProject: ${err.message}`)
  } finally {
    projectLoading.value = false
  }
}

const loadProject = async () => {
  try {
    projectLoading.value = true
    addLog(`Loading project ${currentProjectId.value}...`)
    const res = await getProject(currentProjectId.value)
    if (res.success) {
      projectData.value = res.data
      updatePhaseByStatus(res.data.status)
      addLog(`Project loaded. Status: ${res.data.status}`)

      if (res.data.status === 'ontology_generated' && !res.data.graph_id) {
        await startBuildGraph()
      } else if (res.data.status === 'graph_building' && res.data.graph_build_task_id) {
        currentPhase.value = 1
        startPollingGraphBuildTask(res.data.graph_build_task_id)
        startGraphDataPolling()
      } else if (res.data.status === 'graph_completed' && res.data.graph_id) {
        currentPhase.value = 2
        await loadGraph(res.data.graph_id)
      }
    } else {
      projectError.value = res.error
      addLog(`Error loading project: ${res.error}`)
    }
  } catch (err) {
    projectError.value = err.message
    addLog(`Exception in loadProject: ${err.message}`)
  } finally {
    projectLoading.value = false
  }
}

const updatePhaseByStatus = (status) => {
  switch (status) {
    case 'created':
    case 'ontology_generated': currentPhase.value = 0; break
    case 'graph_building': currentPhase.value = 1; break
    case 'graph_completed': currentPhase.value = 2; break
    case 'failed': projectError.value = 'Project failed'; break
  }
}

// ─── Graph Build ───
const startBuildGraph = async () => {
  try {
    currentPhase.value = 1
    buildProgress.value = { progress: 0, message: 'Starting build...' }
    addLog('Initiating graph build...')

    const res = await buildGraph({ project_id: currentProjectId.value })
    if (res.success) {
      addLog(`Graph build task started. Task ID: ${res.data.task_id}`)
      startGraphDataPolling()
      startPollingGraphBuildTask(res.data.task_id)
    } else {
      projectError.value = res.error
      addLog(`Error starting build: ${res.error}`)
    }
  } catch (err) {
    projectError.value = err.message
    addLog(`Exception in startBuildGraph: ${err.message}`)
  }
}

const startGraphDataPolling = () => {
  stopGraphDataPolling()
  addLog('Started polling for graph data...')
  fetchGraphDataForProject()
  graphDataPollTimer = setInterval(fetchGraphDataForProject, 10000)
}

const fetchGraphDataForProject = async () => {
  try {
    const projRes = await getProject(currentProjectId.value)
    if (projRes.success && projRes.data.graph_id) {
      const gRes = await getGraphData(projRes.data.graph_id)
      if (gRes.success) {
        graphData.value = gRes.data
        const nodeCount = gRes.data.node_count || gRes.data.nodes?.length || 0
        const edgeCount = gRes.data.edge_count || gRes.data.edges?.length || 0
        addLog(`Graph data refreshed. Nodes: ${nodeCount}, Edges: ${edgeCount}`)
      }
    }
  } catch (err) {
    console.warn('Graph fetch error:', err)
  }
}

const startPollingGraphBuildTask = (taskId) => {
  stopGraphBuildPolling()
  pollGraphBuildTask(taskId)
  graphBuildPollTimer = setInterval(() => pollGraphBuildTask(taskId), 2000)
}

const pollGraphBuildTask = async (taskId) => {
  try {
    const res = await getTaskStatus(taskId)
    if (res.success) {
      const task = res.data
      if (task.message && task.message !== buildProgress.value?.message) {
        addLog(task.message)
      }
      buildProgress.value = { progress: task.progress || 0, message: task.message }

      if (task.status === 'completed') {
        addLog('Graph build task completed.')
        stopGraphBuildPolling()
        stopGraphDataPolling()
        currentPhase.value = 2

        const projRes = await getProject(currentProjectId.value)
        if (projRes.success && projRes.data.graph_id) {
          projectData.value = projRes.data
          await loadGraph(projRes.data.graph_id)
        }
      } else if (task.status === 'failed') {
        stopGraphBuildPolling()
        projectError.value = task.error
        addLog(`Graph build task failed: ${task.error}`)
      }
    }
  } catch (e) {
    console.error(e)
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  addLog(`Loading full graph data: ${graphId}`)
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog('Graph data loaded successfully.')
    } else {
      addLog(`Failed to load graph data: ${res.error}`)
    }
  } catch (e) {
    addLog(`Exception loading graph: ${e.message}`)
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (isProjectMode.value) {
    if (projectData.value?.graph_id) {
      addLog('Manual graph refresh triggered.')
      loadGraph(projectData.value.graph_id)
    }
  } else {
    if (predictionData.value?.graph_id) loadGraphForPrediction(predictionData.value.graph_id)
  }
}

const stopGraphBuildPolling = () => {
  if (graphBuildPollTimer) { clearInterval(graphBuildPollTimer); graphBuildPollTimer = null }
}

const stopGraphDataPolling = () => {
  if (graphDataPollTimer) {
    clearInterval(graphDataPollTimer); graphDataPollTimer = null
    addLog('Graph polling stopped.')
  }
}

// ─── Load from Simulation (Step 2/3) ───
const loadFromSimulation = async (simulationId) => {
  try {
    addLog(`Loading simulation data: ${simulationId}`)
    const simRes = await getSimulation(simulationId)
    if (simRes.success && simRes.data) {
      const simData = simRes.data

      // Load simulation config for minutes_per_round
      try {
        const configRes = await getSimulationConfig(simulationId)
        if (configRes.success && configRes.data?.time_config?.minutes_per_round) {
          simMinutesPerRound.value = configRes.data.time_config.minutes_per_round
          addLog(`Time config: ${simMinutesPerRound.value} minutes per round`)
        }
      } catch (configErr) {
        addLog(`Failed to load time config, using default: ${simMinutesPerRound.value}min/round`)
      }

      // Load project data
      if (simData.project_id) {
        currentProjectId.value = simData.project_id
        const projRes = await getProject(simData.project_id)
        if (projRes.success && projRes.data) {
          projectData.value = projRes.data
          addLog(`Project loaded: ${projRes.data.project_id}`)
          if (projRes.data.graph_id) {
            await loadGraph(projRes.data.graph_id)
            currentPhase.value = 2
          }
        }
      }
    } else {
      addLog(`Failed to load simulation: ${simRes.error || 'Unknown error'}`)
    }
  } catch (err) {
    addLog(`Exception loading simulation: ${err.message}`)
  }
}

// ─── Load from Report (Step 4/5) ───
const loadFromReport = async (reportId) => {
  try {
    addLog(`Loading report data: ${reportId}`)
    const reportRes = await getReport(reportId)
    if (reportRes.success && reportRes.data) {
      const reportData = reportRes.data
      if (reportData.simulation_id) {
        currentSimulationId.value = reportData.simulation_id

        const simRes = await getSimulation(reportData.simulation_id)
        if (simRes.success && simRes.data) {
          const simData = simRes.data
          if (simData.project_id) {
            currentProjectId.value = simData.project_id
            const projRes = await getProject(simData.project_id)
            if (projRes.success && projRes.data) {
              projectData.value = projRes.data
              addLog(`Project loaded: ${projRes.data.project_id}`)
              if (projRes.data.graph_id) {
                await loadGraph(projRes.data.graph_id)
                currentPhase.value = 2
              }
            }
          }
        }
      }
    } else {
      addLog(`Failed to load report: ${reportRes.error || 'Unknown error'}`)
    }
  } catch (err) {
    addLog(`Exception loading report: ${err.message}`)
  }
}

// ═══════════════════════════════════════════════
// PREDICTION LOGIC (existing, unchanged)
// ═══════════════════════════════════════════════

const retryPrediction = () => { errorMessage.value = ''; predictionStatus.value = 'pending'; predictionFetchFailCount = 0; startPredictionPolling() }

const fetchPrediction = async () => {
  if (!props.predictionId) return
  try {
    const resp = await fetch(`/api/predict/${props.predictionId}`)
    if (!resp.ok) {
      predictionFetchFailCount++
      if (resp.status === 404) { errorMessage.value = 'Prediction not found.'; stopPredictionPolling(); return }
      if (predictionFetchFailCount >= 5) { errorMessage.value = `Server error (HTTP ${resp.status})`; stopPredictionPolling() }
      return
    }
    predictionFetchFailCount = 0
    const data = await resp.json()
    predictionStatus.value = data.status || 'pending'
    loadingStage.value = data.progress_message || ''
    if (data.status === 'failed') { errorMessage.value = data.error || 'Prediction failed.'; stopPredictionPolling() }
    if (data.status === 'building_graph' || data.status === 'extracting_actors' || data.status === 'scraping_data') currentStep.value = 1
    else if (data.status === 'provisioning' || data.status === 'loading_model') currentStep.value = 2
    else if (data.status === 'simulating' || data.status === 'running') currentStep.value = 3
    else if (data.status === 'aggregating' || data.status === 'answering') currentStep.value = 4
    // Auto-load graph when graph_id becomes available (even before completion)
    // Periodically refresh graph data while prediction is in progress so edges
    // appear as Zep finishes processing episodes (edges are often not ready on
    // the first fetch right after the graph_id appears).
    if (data.graph_id) {
      const hasEdges = graphData.value?.edges?.length > 0
      if (!graphData.value || !hasEdges) {
        loadGraphForPrediction(data.graph_id)
      }
    }
    if (data.status === 'complete') {
      predictionData.value = { question: data.question, prediction_id: data.prediction_id, outcomes: data.outcomes || {}, actor_results: data.actor_results || {}, answers: data.answers || {}, gpu_cost: data.gpu_cost || 0, num_runs: data.num_runs || 0, num_agents: data.num_agents || 0, graph_id: data.graph_id || '', grounding_score: data.grounding_score, grounding_report: data.grounding_report, social_results: data.social_results, agent_decisions: data.agent_decisions, scenario_type: data.scenario_type }
      // Always reload graph data on completion — Zep may have finished
      // processing edges since the initial fetch during building_graph status.
      if (data.graph_id) loadGraphForPrediction(data.graph_id)
      if (data.conversation_id) conversationId.value = data.conversation_id
      currentStep.value = 5
      // Auto-switch to split view so both graph + prediction are visible
      viewMode.value = 'split'
      predictionStatus.value = 'complete'
      stopPredictionPolling()
    }
  } catch (e) { predictionFetchFailCount++; if (predictionFetchFailCount >= 5) { errorMessage.value = 'Network error.'; stopPredictionPolling() } }
}

const startPredictionPolling = () => { if (!props.predictionId) return; stopPredictionPolling(); fetchPrediction(); predictionPollTimer = setInterval(fetchPrediction, 2000) }
const stopPredictionPolling = () => { if (predictionPollTimer) { clearInterval(predictionPollTimer); predictionPollTimer = null } }

let _graphFetchInFlight = false
let _graphRetryTimer = null
const loadGraphForPrediction = async (graphId, retryCount = 0) => {
  // Prevent overlapping fetches from rapid polling
  if (_graphFetchInFlight) return
  _graphFetchInFlight = true
  graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      currentPhase.value = 2
      const nc = res.data.node_count || res.data.nodes?.length || 0
      const ec = res.data.edge_count || res.data.edges?.length || 0
      console.log(`[Prediction] Graph loaded: ${nc} nodes, ${ec} edges (graph_id=${graphId})`)

      // If we got nodes but zero edges, Zep is likely still processing.
      // Schedule a retry (up to 5 retries, backing off 3s → 6s → 12s → 24s → 48s).
      if (nc > 0 && ec === 0 && retryCount < 5) {
        const delay = 3000 * Math.pow(2, retryCount)
        console.log(`[Prediction] Nodes present but no edges — retrying in ${delay/1000}s (attempt ${retryCount + 1}/5)`)
        if (_graphRetryTimer) clearTimeout(_graphRetryTimer)
        _graphRetryTimer = setTimeout(() => loadGraphForPrediction(graphId, retryCount + 1), delay)
      }
    }
  } catch (err) { console.error('Graph load failed:', err) }
  finally { graphLoading.value = false; _graphFetchInFlight = false }
}

// ═══════════════════════════════════════════════
// LIFECYCLE
// ═══════════════════════════════════════════════

onMounted(() => {
  if (isProjectMode.value) {
    viewMode.value = 'split'
    initProject()
  } else if (props.predictionId) {
    // Fetch once immediately — if already complete, no need to poll
    fetchPrediction().then(() => {
      if (predictionStatus.value !== 'complete' && predictionStatus.value !== 'failed') {
        startPredictionPolling()
      }
    })
  }
})

onUnmounted(() => {
  stopPredictionPolling()
  stopGraphBuildPolling()
  stopGraphDataPolling()
  if (_graphRetryTimer) { clearTimeout(_graphRetryTimer); _graphRetryTimer = null }
})

// Watch prediction changes
watch(() => props.predictionId, (newId, oldId) => {
  if (newId && newId !== oldId) { stopPredictionPolling(); predictionStatus.value = 'pending'; predictionData.value = null; errorMessage.value = ''; predictionFetchFailCount = 0; startPredictionPolling() }
})

// Watch route changes for project workflow — when step components navigate
// to a new route (e.g., Step3 -> Report), we detect it here and update state
watch(() => route.name, (newName) => {
  if (!newName) return

  if (newName === 'Report' && route.params.reportId) {
    currentReportId.value = route.params.reportId
    currentStep.value = 4
    if (!currentSimulationId.value) {
      loadFromReport(route.params.reportId)
    }
  } else if (newName === 'Interaction' && route.params.reportId) {
    currentReportId.value = route.params.reportId
    currentStep.value = 5
    if (!currentSimulationId.value) {
      loadFromReport(route.params.reportId)
    }
  } else if (newName === 'SimulationRun' && route.params.simulationId) {
    currentSimulationId.value = route.params.simulationId
    currentStep.value = 3
    simMaxRounds.value = route.query.maxRounds ? parseInt(route.query.maxRounds) : simMaxRounds.value
  } else if (newName === 'Simulation' && route.params.simulationId) {
    currentSimulationId.value = route.params.simulationId
    currentStep.value = 2
  } else if ((newName === 'Process' || newName === 'Project') && route.params.projectId) {
    currentProjectId.value = route.params.projectId
    currentStep.value = 1
  }
})
</script>

<style scoped>

* { box-sizing: border-box; margin: 0; padding: 0; }

.workspace {
  --c-bg: #ffffff;
  --c-surface: #fafafa;
  --c-surface-2: #f4f4f5;
  --c-border: #e4e4e7;
  --c-border-subtle: #ebebef;
  --c-text: #18181b;
  --c-text-secondary: #52525b;
  --c-text-muted: #a1a1aa;
  --c-accent: #b8860b;
  --c-accent-bg: rgba(184, 134, 11, 0.08);
  --c-red: #dc2626;
  --c-green: #16a34a;
  --c-blue: #2563eb;
  --font: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono: 'IBM Plex Mono', 'SF Mono', 'Menlo', monospace;

  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg);
  color: var(--c-text);
  font-family: var(--font);
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
}

/* ── Header ── */
.ws-header {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--c-bg);
  border-bottom: 1px solid var(--c-border);
  flex-shrink: 0;
  z-index: 100;
}
.header-left { flex-shrink: 0; }
.header-center { position: absolute; left: 50%; transform: translateX(-50%); }
.header-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }

.brand { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.brand-mark {
  font-family: var(--mono); font-weight: 700; font-size: 12px;
  color: #fff; background: var(--c-text); padding: 2px 5px; border-radius: 3px; letter-spacing: 0.5px;
}
.brand-text { font-family: var(--mono); font-weight: 600; font-size: 13px; letter-spacing: 1.5px; color: var(--c-text-muted); }

/* Tab rail */
.tab-rail {
  display: flex; background: var(--c-surface-2); border: 1px solid var(--c-border);
  border-radius: 8px; padding: 3px; gap: 1px;
}
.tab-btn {
  display: flex; align-items: center; gap: 5px; border: none; background: transparent;
  padding: 5px 11px; font-family: var(--font); font-size: 12px; font-weight: 500;
  color: var(--c-text-muted); border-radius: 6px; cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.tab-btn:hover { color: var(--c-text-secondary); }
.tab-btn.active { background: var(--c-bg); color: var(--c-text); box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.tab-btn.active .tab-icon :deep(svg) { stroke: var(--c-accent); }
.tab-icon { display: flex; align-items: center; line-height: 0; }

.step-pill { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.step-num { font-family: var(--mono); font-weight: 600; color: var(--c-text-muted); font-size: 11px; }
.step-name { font-weight: 600; color: var(--c-text-secondary); }

.status-badge {
  display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 500;
  color: var(--c-text-muted); padding: 3px 10px 3px 8px; border-radius: 20px;
  border: 1px solid var(--c-border); background: var(--c-surface);
}
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--c-text-muted); }
.status-badge.active .status-dot { background: var(--c-accent); box-shadow: 0 0 6px var(--c-accent); animation: pulse 1.5s ease-in-out infinite; }
.status-badge.complete .status-dot { background: var(--c-green); }
.status-badge.error .status-dot { background: var(--c-red); }
@keyframes pulse { 50% { opacity: 0.4; } }

/* ── Content ── */
.ws-content { flex: 1; display: flex; overflow: hidden; }
.panel { height: 100%; overflow: hidden; transition: all 0.35s cubic-bezier(0.25, 0.8, 0.25, 1); will-change: width, opacity; }
.panel.hidden { width: 0 !important; opacity: 0; pointer-events: none; }
.panel.half { width: 50% !important; }
.panel-graph:not(.hidden):not(.half) { width: 100%; }
.panel-main:not(.hidden):not(.half) { width: 100%; }
.panel-divider { width: 1px; background: var(--c-border); flex-shrink: 0; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
