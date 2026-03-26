<template>
  <div class="page">
    <!-- Nav -->
    <nav class="nav">
      <router-link to="/" class="nav-brand">FORS8</router-link>
      <div class="nav-links">
        <router-link to="/settings" class="nav-link">Settings</router-link>
        <a href="https://github.com/666ghj/MiroFish" target="_blank" class="nav-link">GitHub <span class="arrow">↗</span></a>
      </div>
    </nav>

    <div class="content">
      <!-- Loading / Progress -->
      <section v-if="status !== 'complete' && status !== 'error'" class="progress-section">
        <h1 class="progress-title">Running Prediction</h1>
        <div class="stages">
          <div
            v-for="(stage, i) in stages"
            :key="i"
            class="stage"
            :class="{ active: i === currentStageIndex, done: i < currentStageIndex }"
          >
            <div class="stage-indicator">
              <div v-if="i < currentStageIndex" class="stage-check">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
              <div v-else-if="i === currentStageIndex" class="stage-spinner"></div>
              <div v-else class="stage-dot"></div>
            </div>
            <span class="stage-label">{{ stage.label }}</span>
          </div>
        </div>
        <div v-if="currentRound > 0 && status === 'running'" class="round-counter">
          Round {{ currentRound }} / 30
        </div>
      </section>

      <!-- Error -->
      <section v-if="status === 'error'" class="error-section">
        <h1 class="progress-title">Prediction Failed</h1>
        <p class="error-msg">{{ errorMessage || 'An unexpected error occurred.' }}</p>
        <router-link to="/" class="back-btn">Ask another question</router-link>
      </section>

      <!-- Results -->
      <section v-if="status === 'complete' && result" class="results-section">
        <!-- Original Question -->
        <div class="question-block">
          <div class="question-label">YOUR QUESTION</div>
          <h1 class="question-text">{{ result.question }}</h1>
        </div>

        <!-- Main Answer -->
        <div v-if="result.answers && result.answers.main_answer" class="card answer-card">
          <h2 class="card-title">Prediction</h2>
          <div class="main-answer" v-html="formatAnswer(result.answers.main_answer)"></div>
        </div>

        <!-- Outcome Probabilities -->
        <div v-if="result.outcomes && Object.keys(result.outcomes).length" class="card">
          <h2 class="card-title">Outcome Probabilities</h2>
          <div class="bar-chart">
            <div v-for="(prob, label) in result.outcomes" :key="label" class="bar-row">
              <div class="bar-label">{{ formatLabel(label) }}</div>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: (prob * 100) + '%' }"></div>
              </div>
              <div class="bar-value">{{ (prob * 100).toFixed(0) }}%</div>
            </div>
          </div>
        </div>

        <!-- Per-Actor Outcomes -->
        <div v-if="result.actor_results && Object.keys(result.actor_results).length" class="card">
          <h2 class="card-title">Actor Outcomes</h2>
          <div class="actors-table">
            <div class="actors-header">
              <span>Actor</span>
              <span>Force</span>
              <span>Casualties</span>
              <span>Approval</span>
            </div>
            <div v-for="(actor, id) in result.actor_results" :key="id" class="actors-row">
              <span class="actor-name">{{ actor.name || id }}</span>
              <span class="actor-stat">{{ actor.avg_final_force?.toFixed(0) || '—' }}/100</span>
              <span class="actor-stat">{{ actor.avg_casualties?.toLocaleString() || '0' }}</span>
              <span class="actor-stat">{{ actor.avg_approval ? (actor.avg_approval * 100).toFixed(0) + '%' : '—' }}</span>
            </div>
          </div>
        </div>

        <!-- Grounding Score -->
        <div v-if="result.grounding_score != null" class="card">
          <h2 class="card-title">Grounding Score</h2>
          <div class="grounding-display">
            <div class="grounding-value" :class="result.grounding_score >= 0.7 ? 'high' : result.grounding_score >= 0.4 ? 'mid' : 'low'">{{ (result.grounding_score * 100).toFixed(0) }}%</div>
            <div v-if="result.grounding_report" class="grounding-text" v-html="formatAnswer(result.grounding_report)"></div>
          </div>
        </div>

        <!-- Run Info -->
        <div class="card run-info">
          <span>{{ result.num_runs }} simulation runs</span>
          <span>{{ result.num_agents }} actors</span>
          <span v-if="result.gpu_cost">GPU cost: ${{ result.gpu_cost.toFixed(2) }}</span>
          <span v-if="result.scenario_type">{{ result.scenario_type }}</span>
        </div>

        <div class="actions">
          <router-link to="/" class="back-btn">Ask another question</router-link>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  predictionId: {
    type: String,
    required: true
  }
})

