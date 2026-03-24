<template>
  <div class="chat-page">
    <!-- Nav -->
    <nav class="nav">
      <router-link to="/" class="nav-brand">FORS8</router-link>
      <div class="nav-links">
        <router-link to="/chat" class="nav-link">Chat</router-link>
        <router-link to="/settings" class="nav-link">Settings</router-link>
        <a href="https://github.com/666ghj/MiroFish" target="_blank" class="nav-link">GitHub <span class="arrow">&#8599;</span></a>
      </div>
    </nav>

    <div class="chat-layout">
      <!-- Sidebar -->
      <aside class="sidebar">
        <button class="new-chat-btn" @click="createConversation">+ New Chat</button>
        <div class="conversation-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conversation-item"
            :class="{ active: conv.id === activeConversationId }"
            @click="selectConversation(conv.id)"
          >
            <div class="conv-title">{{ conv.title || 'Untitled' }}</div>
            <div class="conv-date">{{ formatDate(conv.updated_at || conv.created_at) }}</div>
          </div>
          <div v-if="conversations.length === 0 && !sidebarLoading" class="sidebar-empty">
            No conversations yet
          </div>
          <div v-if="sidebarLoading" class="sidebar-loading">
            <div class="dot-loader"><span></span><span></span><span></span></div>
          </div>
        </div>
      </aside>

      <!-- Main Chat Area -->
      <main class="chat-main">
        <!-- Empty state -->
        <div v-if="!activeConversationId" class="empty-state">
          <h2>Start a prediction conversation</h2>
          <p>Ask a geopolitical question to begin.</p>
        </div>

        <!-- Messages -->
        <div v-else class="messages-container" ref="messagesContainer">
          <div class="messages">
            <div
              v-for="(msg, i) in messages"
              :key="i"
              class="message"
              :class="msg.role"
            >
              <div class="message-label">{{ msg.role === 'user' ? 'YOU' : 'FORS8' }}</div>
              <div class="message-body">
                <!-- User message: plain text -->
                <template v-if="msg.role === 'user'">
                  <p>{{ msg.content }}</p>
                </template>

                <!-- Assistant message: prediction results or text -->
                <template v-else>
                  <!-- Loading state for pending predictions -->
                  <div v-if="msg.status === 'pending' || msg.status === 'running'" class="prediction-loading">
                    <div class="stage-spinner"></div>
                    <span class="loading-text">{{ msg.progress_message || 'Running prediction...' }}</span>
                  </div>

                  <!-- Error -->
                  <div v-else-if="msg.status === 'error' || msg.status === 'failed'" class="prediction-error">
                    <p>{{ msg.error || 'Prediction failed.' }}</p>
                  </div>

                  <!-- Completed prediction results inline -->
                  <template v-else>
                    <!-- Main answer -->
                    <div v-if="msg.answers && msg.answers.main_answer" class="inline-answer" v-html="formatAnswer(msg.answers.main_answer)"></div>
                    <div v-else-if="msg.content" class="inline-answer" v-html="formatAnswer(msg.content)"></div>

                    <!-- Outcome bars -->
                    <div v-if="msg.outcomes && Object.keys(msg.outcomes).length" class="inline-card">
                      <div class="inline-card-title">Outcome Probabilities</div>
                      <div class="bar-chart">
                        <div v-for="(prob, label) in msg.outcomes" :key="label" class="bar-row">
                          <div class="bar-label">{{ formatLabel(label) }}</div>
                          <div class="bar-track">
                            <div class="bar-fill" :style="{ width: (prob * 100) + '%' }"></div>
                          </div>
                          <div class="bar-value">{{ (prob * 100).toFixed(0) }}%</div>
                        </div>
                      </div>
                    </div>

                    <!-- Actor table -->
                    <div v-if="msg.actor_results && Object.keys(msg.actor_results).length" class="inline-card">
                      <div class="inline-card-title">Actor Outcomes</div>
                      <div class="actors-table">
                        <div class="actors-header">
                          <span>Actor</span>
                          <span>Force</span>
                          <span>Casualties</span>
                          <span>Approval</span>
                        </div>
                        <div v-for="(actor, id) in msg.actor_results" :key="id" class="actors-row">
                          <span class="actor-name">{{ actor.name || id }}</span>
                          <span class="actor-stat">{{ actor.avg_final_force?.toFixed(0) || '\u2014' }}/100</span>
                          <span class="actor-stat">{{ actor.avg_casualties?.toLocaleString() || '0' }}</span>
                          <span class="actor-stat">{{ actor.avg_approval ? (actor.avg_approval * 100).toFixed(0) + '%' : '\u2014' }}</span>
                        </div>
                      </div>
                    </div>

                    <!-- Run info -->
                    <div v-if="msg.num_runs" class="run-info-inline">
                      <span>{{ msg.num_runs }} simulation runs</span>
                      <span v-if="msg.num_agents">{{ msg.num_agents }} actors</span>
                      <span v-if="msg.gpu_cost">${{ msg.gpu_cost.toFixed(2) }} GPU cost</span>
                    </div>
                  </template>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- Input bar -->
        <div class="chat-input-area">
          <div class="chat-bar" :class="{ focused: inputFocused }">
            <button class="clip-btn" @click="triggerFileInput" title="Attach files" :disabled="sending">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
            </button>
            <input
              ref="fileInput"
              type="file"
              multiple
              accept=".pdf,.md,.txt,.doc,.docx,.png,.jpg,.jpeg"
              @change="handleFileSelect"
              style="display:none"
              :disabled="sending"
            />
            <textarea
              ref="textareaRef"
              v-model="query"
              class="chat-input"
              placeholder="Ask a prediction question..."
              rows="1"
              :disabled="sending"
              @keydown.enter.exact.prevent="sendMessage"
              @input="autoResize"
              @focus="inputFocused = true"
              @blur="inputFocused = false"
            ></textarea>
            <button class="send-btn" :disabled="!canSend || sending" @click="sendMessage">
              <svg v-if="!sending" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
              <div v-else class="spinner"></div>
            </button>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const props = defineProps({
  conversationId: {
    type: String,
    default: null
  }
})

