<template>
  <div class="ch-panel">
    <!-- Sidebar -->
    <aside class="ch-sidebar">
      <button class="new-btn" @click="createConversation">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New Chat
      </button>
      <div class="conv-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === activeConversationId }"
          @click="selectConversation(conv.id)"
        >
          <div class="conv-title">{{ conv.title || 'Untitled' }}</div>
          <div class="conv-date mono">{{ formatDate(conv.updated_at || conv.created_at) }}</div>
        </div>
        <div v-if="conversations.length === 0 && !sidebarLoading" class="conv-empty">No conversations yet</div>
        <div v-if="sidebarLoading" class="conv-loading"><div class="dots"><span></span><span></span><span></span></div></div>
      </div>
    </aside>

    <!-- Main -->
    <main class="ch-main">
      <div v-if="!activeConversationId" class="empty-state">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.25"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
        <h2>Select a conversation</h2>
        <p>Your past predictions and chats appear here.</p>
      </div>

      <!-- Messages -->
      <div v-else class="msg-scroll" ref="msgScrollEl">
        <div class="msg-inner">
          <div v-for="(msg, i) in messages" :key="i" class="msg" :class="msg.role">
            <div class="msg-label mono">{{ msg.role === 'user' ? 'YOU' : 'FORS8' }}</div>
            <div class="msg-body">
              <template v-if="msg.role === 'user'"><p>{{ msg.content }}</p></template>
              <template v-else>
                <div v-if="msg.status === 'pending' || msg.status === 'running'" class="msg-loading">
                  <div class="spin-sm"></div>
                  <span>{{ msg.progress_message || 'Running prediction...' }}</span>
                </div>
                <div v-else-if="msg.status === 'error' || msg.status === 'failed'" class="msg-error">{{ msg.error || 'Prediction failed.' }}</div>
                <template v-else>
                  <div v-if="msg.answers && msg.answers.main_answer" class="msg-answer" v-html="formatAnswer(msg.answers.main_answer)"></div>
                  <div v-else-if="msg.content" class="msg-answer" v-html="formatAnswer(msg.content)"></div>

                  <div v-if="msg.outcomes && Object.keys(msg.outcomes).length" class="inline-section">
                    <div class="inline-title mono">Outcome Probabilities</div>
                    <div class="bar-list">
                      <div v-for="(prob, label) in msg.outcomes" :key="label" class="bar-row">
                        <div class="bar-name">{{ formatLabel(label) }}</div>
                        <div class="bar-track"><div class="bar-fill" :style="{ width: (prob * 100) + '%' }"></div></div>
                        <div class="bar-pct mono">{{ (prob * 100).toFixed(0) }}%</div>
                      </div>
                    </div>
                  </div>

                  <div v-if="msg.actor_results && Object.keys(msg.actor_results).length" class="inline-section">
                    <div class="inline-title mono">Actor Outcomes</div>
                    <div class="tbl">
                      <div class="tbl-head"><span>Actor</span><span>Force</span><span>Casualties</span><span>Approval</span></div>
                      <div v-for="(actor, id) in msg.actor_results" :key="id" class="tbl-row">
                        <span class="tbl-name">{{ actor.name || id }}</span>
                        <span class="tbl-val mono">{{ actor.avg_final_force?.toFixed(0) || '\u2014' }}/100</span>
                        <span class="tbl-val mono">{{ actor.avg_casualties?.toLocaleString() || '0' }}</span>
                        <span class="tbl-val mono">{{ actor.avg_approval ? (actor.avg_approval * 100).toFixed(0) + '%' : '\u2014' }}</span>
                      </div>
                    </div>
                  </div>

                  <div v-if="msg.num_runs" class="run-info mono">
                    <span>{{ msg.num_runs }} runs</span>
                    <span v-if="msg.num_agents">{{ msg.num_agents }} actors</span>
                    <span v-if="msg.gpu_cost">${{ msg.gpu_cost.toFixed(2) }}</span>
                  </div>
                </template>
              </template>
            </div>
          </div>
          <div v-if="messagesLoading" class="msg-loading-wrap"><div class="dots"><span></span><span></span><span></span></div></div>
        </div>
      </div>

      <!-- Input -->
      <div v-if="activeConversationId" class="ch-input">
        <div class="input-bar" :class="{ focused: inputFocused }">
          <button class="clip-btn" @click="$refs.fileInput?.click()" title="Attach file">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
          </button>
          <input ref="fileInput" type="file" multiple accept=".pdf,.md,.txt,.doc,.docx,.png,.jpg,.jpeg" style="display:none" />
          <textarea
            ref="textareaRef"
            v-model="query"
            class="text-input"
            placeholder="Ask a prediction question..."
            rows="1"
            :disabled="sending"
            @keydown.enter.exact.prevent="sendMessage"
            @input="autoResize"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
          ></textarea>
          <button class="send-btn" :disabled="!canSend || sending" @click="sendMessage">
            <svg v-if="!sending" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            <div v-else class="btn-spin"></div>
          </button>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

