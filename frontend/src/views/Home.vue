<template>
  <div class="page">
    <!-- Nav -->
    <nav class="nav">
      <div class="nav-brand">FORS8</div>
      <div class="nav-links">
        <router-link to="/chat" class="nav-link">Chat</router-link>
        <router-link to="/settings" class="nav-link">Settings</router-link>
        <a href="https://github.com/666ghj/MiroFish" target="_blank" class="nav-link">GitHub <span class="arrow">↗</span></a>
      </div>
    </nav>

    <div class="content">
      <!-- Hero -->
      <section class="hero" :class="{ visible: mounted }">
        <div class="hero-text">
          <div class="tag">Geopolitical Conflict Prediction Engine</div>
          <h1>Simulate Wars.<br>Predict Outcomes.</h1>
          <p class="desc">
            Deploy up to 100,000 AI agents as nations, militaries, and proxy groups — each making strategic decisions every round. Run parallel simulations across GPU clusters to generate probability-weighted predictions.
          </p>
          <p class="tagline">Who wins. How long. What it costs.</p>
        </div>
        <div class="hero-viz">
          <Fors8Logo3D :size="380" />
        </div>
      </section>

      <!-- Chat Input -->
      <section class="input-section" :class="{ visible: mounted }">
        <div v-if="files.length > 0" class="attached">
          <div v-for="(file, i) in files" :key="i" class="chip">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
            <span>{{ file.name }}</span>
            <button @click.stop="removeFile(i)" class="chip-x">&times;</button>
          </div>
        </div>
        <div class="chat-bar" :class="{ focused: inputFocused }">
          <button class="clip-btn" @click="triggerFileInput" title="Attach files">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
          </button>
          <input
            ref="fileInput"
            type="file"
            multiple
            accept=".pdf,.md,.txt,.doc,.docx,.png,.jpg,.jpeg"
            @change="handleFileSelect"
            style="display:none"
            :disabled="loading"
          />
          <textarea
            ref="textareaRef"
            v-model="query"
            class="chat-input"
            placeholder="Who will win the Iran war? How long will it last?"
            rows="1"
            :disabled="loading"
            @keydown.enter.exact.prevent="submit"
            @input="autoResize"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
          ></textarea>
          <button class="send-btn" :disabled="!canSubmit || loading" @click="submit">
            <svg v-if="!loading" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            <div v-else class="spinner"></div>
          </button>
        </div>
        <div class="input-footer">
          <span>Fors8 v1.0</span>
          <span>PDF, MD, TXT, Word, images</span>
        </div>
      </section>

      <!-- Stats -->
      <section class="stats" :class="{ visible: mounted }">
        <div class="stat">
          <div class="stat-val">~$5</div>
          <div class="stat-label">per 100K-agent simulation</div>
        </div>
        <div class="stat-divider"></div>
        <div class="stat">
          <div class="stat-val">100K+</div>
          <div class="stat-label">AI agents across parallel runs</div>
        </div>
        <div class="stat-divider"></div>
        <div class="stat">
          <div class="stat-val">11</div>
          <div class="stat-label">real-time OSINT sources</div>
        </div>
      </section>

      <!-- Workflow -->
      <section class="workflow" :class="{ visible: mounted }">
        <h2 class="section-heading">How it works</h2>
        <div class="steps">
          <div v-for="(step, i) in steps" :key="i" class="step" :style="{ animationDelay: (i * 0.08) + 's' }">
            <div class="step-num">{{ String(i + 1).padStart(2, '0') }}</div>
            <div class="step-body">
              <div class="step-title">{{ step.title }}</div>
              <div class="step-desc">{{ step.desc }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- History -->
      <section class="history-section">
        <HistoryDatabase />
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import Fors8Logo3D from '../components/Fors8Logo3D.vue'
import { setPendingUpload } from '../store/pendingUpload'

const router = useRouter()
const mounted = ref(false)

const query = ref('')
const files = ref([])
const loading = ref(false)
const inputFocused = ref(false)
const fileInput = ref(null)
const textareaRef = ref(null)

const steps = [
  { title: 'Data Ingestion', desc: 'Auto-ingest from YouTube, news RSS, GDELT, Google News, and 7 more sources — plus upload your own docs.' },
  { title: 'Actor Profiling', desc: 'Generate 20+ geopolitical actor profiles with ideology, military capability, temperament, and strategic doctrine.' },
  { title: 'War Simulation', desc: 'OODA-loop decision engine with escalation guardrails, fog of war, and consequence modeling across parallel GPU runs.' },
  { title: 'Prediction Report', desc: 'Probability-weighted outcomes — who wins, how long, what it costs — aggregated across 10+ simulation runs.' },
  { title: 'Ask Anything', desc: 'Interview simulated leaders in-character, ask strategic questions, explore what-if scenarios.' },
]

const canSubmit = computed(() => query.value.trim() !== '')

const triggerFileInput = () => { if (!loading.value) fileInput.value?.click() }

const handleFileSelect = (e) => {
  const selected = Array.from(e.target.files)
  addFiles(selected)
  e.target.value = ''
}

const MAX_FILE_SIZE = 50 * 1024 * 1024  // 50 MB per file
const MAX_FILES = 10

const addFiles = (newFiles) => {
  const allowedExts = ['pdf', 'md', 'txt', 'doc', 'docx', 'png', 'jpg', 'jpeg']
  const valid = newFiles.filter(f => {
    const parts = f.name.split('.')
    if (parts.length < 2) return false  // no extension
    const ext = parts.pop().toLowerCase()
    if (!allowedExts.includes(ext)) return false
    if (f.size > MAX_FILE_SIZE) return false
    return true
  })
  const remaining = MAX_FILES - files.value.length
  files.value.push(...valid.slice(0, Math.max(0, remaining)))
}

const removeFile = (i) => files.value.splice(i, 1)

const autoResize = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

const submit = () => {
  if (!canSubmit.value || loading.value) return
  setPendingUpload([...files.value], query.value, 'geopolitical')
  router.push('/process/new')
}

onMounted(() => {
  requestAnimationFrame(() => { mounted.value = true })
})
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=DM+Mono:wght@400;500&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

.page {
  min-height: 100vh;
  background: #fff;
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
  color: #111;
  -webkit-font-smoothing: antialiased;
}

/* ── Nav ── */
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

/* ── Content ── */
.content {
  max-width: 980px;
  margin: 0 auto;
  padding: 0 32px;
}

/* ── Hero ── */
.hero {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 40px;
  align-items: center;
  padding: 72px 0 48px;
  opacity: 0;
  transform: translateY(16px);
  transition: opacity 0.7s ease, transform 0.7s ease;
}
.hero.visible { opacity: 1; transform: none; }

.tag {
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.5px;
  color: #999;
  text-transform: uppercase;
  margin-bottom: 20px;
}

h1 {
  font-size: 46px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -1.5px;
  margin-bottom: 20px;
}

.desc {
  font-size: 16px;
  line-height: 1.65;
  color: #555;
  max-width: 480px;
  margin-bottom: 16px;
}

.tagline {
  font-style: italic;
  color: #999;
  font-size: 15px;
}

.hero-viz {
  display: flex;
  justify-content: center;
  align-items: center;
}

/* ── Chat Input ── */
.input-section {
  padding-bottom: 48px;
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 0.7s ease 0.15s, transform 0.7s ease 0.15s;
}
.input-section.visible { opacity: 1; transform: none; }

.attached {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  background: #f5f5f5;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  font-size: 12px;
  color: #444;
  font-family: 'DM Mono', monospace;
}
.chip span { max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip svg { color: #999; flex-shrink: 0; }
.chip-x {
  background: none;
  border: none;
  font-size: 16px;
  color: #bbb;
  cursor: pointer;
  line-height: 1;
  padding: 0;
}
.chip-x:hover { color: #e00; }

.chat-bar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  border: 1.5px solid #ddd;
  border-radius: 14px;
  padding: 10px 14px;
  background: #fff;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.chat-bar.focused {
  border-color: #111;
  box-shadow: 0 0 0 3px rgba(0,0,0,0.04);
}

.clip-btn {
  background: none;
  border: none;
  color: #aaa;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  flex-shrink: 0;
  display: flex;
  transition: color 0.15s;
}
.clip-btn:hover { color: #111; }

.chat-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font-family: 'DM Sans', sans-serif;
  font-size: 15px;
  line-height: 1.5;
  color: #111;
  background: transparent;
  min-height: 24px;
  max-height: 160px;
}
.chat-input::placeholder { color: #bbb; }

.send-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #111;
  border: none;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, transform 0.1s;
}
.send-btn:hover:not(:disabled) { background: #333; transform: scale(1.04); }
.send-btn:disabled { background: #e0e0e0; cursor: default; }

.spinner {
  width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,0.25);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.input-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 11px;
  color: #bbb;
  font-family: 'DM Mono', monospace;
  padding: 0 4px;
}

/* ── Stats ── */
.stats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 36px 0;
  border-top: 1px solid #eee;
  border-bottom: 1px solid #eee;
  opacity: 0;
  transform: translateY(10px);
  transition: opacity 0.6s ease 0.25s, transform 0.6s ease 0.25s;
}
.stats.visible { opacity: 1; transform: none; }

.stat {
  flex: 1;
  text-align: center;
  padding: 0 24px;
}

.stat-divider {
  width: 1px;
  height: 36px;
  background: #e8e8e8;
  flex-shrink: 0;
}

.stat-val {
  font-family: 'DM Mono', monospace;
  font-size: 28px;
  font-weight: 500;
  letter-spacing: -0.5px;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 12px;
  color: #999;
}

/* ── Workflow ── */
.workflow {
  padding: 56px 0;
  opacity: 0;
  transform: translateY(10px);
  transition: opacity 0.6s ease 0.35s, transform 0.6s ease 0.35s;
}
.workflow.visible { opacity: 1; transform: none; }

.section-heading {
  font-size: 13px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin-bottom: 28px;
}

.steps { display: flex; flex-direction: column; }

.step {
  display: flex;
  gap: 20px;
  padding: 18px 0;
  border-bottom: 1px solid #f0f0f0;
  opacity: 0;
  animation: stepIn 0.4s ease forwards;
}

@keyframes stepIn {
  from { opacity: 0; transform: translateX(-8px); }
  to { opacity: 1; transform: none; }
}

.step:last-child { border-bottom: none; }

.step-num {
  font-family: 'DM Mono', monospace;
  font-size: 12px;
  color: #ccc;
  padding-top: 2px;
  flex-shrink: 0;
  width: 24px;
}

.step-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 3px;
}

.step-desc {
  font-size: 13px;
  color: #888;
  line-height: 1.5;
}

/* ── History ── */
.history-section {
  border-top: 1px solid #eee;
  padding: 40px 0;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .hero {
    grid-template-columns: 1fr;
    padding: 40px 0 24px;
    text-align: center;
  }
  h1 { font-size: 32px; }
  .desc { max-width: 100%; }
  .hero-viz { order: -1; }
  .stats { flex-direction: column; gap: 20px; }
  .stat-divider { width: 40px; height: 1px; }
  .content { padding: 0 20px; }
}
</style>