const status = ref('pending')
const result = ref(null)
const currentRound = ref(0)
const errorMessage = ref('')
const progressMessage = ref('')
const progressPct = ref(0)
let pollTimer = null

const stages = [
  { label: 'Connecting to GPU...', key: 'provisioning' },
  { label: 'Verifying model...', key: 'loading_model' },
  { label: 'Running simulation...', key: 'simulating' },
  { label: 'Aggregating results...', key: 'aggregating' },
  { label: 'Generating answer...', key: 'answering' },
  { label: 'Complete', key: 'complete' },
]

const stageKeyMap = {
  pending: 0,
  queued: 0,
  provisioning: 0,
  loading_model: 1,
  simulating: 2,
  running: 2,
  aggregating: 3,
  answering: 4,
  complete: 5,
  failed: -1,
  error: -1,
}

const currentStageIndex = computed(() => {
  return stageKeyMap[status.value] ?? 0
})

let fetchFailCount = 0
const MAX_FETCH_FAILURES = 5

const fetchStatus = async () => {
  try {
    const resp = await fetch(`/api/predict/${props.predictionId}`)

    if (!resp.ok) {
      fetchFailCount++
      if (resp.status === 404) {
        errorMessage.value = 'Prediction not found. It may have expired.'
        status.value = 'error'
        clearInterval(pollTimer)
        pollTimer = null
        return
      }
      if (fetchFailCount >= MAX_FETCH_FAILURES) {
        errorMessage.value = `Server error (HTTP ${resp.status}). Please try again later.`
        status.value = 'error'
        clearInterval(pollTimer)
        pollTimer = null
      }
      return
    }

    fetchFailCount = 0
    const data = await resp.json()

    status.value = data.status || 'pending'
    progressMessage.value = data.progress_message || ''
    progressPct.value = data.progress_pct || 0

    if (data.error && data.status === 'failed') {
      errorMessage.value = data.error
      status.value = 'error'
    }
    if (data.status === 'complete') {
      result.value = {
        question: data.question,
        outcomes: data.outcomes || {},
        actor_results: data.actor_results || {},
        answers: data.answers || {},
        gpu_cost: data.gpu_cost || 0,
        num_runs: data.num_runs || 0,
        num_agents: data.num_agents || 0,
        grounding_score: data.grounding_score,
        grounding_report: data.grounding_report,
        social_results: data.social_results,
        scenario_type: data.scenario_type,
      }
    }

    if (status.value === 'complete' || status.value === 'error') {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch (e) {
    console.error('Failed to fetch prediction status:', e)
    fetchFailCount++
    if (fetchFailCount >= MAX_FETCH_FAILURES) {
      errorMessage.value = 'Network error — unable to reach the server.'
      status.value = 'error'
      clearInterval(pollTimer)
      pollTimer = null
    }
  }
}

onMounted(() => {
  fetchStatus()
  pollTimer = setInterval(fetchStatus, 2000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

const formatLabel = (label) => {
  return label.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
}

const escapeHtml = (str) => {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

const formatAnswer = (text) => {
  if (!text) return ''
  const escaped = escapeHtml(text)
  return escaped.replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>')
}
</script>

<style scoped>

* { box-sizing: border-box; margin: 0; padding: 0; }

.page {
  min-height: 100vh;
  background: #fff;
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
  color: #111;
  -webkit-font-smoothing: antialiased;
}

/* Nav */
.nav {
  height: 52px;
  background: #111;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 36px;
}

.nav-brand {
  font-family: 'DM Mono', monospace;
  font-weight: 500;
  font-size: 13px;
  letter-spacing: 2px;
  color: #fff;
  text-decoration: none;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 32px;
}

.nav-link {
  color: rgba(255,255,255,0.65);
  text-decoration: none;
  font-size: 13px;
  font-weight: 400;
  transition: color 0.15s;
}
.nav-link:hover { color: #fff; }

.arrow { font-family: system-ui; }

/* Content */
.content {
  max-width: 780px;
  margin: 0 auto;
  padding: 0 32px;
}

/* Progress */
.progress-section {
  padding: 80px 0 40px;
  text-align: center;
}

.progress-title {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin-bottom: 40px;
}

.stages {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 340px;
  margin: 0 auto;
  text-align: left;
}

.stage {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #ccc;
  transition: color 0.3s;
}
.stage.active { color: #111; font-weight: 500; }
.stage.done { color: #888; }

.stage-indicator {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stage-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ddd;
}

.stage-check {
  color: #111;
  display: flex;
}

.stage-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid #ddd;
  border-top-color: #111;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.stage-label {
  font-size: 14px;
}

.round-counter {
  margin-top: 32px;
  font-family: 'DM Mono', monospace;
  font-size: 13px;
  color: #999;
}

/* Error */
.error-section {
  padding: 80px 0 40px;
  text-align: center;
}

.error-msg {
  color: #888;
  font-size: 15px;
  margin-bottom: 32px;
}

/* Results */
.results-section {
  padding: 56px 0 80px;
}

.question-block {
  margin-bottom: 40px;
}

.question-label {
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin-bottom: 10px;
}

.question-text {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
  line-height: 1.25;
}

/* Cards */
.card {
  border: 1px solid #eee;
  border-radius: 12px;
  padding: 28px;
  margin-bottom: 20px;
}

.card-title {
  font-size: 13px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin-bottom: 20px;
}

/* Bar Chart */
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bar-label {
  width: 200px;
  font-size: 14px;
  font-weight: 500;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 24px;
  background: #f5f5f5;
  border-radius: 6px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: #111;
  border-radius: 6px;
  transition: width 0.6s ease;
  min-width: 2px;
}

.bar-value {
  width: 44px;
  font-family: 'DM Mono', monospace;
  font-size: 13px;
  text-align: right;
  flex-shrink: 0;
  color: #555;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.stat-item {
  text-align: center;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
}

.stat-val {
  font-family: 'DM Mono', monospace;
  font-size: 22px;
  font-weight: 500;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 12px;
  color: #999;
}

/* Actors Table */
.actors-table {
  font-size: 14px;
}

.actors-header {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #eee;
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #999;
}

.actors-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #f5f5f5;
}

.actors-row:last-child { border-bottom: none; }

.actor-name { font-weight: 500; }
.actor-stat { font-family: 'DM Mono', monospace; color: #555; }

/* Grounding */
.grounding-display { display: flex; align-items: flex-start; gap: 16px; }
.grounding-value { font-family: 'DM Mono', monospace; font-size: 28px; font-weight: 600; flex-shrink: 0; }
.grounding-value.high { color: #16a34a; }
.grounding-value.mid { color: #d97706; }
.grounding-value.low { color: #dc2626; }
.grounding-text { font-size: 14px; color: #555; line-height: 1.65; }

/* QA */
.qa-block {
  padding: 16px 0;
  border-bottom: 1px solid #f5f5f5;
}
.qa-block:last-child { border-bottom: none; }

.qa-question {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 8px;
}

.qa-answer {
  font-size: 14px;
  color: #555;
  line-height: 1.65;
}

/* Actions */
.actions {
  margin-top: 40px;
  text-align: center;
}

.back-btn {
  display: inline-block;
  padding: 12px 28px;
  background: #111;
  color: #fff;
  text-decoration: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.15s;
}
.back-btn:hover { background: #333; }

/* Responsive */
@media (max-width: 768px) {
  .content { padding: 0 20px; }
  .bar-label { width: 120px; font-size: 12px; }
  .stats-grid { grid-template-columns: 1fr; }
  .question-text { font-size: 20px; }
}
</style>
