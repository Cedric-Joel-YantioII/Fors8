<template>
  <div class="pred-panel">
    <!-- Loading (only show if we DON'T have data yet) -->
    <div v-if="loading && !hasData" class="state-overlay">
      <div class="loader-wrap">
        <div class="loader-ring"></div>
        <p class="loader-text">{{ loadingStage || 'Running prediction...' }}</p>
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="state-overlay">
      <div class="error-wrap">
        <div class="error-badge">!</div>
        <p class="error-msg">{{ error }}</p>
        <button class="btn-retry" @click="$emit('retry')">Retry</button>
      </div>
    </div>

    <!-- Empty -->
    <div v-else-if="!predictionData" class="state-overlay">
      <div class="empty-wrap">
        <p class="empty-title">No prediction loaded</p>
        <p class="empty-sub">Submit a question from the home page, or browse past predictions in the History tab.</p>
        <div class="empty-actions">
          <button class="btn-home" @click="$router.push('/')">Go to Home</button>
          <button class="btn-history" @click="$emit('switch-tab', 'chat-history')">View History</button>
        </div>
      </div>
    </div>

    <!-- Report + Chat Layout -->
    <div v-else class="layout">
      <!-- LEFT: Report -->
      <div class="col-report" ref="reportCol">
        <div class="report-inner">
          <!-- Header -->
          <header class="report-hdr">
            <div class="report-meta">
              <span class="tag">PREDICTION REPORT</span>
              <span class="mono id-tag" v-if="predictionData.prediction_id">{{ predictionData.prediction_id }}</span>
            </div>
            <h1 class="report-question">{{ predictionData.question || 'Untitled Prediction' }}</h1>
          </header>

          <!-- Main Answer -->
          <section v-if="mainAnswer" class="section">
            <div class="section-hdr">
              <span class="section-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>
              </span>
              <h2>Analysis</h2>
            </div>
            <div class="answer-body" v-html="formatAnswer(mainAnswer)"></div>
          </section>

          <!-- Outcome Probabilities -->
          <section v-if="hasOutcomes" class="section">
            <div class="section-hdr">
              <span class="section-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
              </span>
              <h2>Outcome Probabilities</h2>
            </div>
            <div class="prob-grid">
              <div v-for="(prob, label) in predictionData.outcomes" :key="label" class="prob-row">
                <div class="prob-label">{{ formatLabel(label) }}</div>
                <div class="prob-bar-wrap">
                  <div class="prob-bar" :style="{ width: (prob * 100) + '%' }" :class="probColor(prob)"></div>
                </div>
                <div class="prob-val mono">{{ (prob * 100).toFixed(0) }}%</div>
              </div>
            </div>
          </section>

          <!-- Actor Outcomes -->
          <section v-if="hasActors" class="section">
            <div class="section-hdr">
              <span class="section-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
              </span>
              <h2>Actor Outcomes</h2>
            </div>
            <div class="actor-table">
              <div class="actor-thead">
                <span>Actor</span><span>Force</span><span>Casualties</span><span>Approval</span>
              </div>
              <div v-for="(actor, id) in predictionData.actor_results" :key="id" class="actor-row">
                <span class="actor-name">{{ actor.name || id }}</span>
                <span class="actor-val mono">
                  <span class="force-bar" :style="{ width: (actor.avg_final_force || 0) + '%' }"></span>
                  {{ actor.avg_final_force?.toFixed(0) || '\u2014' }}
                </span>
                <span class="actor-val mono" :class="{ 'has-casualties': actor.avg_casualties > 0 }">
                  {{ actor.avg_casualties > 0 ? actor.avg_casualties.toLocaleString() : '0' }}
                </span>
                <span class="actor-val mono">{{ actor.avg_approval ? (actor.avg_approval * 100).toFixed(0) + '%' : '\u2014' }}</span>
              </div>
            </div>
          </section>

          <!-- Grounding Score -->
          <section v-if="predictionData.grounding_score != null" class="section">
            <div class="section-hdr">
              <span class="section-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              </span>
              <h2>Grounding Score</h2>
            </div>
            <div class="grounding-score">
              <div class="grounding-val mono" :class="groundingColor">{{ (predictionData.grounding_score * 100).toFixed(0) }}%</div>
              <div v-if="predictionData.grounding_report" class="grounding-report" v-html="formatAnswer(predictionData.grounding_report)"></div>
            </div>
          </section>

          <!-- Social Simulation -->
          <section v-if="hasSocialResults" class="section">
            <div class="section-hdr">
              <span class="section-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
              </span>
              <h2>Social Simulation</h2>
            </div>

            <!-- String fallback -->
            <div v-if="typeof predictionData.social_results === 'string'" class="answer-body" v-html="formatAnswer(predictionData.social_results)"></div>

            <!-- Structured data -->
            <div v-else class="social-cards">
              <!-- Pressure gauges -->
              <div v-if="socialEscalation != null || socialDeescalation != null" class="pressure-row">
                <div v-if="socialEscalation != null" class="pressure-card escalation">
                  <div class="pressure-label">Escalation Pressure</div>
                  <div class="pressure-bar-wrap">
                    <div class="pressure-bar esc-bar" :style="{ width: (socialEscalation * 100) + '%' }"></div>
                  </div>
                  <div class="pressure-val mono">{{ (socialEscalation * 100).toFixed(1) }}%</div>
                </div>
                <div v-if="socialDeescalation != null" class="pressure-card deescalation">
                  <div class="pressure-label">De-escalation Pressure</div>
                  <div class="pressure-bar-wrap">
                    <div class="pressure-bar deesc-bar" :style="{ width: (socialDeescalation * 100) + '%' }"></div>
                  </div>
                  <div class="pressure-val mono">{{ (socialDeescalation * 100).toFixed(1) }}%</div>
                </div>
              </div>

              <!-- Country sentiments -->
              <div v-if="sortedSentiments.length > 0" class="sentiments-block">
                <h3 class="sub-heading mono">Country Sentiments</h3>
                <div class="sentiment-list">
                  <div v-for="s in sortedSentiments" :key="s.name" class="sentiment-row">
                    <span class="sentiment-name">{{ s.name }}</span>
                    <span class="sentiment-badge mono" :class="s.cls">{{ s.label }}</span>
                  </div>
                </div>
              </div>

              <!-- Final round summary (if present) -->
              <div v-if="socialFinalRound" class="final-round-block">
                <h3 class="sub-heading mono">Final Round</h3>
                <div class="final-round-grid">
                  <div v-for="(val, key) in socialFinalRound" :key="key" class="fr-item">
                    <span class="fr-key">{{ formatLabel(key) }}</span>
                    <span class="fr-val mono">{{ typeof val === 'number' ? val.toFixed(3) : val }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- Run Info -->
          <footer v-if="predictionData.num_runs" class="run-footer mono">
            <span v-if="predictionData.num_runs">{{ predictionData.num_runs }} runs</span>
            <span class="dot-sep"></span>
            <span v-if="predictionData.num_agents">{{ predictionData.num_agents }} actors</span>
            <span class="dot-sep"></span>
            <span v-if="predictionData.gpu_cost">${{ Number(predictionData.gpu_cost || 0).toFixed(2) }} GPU</span>
            <template v-if="predictionData.scenario_type">
              <span class="dot-sep"></span>
              <span>{{ predictionData.scenario_type }}</span>
            </template>
          </footer>
        </div>
      </div>

      <!-- RIGHT: Chat -->
      <div class="col-chat">
        <div class="chat-top">
          <h3 class="chat-title">Follow-up Questions</h3>
        </div>

        <div class="chat-feed" ref="chatFeedEl">
          <div v-if="chatMessages.length === 0" class="chat-empty-state">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
            <p>Ask follow-up questions about this prediction</p>
          </div>
          <div v-for="(msg, i) in chatMessages" :key="i" class="chat-msg" :class="msg.role">
            <div class="msg-tag mono">{{ msg.role === 'user' ? 'YOU' : 'FORS8' }}</div>
            <div class="msg-text">
              <div v-if="msg.loading" class="typing-dots"><span></span><span></span><span></span></div>
              <div v-else v-html="formatAnswer(msg.content)"></div>
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="chat-input-wrap">
          <div class="input-bar" :class="{ focused: inputFocused }">
            <button class="clip-btn" @click="triggerFileInput" title="Attach file">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
            </button>
            <input ref="fileInputRef" type="file" multiple accept=".pdf,.md,.txt,.doc,.docx,.png,.jpg,.jpeg" @change="handleFileSelect" style="display:none" />
            <textarea
              ref="textareaRef"
              v-model="chatInput"
              class="text-input"
              placeholder="Ask a follow-up..."
              rows="1"
              :disabled="chatSending"
              @keydown.enter.exact.prevent="sendChatMessage"
              @input="autoResize"
              @focus="inputFocused = true"
              @blur="inputFocused = false"
            ></textarea>
            <button class="send-btn" :disabled="!canSend || chatSending" @click="sendChatMessage">
              <svg v-if="!chatSending" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
              <div v-else class="btn-spin"></div>
            </button>
          </div>
          <!-- Attached files -->
          <div v-if="attachedFiles.length > 0" class="attached-files">
            <div v-for="(f, i) in attachedFiles" :key="i" class="file-chip">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>
              <span>{{ f.name }}</span>
              <button @click="removeFile(i)" class="file-x">&times;</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'

const props = defineProps({
  predictionData: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  loadingStage: { type: String, default: '' },
  error: { type: String, default: '' },
  conversationId: { type: [String, Number], default: '' },
})
const emit = defineEmits(['retry', 'switch-tab'])

const hasData = computed(() => !!(props.predictionData?.answers?.main_answer || props.predictionData?.main_answer))
const mainAnswer = computed(() => props.predictionData?.answers?.main_answer || props.predictionData?.main_answer || '')
const hasOutcomes = computed(() => props.predictionData?.outcomes && Object.keys(props.predictionData.outcomes).length > 0)
const hasActors = computed(() => props.predictionData?.actor_results && Object.keys(props.predictionData.actor_results).length > 0)
const hasSocialResults = computed(() => props.predictionData?.social_results && (typeof props.predictionData.social_results === 'string' ? props.predictionData.social_results.length > 0 : Object.keys(props.predictionData.social_results).length > 0))
const groundingColor = computed(() => {
  const s = props.predictionData?.grounding_score
  if (s == null) return ''
  if (s >= 0.7) return 'high'
  if (s >= 0.4) return 'mid'
  return 'low'
})
const socialEscalation = computed(() => {
  const sr = props.predictionData?.social_results
  if (!sr || typeof sr === 'string') return null
  return sr.escalation_pressure ?? null
})
const socialDeescalation = computed(() => {
  const sr = props.predictionData?.social_results
  if (!sr || typeof sr === 'string') return null
  return sr.deescalation_pressure ?? null
})
const sortedSentiments = computed(() => {
  const sr = props.predictionData?.social_results
  if (!sr || typeof sr === 'string' || !sr.country_sentiments) return []
  return Object.entries(sr.country_sentiments)
    .map(([name, val]) => {
      const v = Number(val)
      let cls = 'neutral'
      let label = v.toFixed(3)
      if (v > 0.01) { cls = 'hawkish'; label = '+' + v.toFixed(3) }
      else if (v < -0.01) { cls = 'dovish'; label = v.toFixed(3) }
      else { label = v.toFixed(3) }
      return { name: formatLabel(name), val: v, cls, label }
    })
    .sort((a, b) => a.val - b.val)
})
const socialFinalRound = computed(() => {
  const sr = props.predictionData?.social_results
  if (!sr || typeof sr === 'string' || !sr.final_round) return null
  // Only include scalar values — skip nested objects/arrays (already shown elsewhere)
  const fr = sr.final_round
  const scalars = {}
  for (const [k, v] of Object.entries(fr)) {
    if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') {
      scalars[k] = typeof v === 'number' ? Math.round(v * 1000) / 1000 : v
    }
  }
  return Object.keys(scalars).length > 0 ? scalars : null
})
const canSend = computed(() => chatInput.value.trim() !== '')

const chatMessages = ref([])
const chatInput = ref('')
const chatSending = ref(false)
const inputFocused = ref(false)
const chatFeedEl = ref(null)
const textareaRef = ref(null)
const fileInputRef = ref(null)
const attachedFiles = ref([])

const triggerFileInput = () => fileInputRef.value?.click()
const handleFileSelect = (e) => {
  const files = Array.from(e.target.files || [])
  attachedFiles.value.push(...files.slice(0, 10 - attachedFiles.value.length))
  e.target.value = ''
}
const removeFile = (i) => attachedFiles.value.splice(i, 1)

const probColor = (prob) => {
  if (prob >= 0.7) return 'high'
  if (prob >= 0.4) return 'mid'
  return 'low'
}

const sendChatMessage = async () => {
  if (!canSend.value || chatSending.value) return
  const text = chatInput.value.trim()
  chatInput.value = ''
  resetTextarea()
  chatMessages.value.push({ role: 'user', content: text })
  await nextTick(); scrollToBottom()
  chatMessages.value.push({ role: 'assistant', content: '', loading: true })
  await nextTick(); scrollToBottom()
  chatSending.value = true
  const aidx = chatMessages.value.length - 1
  try {
    const convId = props.conversationId
    if (!convId) { chatMessages.value[aidx].loading = false; chatMessages.value[aidx].content = 'No active conversation.'; chatSending.value = false; return }
    const resp = await fetch(`/api/conversations/${convId}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text }) })
    if (!resp.ok) { chatMessages.value[aidx].loading = false; chatMessages.value[aidx].content = `Error: ${resp.status}`; chatSending.value = false; return }
    const data = await resp.json()
    if (data.prediction_id) { await pollForResponse(data.prediction_id, aidx) }
    else { chatMessages.value[aidx].loading = false; chatMessages.value[aidx].content = data.content || data.answer || data.message || 'Response received.' }
  } catch (e) { chatMessages.value[aidx].loading = false; chatMessages.value[aidx].content = 'Network error.' }
  finally { chatSending.value = false; await nextTick(); scrollToBottom() }
}

const pollForResponse = async (predictionId, msgIndex) => {
  let fails = 0
  return new Promise((resolve) => {
    const poll = async () => {
      try {
        const resp = await fetch(`/api/predict/${predictionId}`)
        if (!resp.ok) { fails++; if (fails >= 30) { chatMessages.value[msgIndex].loading = false; chatMessages.value[msgIndex].content = 'Timed out.'; resolve(); return }; setTimeout(poll, 2000); return }
        const data = await resp.json()
        if (data.status === 'complete') { chatMessages.value[msgIndex].loading = false; chatMessages.value[msgIndex].content = data.answers?.main_answer || 'Complete.'; await nextTick(); scrollToBottom(); resolve(); return }
        if (data.status === 'failed' || data.status === 'error') { chatMessages.value[msgIndex].loading = false; chatMessages.value[msgIndex].content = data.error || 'Failed.'; resolve(); return }
        setTimeout(poll, 2000)
      } catch (e) { fails++; if (fails >= 30) { chatMessages.value[msgIndex].loading = false; chatMessages.value[msgIndex].content = 'Network error.'; resolve(); return }; setTimeout(poll, 2000) }
    }
    poll()
  })
}

const scrollToBottom = () => { const el = chatFeedEl.value; if (el) el.scrollTop = el.scrollHeight }
const autoResize = () => { const el = textareaRef.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 120) + 'px' }
const resetTextarea = () => { nextTick(() => { const el = textareaRef.value; if (el) el.style.height = 'auto' }) }

const formatLabel = (l) => l.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const formatAnswer = (text) => {
  if (!text) return ''
  let t = escapeHtml(text)
  t = t.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
    .replace(/<\/ul>\s*<ul>/g, '')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
  return `<p>${t}</p>`
}

watch(() => props.predictionData?.prediction_id, () => { chatMessages.value = [] })
</script>

<style scoped>

* { box-sizing: border-box; margin: 0; padding: 0; }

.pred-panel {
  --c-bg: #ffffff;
  --c-surface: #fafafa;
  --c-surface-2: #f4f4f5;
  --c-border: #e4e4e7;
  --c-text: #18181b;
  --c-text-2: #3f3f46;
  --c-text-muted: #a1a1aa;
  --c-accent: #b8860b;
  --c-red: #dc2626;
  --c-green: #16a34a;
  --c-amber: #d97706;
  --font: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono: 'IBM Plex Mono', 'SF Mono', 'Menlo', monospace;

  height: 100%; font-family: var(--font); color: var(--c-text); background: var(--c-bg); -webkit-font-smoothing: antialiased;
}
.mono { font-family: var(--mono); }

/* States */
.state-overlay { height: 100%; display: flex; align-items: center; justify-content: center; }
.loader-wrap { text-align: center; }
.loader-ring { width: 32px; height: 32px; border: 3px solid var(--c-border); border-top-color: var(--c-accent); border-radius: 50%; animation: spin 0.7s linear infinite; margin: 0 auto 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
.loader-text { font-size: 13px; color: var(--c-text-muted); }
.error-wrap { text-align: center; }
.error-badge { width: 40px; height: 40px; border-radius: 50%; background: #fef2f2; color: var(--c-red); font-weight: 700; font-size: 20px; display: flex; align-items: center; justify-content: center; margin: 0 auto 16px; }
.error-msg { font-size: 14px; color: var(--c-text-2); margin-bottom: 20px; max-width: 400px; }
.btn-retry { padding: 8px 20px; background: var(--c-text); color: #fff; border: none; border-radius: 6px; font-family: var(--font); font-size: 13px; font-weight: 500; cursor: pointer; }
.btn-retry:hover { background: #333; }
.empty-wrap { text-align: center; }
.empty-title { font-size: 16px; font-weight: 600; color: var(--c-text-muted); margin-bottom: 6px; }
.empty-sub { font-size: 13px; color: #c4c4cc; max-width: 340px; line-height: 1.5; }
.empty-actions { display: flex; gap: 10px; margin-top: 18px; }
.btn-home { padding: 8px 20px; background: var(--c-text); color: #fff; border: none; border-radius: 6px; font-family: var(--font); font-size: 13px; font-weight: 500; cursor: pointer; transition: background 0.15s; }
.btn-home:hover { background: #333; }
.btn-history { padding: 8px 20px; background: transparent; color: var(--c-text-2); border: 1px solid var(--c-border); border-radius: 6px; font-family: var(--font); font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.btn-history:hover { border-color: var(--c-text-muted); color: var(--c-text); }

/* Layout */
.layout { display: flex; height: 100%; overflow: hidden; }
.col-report { flex: 0 0 60%; max-width: 60%; overflow-y: auto; border-right: 1px solid var(--c-border); }
.col-chat { flex: 0 0 40%; max-width: 40%; display: flex; flex-direction: column; }

/* Report */
.report-inner { padding: 36px 32px 60px; max-width: 680px; }
.report-hdr { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--c-border); }
.report-meta { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.tag { font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #fff; background: var(--c-text); padding: 3px 8px; border-radius: 3px; }
.id-tag { font-size: 11px; color: var(--c-text-muted); }
.report-question { font-size: 22px; font-weight: 700; letter-spacing: -0.3px; line-height: 1.35; }

/* Sections */
.section { margin-bottom: 24px; background: var(--c-surface); border: 1px solid var(--c-border); border-radius: 10px; padding: 20px 22px; }
.section-hdr { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.section-hdr h2 { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--c-text-muted); font-family: var(--mono); }
.section-icon { color: var(--c-text-muted); display: flex; }

/* Answer */
.answer-body { font-size: 14px; line-height: 1.75; color: var(--c-text-2); }
.answer-body :deep(p) { margin-bottom: 10px; }
.answer-body :deep(strong) { font-weight: 600; color: var(--c-text); }
.answer-body :deep(h2), .answer-body :deep(h3), .answer-body :deep(h4) { margin: 16px 0 8px; color: var(--c-text); font-weight: 600; }
.answer-body :deep(ul) { padding-left: 18px; margin-bottom: 10px; }
.answer-body :deep(li) { margin-bottom: 4px; }

/* Probability bars */
.prob-grid { display: flex; flex-direction: column; gap: 10px; }
.prob-row { display: flex; align-items: center; gap: 10px; }
.prob-label { width: 160px; font-size: 13px; font-weight: 500; flex-shrink: 0; }
.prob-bar-wrap { flex: 1; height: 20px; background: var(--c-surface-2); border-radius: 4px; overflow: hidden; }
.prob-bar { height: 100%; border-radius: 4px; transition: width 0.6s ease; min-width: 3px; }
.prob-bar.high { background: var(--c-red); }
.prob-bar.mid { background: var(--c-amber); }
.prob-bar.low { background: var(--c-green); }
.prob-val { width: 38px; font-size: 12px; text-align: right; flex-shrink: 0; color: var(--c-text-2); }

/* Actor table */
.actor-table { font-size: 13px; }
.actor-thead { display: grid; grid-template-columns: 1.3fr 1fr 1fr 0.8fr; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--c-border); font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--c-text-muted); }
.actor-row { display: grid; grid-template-columns: 1.3fr 1fr 1fr 0.8fr; gap: 8px; padding: 9px 0; border-bottom: 1px solid var(--c-surface-2); align-items: center; }
.actor-row:last-child { border-bottom: none; }
.actor-name { font-weight: 500; }
.actor-val { color: var(--c-text-2); font-size: 12px; position: relative; }
.actor-val.has-casualties { color: var(--c-red); font-weight: 600; }
.force-bar { position: absolute; left: 0; top: 0; bottom: 0; background: var(--c-surface-2); border-radius: 2px; z-index: 0; }
.actor-val .force-bar + * { position: relative; z-index: 1; }

/* Grounding score */
.grounding-score { display: flex; align-items: flex-start; gap: 16px; }
.grounding-val { font-size: 28px; font-weight: 600; flex-shrink: 0; }
.grounding-val.high { color: var(--c-green); }
.grounding-val.mid { color: var(--c-amber); }
.grounding-val.low { color: var(--c-red); }
.grounding-report { font-size: 13px; line-height: 1.6; color: var(--c-text-2); }

/* Social simulation */
.social-cards { display: flex; flex-direction: column; gap: 18px; }
.pressure-row { display: flex; gap: 12px; }
.pressure-card { flex: 1; background: var(--c-surface-2); border-radius: 8px; padding: 14px 16px; }
.pressure-label { font-size: 12px; font-weight: 500; color: var(--c-text-muted); margin-bottom: 8px; }
.pressure-bar-wrap { height: 8px; background: var(--c-border); border-radius: 4px; overflow: hidden; margin-bottom: 6px; }
.pressure-bar { height: 100%; border-radius: 4px; transition: width 0.6s ease; min-width: 2px; }
.esc-bar { background: var(--c-red); }
.deesc-bar { background: var(--c-green); }
.pressure-val { font-size: 18px; font-weight: 600; }
.pressure-card.escalation .pressure-val { color: var(--c-red); }
.pressure-card.deescalation .pressure-val { color: var(--c-green); }

.sub-heading { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--c-text-muted); margin-bottom: 10px; }

.sentiment-list { display: flex; flex-direction: column; gap: 6px; }
.sentiment-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 12px; background: var(--c-surface-2); border-radius: 6px; }
.sentiment-name { font-size: 13px; font-weight: 500; }
.sentiment-badge { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.sentiment-badge.hawkish { color: var(--c-red); background: #fef2f2; }
.sentiment-badge.dovish { color: var(--c-green); background: #f0fdf4; }
.sentiment-badge.neutral { color: var(--c-text-muted); background: var(--c-surface); }

.final-round-block { border-top: 1px solid var(--c-border); padding-top: 14px; }
.final-round-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.fr-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: var(--c-surface-2); border-radius: 6px; font-size: 13px; }
.fr-key { color: var(--c-text-2); }
.fr-val { font-size: 12px; color: var(--c-text); font-weight: 500; }

/* Run footer */
.run-footer { display: flex; align-items: center; gap: 10px; padding-top: 20px; margin-top: 8px; font-size: 11px; color: var(--c-text-muted); border-top: 1px solid var(--c-surface-2); }
.dot-sep { width: 3px; height: 3px; border-radius: 50%; background: var(--c-text-muted); }

/* ── Chat Column ── */
.chat-top { padding: 14px 18px; border-bottom: 1px solid var(--c-border); flex-shrink: 0; }
.chat-title { font-family: var(--mono); font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 1px; color: var(--c-text-muted); }

.chat-feed { flex: 1; overflow-y: auto; padding: 16px 18px; }
.chat-empty-state { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
.chat-empty-state p { font-size: 13px; color: #c4c4cc; }

.chat-msg { margin-bottom: 20px; }
.msg-tag { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--c-text-muted); margin-bottom: 4px; }
.msg-text { font-size: 14px; line-height: 1.65; color: var(--c-text-2); }
.chat-msg.user .msg-text { color: var(--c-text); font-weight: 500; }
.msg-text :deep(p) { margin-bottom: 6px; }
.msg-text :deep(strong) { font-weight: 600; color: var(--c-text); }

.typing-dots { display: flex; gap: 4px; padding: 6px 0; }
.typing-dots span { width: 6px; height: 6px; background: var(--c-text-muted); border-radius: 50%; animation: dotPulse 1s ease-in-out infinite; }
.typing-dots span:nth-child(2) { animation-delay: 0.15s; }
.typing-dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes dotPulse { 0%,80%,100% { transform: scale(0.6); opacity: 0.3; } 40% { transform: scale(1); opacity: 1; } }

/* Input */
.chat-input-wrap { padding: 10px 18px 14px; border-top: 1px solid var(--c-border); flex-shrink: 0; }
.input-bar { display: flex; align-items: flex-end; gap: 6px; border: 1.5px solid var(--c-border); border-radius: 10px; padding: 6px 10px; background: var(--c-bg); transition: border-color 0.15s, box-shadow 0.15s; }
.input-bar.focused { border-color: var(--c-accent); box-shadow: 0 0 0 3px var(--c-accent, 0.06); }

.clip-btn { background: none; border: none; color: var(--c-text-muted); cursor: pointer; padding: 4px; display: flex; border-radius: 4px; transition: color 0.15s; flex-shrink: 0; }
.clip-btn:hover { color: var(--c-text-2); }

.text-input { flex: 1; border: none; outline: none; resize: none; font-family: var(--font); font-size: 13px; line-height: 1.5; color: var(--c-text); background: transparent; min-height: 22px; max-height: 120px; }
.text-input::placeholder { color: #c4c4cc; }

.send-btn { width: 30px; height: 30px; border-radius: 50%; background: var(--c-text); border: none; color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: background 0.15s, transform 0.1s; }
.send-btn:hover:not(:disabled) { background: #444; transform: scale(1.04); }
.send-btn:disabled { background: var(--c-border); color: var(--c-text-muted); cursor: default; }
.btn-spin { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,0.25); border-top-color: #fff; border-radius: 50%; animation: spin 0.6s linear infinite; }

/* Attached files */
.attached-files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.file-chip { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--c-text-2); background: var(--c-surface-2); padding: 4px 8px; border-radius: 4px; }
.file-x { background: none; border: none; color: var(--c-text-muted); cursor: pointer; font-size: 14px; line-height: 1; padding: 0 2px; }
.file-x:hover { color: var(--c-red); }

/* Responsive */
@media (max-width: 900px) {
  .layout { flex-direction: column; }
  .col-report { flex: none; max-width: 100%; border-right: none; border-bottom: 1px solid var(--c-border); max-height: 55vh; }
  .col-chat { flex: 1; max-width: 100%; min-height: 280px; }
  .report-inner { padding: 24px 18px 36px; }
  .prob-label { width: 120px; font-size: 12px; }
}
</style>