const emit = defineEmits(['conversation-selected'])

const conversations = ref([])
const messages = ref([])
const activeConversationId = ref(null)
const sidebarLoading = ref(false)
const messagesLoading = ref(false)
const sending = ref(false)
const query = ref('')
const inputFocused = ref(false)
const textareaRef = ref(null)
const msgScrollEl = ref(null)
let pollTimers = {}
const canSend = computed(() => query.value.trim() !== '')

const loadConversations = async () => { sidebarLoading.value = true; try { const r = await fetch('/api/conversations'); if (r.ok) conversations.value = await r.json() } catch (e) { console.error(e) } finally { sidebarLoading.value = false } }
const createConversation = async () => { stopAllPolling(); activeConversationId.value = null; messages.value = []; try { const r = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New Conversation' }) }); if (r.ok) { const c = await r.json(); conversations.value.unshift(c); activeConversationId.value = c.id; emit('conversation-selected', c.id); await nextTick(); textareaRef.value?.focus() } } catch (e) { console.error(e) } }
const selectConversation = (id) => { if (id === activeConversationId.value) return; stopAllPolling(); activeConversationId.value = id; emit('conversation-selected', id); loadConversation(id) }
const loadConversation = async (id) => { if (!id) return; messagesLoading.value = true; try { const r = await fetch(`/api/conversations/${id}`); if (r.ok) { const d = await r.json(); messages.value = d.messages || []; messages.value.forEach((m, i) => { if (m.role === 'assistant' && (m.status === 'pending' || m.status === 'running') && m.prediction_id) startPolling(m.prediction_id, i) }); await nextTick(); scrollToBottom() } } catch (e) { console.error(e) } finally { messagesLoading.value = false } }

const sendMessage = async () => {
  if (!canSend.value || sending.value) return
  const text = query.value.trim(); query.value = ''; resetTextarea()
  if (!activeConversationId.value) { try { const r = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: text.slice(0, 80) }) }); if (r.ok) { const c = await r.json(); conversations.value.unshift(c); activeConversationId.value = c.id; emit('conversation-selected', c.id) } else return } catch (e) { return } }
  messages.value.push({ role: 'user', content: text }); await nextTick(); scrollToBottom()
  sending.value = true
  try {
    const r = await fetch(`/api/conversations/${activeConversationId.value}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text }) })
    if (r.ok) {
      const d = await r.json()
      const am = { role: 'assistant', status: d.status || 'pending', prediction_id: d.prediction_id, content: '', progress_message: 'Starting prediction...' }
      messages.value.push(am); const mi = messages.value.length - 1; await nextTick(); scrollToBottom()
      const conv = conversations.value.find(c => c.id === activeConversationId.value)
      if (conv && (conv.title === 'New Conversation' || !conv.title)) conv.title = text.slice(0, 80)
      if (d.prediction_id) startPolling(d.prediction_id, mi)
    }
  } catch (e) { messages.value.push({ role: 'assistant', status: 'error', error: 'Failed to send.' }) }
  finally { sending.value = false; await nextTick(); scrollToBottom() }
}

const startPolling = (pid, mi) => {
  if (pollTimers[pid]) return; let fails = 0
  const poll = async () => {
    try {
      const r = await fetch(`/api/predict/${pid}`); if (!r.ok) { fails++; if (fails >= 5) { messages.value[mi].status = 'error'; messages.value[mi].error = 'Server error.'; stopPolling(pid) }; return }; fails = 0; const d = await r.json()
      const m = messages.value[mi]; if (!m) { stopPolling(pid); return }
      m.status = d.status || 'pending'; m.progress_message = d.progress_message || ''
      if (d.status === 'failed') { m.status = 'error'; m.error = d.error || 'Failed.'; stopPolling(pid) }
      if (d.status === 'complete') { m.status = 'complete'; m.answers = d.answers || {}; m.content = d.answers?.main_answer || ''; m.outcomes = d.outcomes || {}; m.actor_results = d.actor_results || {}; m.num_runs = d.num_runs || 0; m.num_agents = d.num_agents || 0; m.gpu_cost = d.gpu_cost || 0; stopPolling(pid); await nextTick(); scrollToBottom() }
    } catch (e) { fails++; if (fails >= 5) { messages.value[mi].status = 'error'; messages.value[mi].error = 'Network error.'; stopPolling(pid) } }
  }
  poll(); pollTimers[pid] = setInterval(poll, 2000)
}
const stopPolling = (pid) => { if (pollTimers[pid]) { clearInterval(pollTimers[pid]); delete pollTimers[pid] } }
const stopAllPolling = () => Object.keys(pollTimers).forEach(stopPolling)

const scrollToBottom = () => { const el = msgScrollEl.value; if (el) el.scrollTop = el.scrollHeight }
const autoResize = () => { const el = textareaRef.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 160) + 'px' }
const resetTextarea = () => nextTick(() => { const el = textareaRef.value; if (el) el.style.height = 'auto' })
const formatDate = (ds) => { if (!ds) return ''; const d = new Date(ds), now = new Date(), diff = now - d; if (diff < 86400000) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); if (diff < 604800000) return d.toLocaleDateString([], { weekday: 'short' }); return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) }
const formatLabel = (l) => l.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const formatAnswer = (text) => { if (!text) return ''; return escapeHtml(text).replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>') }

onMounted(() => loadConversations())
onUnmounted(() => stopAllPolling())
</script>

<style scoped>

* { box-sizing: border-box; margin: 0; padding: 0; }

.ch-panel {
  --c-bg: #ffffff;
  --c-surface: #fafafa;
  --c-surface-2: #f4f4f5;
  --c-border: #e4e4e7;
  --c-text: #18181b;
  --c-text-2: #3f3f46;
  --c-text-muted: #a1a1aa;
  --c-accent: #b8860b;
  --c-red: #dc2626;
  --font: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono: 'IBM Plex Mono', 'SF Mono', 'Menlo', monospace;

  height: 100%; display: flex; font-family: var(--font); color: var(--c-text); background: var(--c-bg); -webkit-font-smoothing: antialiased; overflow: hidden;
}
.mono { font-family: var(--mono); }

/* Sidebar */
.ch-sidebar { width: 260px; border-right: 1px solid var(--c-border); display: flex; flex-direction: column; flex-shrink: 0; background: var(--c-surface); }
.new-btn { display: flex; align-items: center; gap: 6px; margin: 14px 12px; padding: 9px 14px; background: var(--c-text); color: #fff; border: none; border-radius: 7px; font-family: var(--font); font-size: 13px; font-weight: 500; cursor: pointer; transition: background 0.15s; }
.new-btn:hover { background: #333; }
.conv-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
.conv-item { padding: 10px 10px; border-radius: 7px; cursor: pointer; transition: background 0.12s; margin-bottom: 1px; }
.conv-item:hover { background: var(--c-surface-2); }
.conv-item.active { background: var(--c-surface-2); border-left: 2px solid var(--c-accent); }
.conv-title { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-date { font-size: 11px; color: var(--c-text-muted); margin-top: 2px; }
.conv-empty { padding: 24px 12px; font-size: 13px; color: var(--c-text-muted); text-align: center; }
.conv-loading { padding: 24px; display: flex; justify-content: center; }

.dots { display: flex; gap: 4px; }
.dots span { width: 5px; height: 5px; background: var(--c-text-muted); border-radius: 50%; animation: dotP 1s ease-in-out infinite; }
.dots span:nth-child(2) { animation-delay: 0.15s; }
.dots span:nth-child(3) { animation-delay: 0.3s; }
@keyframes dotP { 0%,80%,100% { transform: scale(0.6); opacity: 0.3; } 40% { transform: scale(1); opacity: 1; } }

/* Main */
.ch-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; }
.empty-state h2 { font-size: 16px; font-weight: 600; color: var(--c-text-muted); }
.empty-state p { font-size: 13px; color: #c4c4cc; }

/* Messages */
.msg-scroll { flex: 1; overflow-y: auto; padding: 20px 0; }
.msg-inner { max-width: 680px; margin: 0 auto; padding: 0 28px; }
.msg-loading-wrap { padding: 20px; display: flex; justify-content: center; }
.msg { margin-bottom: 24px; }
.msg-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--c-text-muted); margin-bottom: 5px; }
.msg-body { font-size: 14px; line-height: 1.7; color: var(--c-text-2); }
.msg.user .msg-body { color: var(--c-text); font-weight: 500; }
.msg-loading { display: flex; align-items: center; gap: 10px; padding: 12px 0; }
.msg-loading span { font-size: 13px; color: var(--c-text-muted); }
.spin-sm { width: 14px; height: 14px; border: 2px solid var(--c-border); border-top-color: var(--c-accent); border-radius: 50%; animation: spin 0.6s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.msg-error { color: var(--c-red); font-size: 14px; }
.msg-answer { margin-bottom: 12px; line-height: 1.7; }
.msg-answer :deep(p) { margin-bottom: 8px; }

/* Inline sections */
.inline-section { border: 1px solid var(--c-border); border-radius: 8px; padding: 16px; margin-top: 12px; margin-bottom: 8px; background: var(--c-surface); }
.inline-title { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--c-text-muted); margin-bottom: 12px; }
.bar-list { display: flex; flex-direction: column; gap: 8px; }
.bar-row { display: flex; align-items: center; gap: 10px; }
.bar-name { width: 160px; font-size: 13px; font-weight: 500; flex-shrink: 0; }
.bar-track { flex: 1; height: 18px; background: var(--c-surface-2); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--c-text); border-radius: 3px; transition: width 0.5s ease; min-width: 2px; }
.bar-pct { width: 36px; font-size: 11px; text-align: right; color: var(--c-text-2); flex-shrink: 0; }
.tbl { font-size: 13px; }
.tbl-head { display: grid; grid-template-columns: 1.3fr 1fr 1fr 0.8fr; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--c-border); font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--c-text-muted); }
.tbl-row { display: grid; grid-template-columns: 1.3fr 1fr 1fr 0.8fr; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--c-surface-2); }
.tbl-row:last-child { border-bottom: none; }
.tbl-name { font-weight: 500; }
.tbl-val { color: var(--c-text-2); font-size: 12px; }
.run-info { display: flex; gap: 16px; margin-top: 12px; font-size: 11px; color: var(--c-text-muted); }

/* Input */
.ch-input { padding: 12px 28px 16px; border-top: 1px solid var(--c-border); max-width: 680px; margin: 0 auto; width: 100%; }
.input-bar { display: flex; align-items: flex-end; gap: 6px; border: 1.5px solid var(--c-border); border-radius: 10px; padding: 6px 10px; background: var(--c-bg); transition: border-color 0.15s, box-shadow 0.15s; }
.input-bar.focused { border-color: var(--c-accent); box-shadow: 0 0 0 3px rgba(184, 134, 11, 0.06); }
.clip-btn { background: none; border: none; color: var(--c-text-muted); cursor: pointer; padding: 4px; display: flex; border-radius: 4px; flex-shrink: 0; }
.clip-btn:hover { color: var(--c-text-2); }
.text-input { flex: 1; border: none; outline: none; resize: none; font-family: var(--font); font-size: 13px; line-height: 1.5; color: var(--c-text); background: transparent; min-height: 22px; max-height: 160px; }
.text-input::placeholder { color: #c4c4cc; }
.send-btn { width: 30px; height: 30px; border-radius: 50%; background: var(--c-text); border: none; color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: background 0.15s; }
.send-btn:hover:not(:disabled) { background: #444; }
.send-btn:disabled { background: var(--c-border); color: var(--c-text-muted); cursor: default; }
.btn-spin { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,0.25); border-top-color: #fff; border-radius: 50%; animation: spin 0.6s linear infinite; }

.conv-list::-webkit-scrollbar, .msg-scroll::-webkit-scrollbar { width: 5px; }
.conv-list::-webkit-scrollbar-thumb, .msg-scroll::-webkit-scrollbar-thumb { background: var(--c-border); border-radius: 3px; }

@media (max-width: 768px) {
  .ch-sidebar { width: 200px; }
  .msg-inner { padding: 0 16px; }
  .ch-input { padding: 10px 16px 14px; }
  .bar-name { width: 100px; font-size: 12px; }
}
</style>