const router = useRouter()
const route = useRoute()

const conversations = ref([])
const messages = ref([])
const activeConversationId = ref(null)
const sidebarLoading = ref(false)
const sending = ref(false)
const query = ref('')
const inputFocused = ref(false)
const fileInput = ref(null)
const textareaRef = ref(null)
const messagesContainer = ref(null)

let pollTimers = {}

const canSend = computed(() => query.value.trim() !== '')

// --- Sidebar ---

const loadConversations = async () => {
  sidebarLoading.value = true
  try {
    const resp = await fetch('/api/conversations')
    if (resp.ok) {
      conversations.value = await resp.json()
    }
  } catch (e) {
    console.error('Failed to load conversations:', e)
  } finally {
    sidebarLoading.value = false
  }
}

const createConversation = async () => {
  try {
    const resp = await fetch('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New Conversation' })
    })
    if (resp.ok) {
      const conv = await resp.json()
      conversations.value.unshift(conv)
      router.push(`/chat/${conv.id}`)
    }
  } catch (e) {
    console.error('Failed to create conversation:', e)
  }
}

const selectConversation = (id) => {
  router.push(`/chat/${id}`)
}

const loadConversation = async (id) => {
  if (!id) return
  activeConversationId.value = id
  try {
    const resp = await fetch(`/api/conversations/${id}`)
    if (resp.ok) {
      const data = await resp.json()
      messages.value = data.messages || []
      // Start polling for any pending messages
      messages.value.forEach((msg, i) => {
        if (msg.role === 'assistant' && (msg.status === 'pending' || msg.status === 'running') && msg.prediction_id) {
          startPolling(msg.prediction_id, i)
        }
      })
      await nextTick()
      scrollToBottom()
    }
  } catch (e) {
    console.error('Failed to load conversation:', e)
  }
}

// --- Messaging ---

const sendMessage = async () => {
  if (!canSend.value || sending.value) return
  const text = query.value.trim()
  query.value = ''
  resetTextarea()

  // Create conversation if none active
  if (!activeConversationId.value) {
    try {
      const resp = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: text.slice(0, 80) })
      })
      if (resp.ok) {
        const conv = await resp.json()
        conversations.value.unshift(conv)
        activeConversationId.value = conv.id
        router.push(`/chat/${conv.id}`)
      } else {
        return
      }
    } catch (e) {
      console.error('Failed to create conversation:', e)
      return
    }
  }

  // Add user message locally
  messages.value.push({ role: 'user', content: text })
  await nextTick()
  scrollToBottom()

  // Send to server
  sending.value = true
  try {
    const resp = await fetch(`/api/conversations/${activeConversationId.value}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text })
    })
    if (resp.ok) {
      const data = await resp.json()
      // Add assistant placeholder
      const assistantMsg = {
        role: 'assistant',
        status: data.status || 'pending',
        prediction_id: data.prediction_id,
        content: '',
        progress_message: 'Starting prediction...'
      }
      messages.value.push(assistantMsg)
      const msgIndex = messages.value.length - 1
      await nextTick()
      scrollToBottom()

      // Update sidebar title if it was the first message
      const conv = conversations.value.find(c => c.id === activeConversationId.value)
      if (conv && (conv.title === 'New Conversation' || !conv.title)) {
        conv.title = text.slice(0, 80)
      }

      // Start polling for this prediction
      if (data.prediction_id) {
        startPolling(data.prediction_id, msgIndex)
      }
    }
  } catch (e) {
    console.error('Failed to send message:', e)
    messages.value.push({ role: 'assistant', status: 'error', error: 'Failed to send message.' })
  } finally {
    sending.value = false
    await nextTick()
    scrollToBottom()
  }
}

// --- Prediction polling ---

const startPolling = (predictionId, msgIndex) => {
  if (pollTimers[predictionId]) return

  let failCount = 0
  const MAX_FAILURES = 5

  const poll = async () => {
    try {
      const resp = await fetch(`/api/predict/${predictionId}`)
      if (!resp.ok) {
        failCount++
        if (failCount >= MAX_FAILURES) {
          messages.value[msgIndex].status = 'error'
          messages.value[msgIndex].error = `Server error (HTTP ${resp.status})`
          stopPolling(predictionId)
        }
        return
      }
      failCount = 0
      const data = await resp.json()

      const msg = messages.value[msgIndex]
      if (!msg) { stopPolling(predictionId); return }

      msg.status = data.status || 'pending'
      msg.progress_message = data.progress_message || ''

      if (data.status === 'failed') {
        msg.status = 'error'
        msg.error = data.error || 'Prediction failed.'
        stopPolling(predictionId)
      }

      if (data.status === 'complete') {
        msg.status = 'complete'
        msg.answers = data.answers || {}
        msg.content = data.answers?.main_answer || ''
        msg.outcomes = data.outcomes || {}
        msg.actor_results = data.actor_results || {}
        msg.num_runs = data.num_runs || 0
        msg.num_agents = data.num_agents || 0
        msg.gpu_cost = data.gpu_cost || 0
        stopPolling(predictionId)
        await nextTick()
        scrollToBottom()
      }
    } catch (e) {
      console.error('Poll error:', e)
      failCount++
      if (failCount >= MAX_FAILURES) {
        messages.value[msgIndex].status = 'error'
        messages.value[msgIndex].error = 'Network error.'
        stopPolling(predictionId)
      }
    }
  }

  poll()
  pollTimers[predictionId] = setInterval(poll, 2000)
}

const stopPolling = (predictionId) => {
  if (pollTimers[predictionId]) {
    clearInterval(pollTimers[predictionId])
    delete pollTimers[predictionId]
  }
}

// --- Utilities ---

const scrollToBottom = () => {
  const el = messagesContainer.value
  if (el) el.scrollTop = el.scrollHeight
}

const autoResize = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

const resetTextarea = () => {
  nextTick(() => {
    const el = textareaRef.value
    if (el) el.style.height = 'auto'
  })
}

const triggerFileInput = () => { if (!sending.value) fileInput.value?.click() }

const handleFileSelect = (e) => {
  // File handling placeholder — attach to message in future
  e.target.value = ''
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now - d
  if (diff < 86400000) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  if (diff < 604800000) {
    return d.toLocaleDateString([], { weekday: 'short' })
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

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

// --- Lifecycle ---

watch(() => route.params.conversationId, (newId) => {
  if (newId) {
    loadConversation(newId)
  } else {
    activeConversationId.value = null
    messages.value = []
  }
})

onMounted(() => {
  loadConversations()
  if (props.conversationId) {
    loadConversation(props.conversationId)
  }
})

onUnmounted(() => {
  Object.keys(pollTimers).forEach(stopPolling)
})
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=DM+Mono:wght@400;500&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

.chat-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
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
  flex-shrink: 0;
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

/* Layout */
.chat-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Sidebar */
.sidebar {
  width: 240px;
  border-right: 1px solid #eee;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: #fafafa;
}

.new-chat-btn {
  margin: 16px;
  padding: 10px 16px;
  background: #111;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.new-chat-btn:hover { background: #333; }

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.conversation-item {
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
  margin-bottom: 2px;
}
.conversation-item:hover { background: #f0f0f0; }
.conversation-item.active { background: #e8e8e8; }

.conv-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-date {
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  color: #999;
  margin-top: 3px;
}

.sidebar-empty {
  padding: 24px 12px;
  font-size: 13px;
  color: #bbb;
  text-align: center;
}

.sidebar-loading {
  padding: 24px;
  display: flex;
  justify-content: center;
}

.dot-loader { display: flex; gap: 4px; }
.dot-loader span {
  width: 6px;
  height: 6px;
  background: #ccc;
  border-radius: 50%;
  animation: dotBounce 1s ease-in-out infinite;
}
.dot-loader span:nth-child(2) { animation-delay: 0.15s; }
.dot-loader span:nth-child(3) { animation-delay: 0.3s; }
@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* Main Area */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #bbb;
}
.empty-state h2 {
  font-size: 20px;
  font-weight: 600;
  color: #999;
  margin-bottom: 8px;
}
.empty-state p {
  font-size: 14px;
}

/* Messages */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 32px 0;
}

.messages {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 32px;
}

.message {
  margin-bottom: 32px;
}

.message-label {
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin-bottom: 8px;
}

.message-body {
  font-size: 15px;
  line-height: 1.65;
  color: #333;
}

.message.user .message-body {
  color: #111;
  font-weight: 500;
}

/* Prediction loading */
.prediction-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 0;
}

.loading-text {
  font-size: 14px;
  color: #888;
}

.stage-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid #ddd;
  border-top-color: #111;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.prediction-error {
  color: #c00;
  font-size: 14px;
}

/* Inline result cards */
.inline-answer {
  margin-bottom: 16px;
  line-height: 1.7;
}
.inline-answer p { margin-bottom: 10px; }

.inline-card {
  border: 1px solid #eee;
  border-radius: 10px;
  padding: 20px;
  margin-top: 16px;
  margin-bottom: 12px;
}

.inline-card-title {
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin-bottom: 16px;
}

/* Bar Chart */
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bar-label {
  width: 180px;
  font-size: 13px;
  font-weight: 500;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 22px;
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
  width: 40px;
  font-family: 'DM Mono', monospace;
  font-size: 12px;
  text-align: right;
  flex-shrink: 0;
  color: #555;
}

/* Actors Table */
.actors-table {
  font-size: 13px;
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
  padding: 10px 0;
  border-bottom: 1px solid #f5f5f5;
}
.actors-row:last-child { border-bottom: none; }

.actor-name { font-weight: 500; }
.actor-stat { font-family: 'DM Mono', monospace; color: #555; }

.run-info-inline {
  display: flex;
  gap: 20px;
  margin-top: 16px;
  font-family: 'DM Mono', monospace;
  font-size: 12px;
  color: #999;
}

/* Input Area */
.chat-input-area {
  padding: 16px 32px 24px;
  border-top: 1px solid #eee;
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
}

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
.clip-btn:disabled { color: #ddd; cursor: default; }

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

/* Responsive */
@media (max-width: 768px) {
  .sidebar { display: none; }
  .messages { padding: 0 16px; }
  .chat-input-area { padding: 12px 16px 16px; }
  .bar-label { width: 100px; font-size: 12px; }
  .actors-header, .actors-row { grid-template-columns: 1fr 1fr; }
}
</style>
