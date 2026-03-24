<template>
  <div class="settings-container">
    <!-- Nav -->
    <nav class="settings-nav">
      <div class="nav-left">
        <router-link to="/" class="back-link">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
        </router-link>
        <span class="nav-brand">FORS8</span>
      </div>
      <div class="nav-right">
        <span class="nav-page-title">Settings</span>
      </div>
    </nav>

    <main class="settings-main">
      <div class="settings-inner">
        <!-- Header -->
        <div class="page-header">
          <h1>AI Provider</h1>
          <p>Choose how Fors8 connects to language models for simulation.</p>
        </div>

        <!-- Provider Grid (when nothing selected) -->
        <div v-if="!selectedProvider" class="provider-grid">
          <div
            v-for="p in providers"
            :key="p.id"
            class="provider-card"
            @click="selectProvider(p.id)"
          >
            <div class="card-logo" v-html="p.svg"></div>
            <div class="card-body">
              <div class="card-name">{{ p.name }}</div>
              <div class="card-desc">{{ p.desc }}</div>
            </div>
            <svg class="card-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>
          </div>
        </div>

        <!-- Expanded Provider View -->
        <div v-if="selectedProvider" class="provider-detail">
          <button class="detail-back" @click="selectedProvider = null; authMethod = null">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
            All providers
          </button>

          <div class="detail-header">
            <div class="detail-logo" v-html="currentProvider.svg"></div>
            <div>
              <h2>{{ currentProvider.name }}</h2>
              <p>{{ currentProvider.desc }}</p>
            </div>
          </div>

          <!-- Anthropic / OpenAI Auth -->
          <template v-if="selectedProvider === 'anthropic' || selectedProvider === 'openai'">
            <div class="auth-cards">
              <div class="auth-card" :class="{ active: authMethod === 'oauth' }" @click="authMethod = 'oauth'">
                <div class="auth-card-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                </div>
                <div class="auth-card-body">
                  <div class="auth-card-title">Sign in with {{ selectedProvider === 'anthropic' ? 'Claude' : 'ChatGPT' }}</div>
                  <div class="auth-card-sub">Use your existing subscription — no extra cost</div>
                </div>
                <span class="free-tag">FREE</span>
              </div>
              <div class="auth-card" :class="{ active: authMethod === 'api_key' }" @click="authMethod = 'api_key'">
                <div class="auth-card-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                </div>
                <div class="auth-card-body">
                  <div class="auth-card-title">API Key</div>
                  <div class="auth-card-sub">Pay per token — enter your API key</div>
                </div>
              </div>
            </div>

            <!-- OAuth flow -->
            <div v-if="authMethod === 'oauth'" class="auth-form">
              <button class="btn-primary" @click="startOAuthLogin" :disabled="oauthLoading">
                {{ oauthLoading ? 'Opening browser...' : `Sign in with ${selectedProvider === 'anthropic' ? 'Claude' : 'ChatGPT'}` }}
              </button>
              <div v-if="oauthStatus" class="status-msg" :class="oauthStatus.authenticated ? 'success' : 'error'">
                {{ oauthStatus.authenticated ? `Connected as ${oauthStatus.user_email || 'user'}` : 'Not connected' }}
              </div>
            </div>

            <!-- API Key form -->
            <div v-if="authMethod === 'api_key'" class="auth-form">
              <div class="form-group">
                <label>API Key</label>
                <input type="password" v-model="apiKey" :placeholder="selectedProvider === 'anthropic' ? 'sk-ant-api03-...' : 'sk-...'" />
              </div>
              <div class="form-group">
                <label>Base URL <span class="optional">(optional)</span></label>
                <input type="text" v-model="baseUrl" :placeholder="selectedProvider === 'anthropic' ? 'https://api.anthropic.com/v1' : 'https://api.openai.com/v1'" />
              </div>
              <button class="btn-primary" @click="saveApiKey">Save</button>
            </div>
          </template>

          <!-- OpenRouter -->
          <template v-if="selectedProvider === 'openrouter'">
            <div class="auth-form" style="margin-bottom: 32px;">
              <div class="form-group">
                <label>OpenRouter API Key</label>
                <input type="password" v-model="openrouterKey" placeholder="sk-or-v1-..." />
              </div>
              <button class="btn-primary" @click="saveOpenRouterKey" style="margin-top:8px">Save Key</button>
            </div>

            <div class="model-section">
              <div class="model-search-wrap">
                <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
                <input type="text" v-model="modelSearch" placeholder="Search models..." class="model-search" />
              </div>
              <div class="model-list">
                <div
                  v-for="m in filteredModels"
                  :key="m.id"
                  class="model-row"
                  :class="{ selected: selectedModel === m.id }"
                  @click="selectModel(m.id)"
                >
                  <div class="model-info">
                    <span class="model-name">{{ m.name }}</span>
                    <span class="model-provider">{{ m.provider }}</span>
                  </div>
                  <div class="model-right">
                    <span v-if="m.free" class="model-free">FREE</span>
                    <span v-else class="model-price">{{ m.price }}</span>
                    <span class="model-ctx">{{ m.context }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- Self-Hosted / Vast.ai -->
          <template v-if="selectedProvider === 'vllm'">
            <div class="vastai-cta">
              <span>Need a Vast.ai account?</span>
              <a href="https://cloud.vast.ai/" target="_blank" class="vastai-link">
                Sign up at cloud.vast.ai
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              </a>
            </div>
            <div class="auth-form" style="margin-bottom:24px">
              <div class="form-group">
                <label>Vast.ai API Key <span class="optional">(for auto-provisioning)</span></label>
                <input type="password" v-model="vastaiKey" placeholder="Your Vast.ai API key" />
              </div>
              <div class="form-divider"><span>or</span></div>
              <div class="form-group">
                <label>vLLM Endpoint <span class="optional">(if self-managed)</span></label>
                <input type="text" v-model="vllmEndpoint" placeholder="http://your-gpu-ip:8000/v1" />
              </div>
            </div>

            <h3 class="subsection-title">Model</h3>
            <div class="gpu-model-list">
              <div
                v-for="m in vllmModels"
                :key="m.id"
                class="gpu-model-card"
                :class="{ selected: selectedVllmModel === m.id }"
                @click="selectedVllmModel = m.id"
              >
                <div class="gpu-model-name">{{ m.name }}</div>
                <div class="gpu-model-meta">{{ m.gpus }} &middot; ${{ m.costPerHour }}/hr</div>
                <div class="gpu-model-note">{{ m.strengths }}</div>
              </div>
            </div>

            <h3 class="subsection-title">Scale</h3>
            <div class="scale-grid">
              <div class="form-group">
                <label>GPUs</label>
                <select v-model.number="numGpus">
                  <option :value="1">1</option>
                  <option :value="2">2</option>
                  <option :value="4">4</option>
                  <option :value="8">8</option>
                </select>
              </div>
              <div class="form-group">
                <label>Agents</label>
                <select v-model.number="agentsPerRun">
                  <option :value="1000">1K</option>
                  <option :value="10000">10K</option>
                  <option :value="100000">100K</option>
                  <option :value="1000000">1M</option>
                </select>
              </div>
              <div class="form-group">
                <label>Parallel Runs</label>
                <select v-model.number="parallelRuns">
                  <option :value="1">1</option>
                  <option :value="5">5</option>
                  <option :value="10">10</option>
                </select>
              </div>
            </div>

            <div class="cost-box">
              <div class="cost-label">Estimated cost</div>
              <div class="cost-value">${{ estimatedCost.toFixed(2) }}</div>
              <div class="cost-detail">{{ estimatedTime }} min &middot; {{ totalCalls.toLocaleString() }} LLM calls</div>
            </div>

            <button class="btn-primary" @click="provisionGpus" :disabled="!vastaiKey && !vllmEndpoint">
              {{ vllmEndpoint ? 'Connect' : 'Launch GPUs' }}
            </button>
          </template>
        </div>
      </div>
    </main>
  </div>
</template>

<script>
export default {
  name: 'SettingsPage',
  data() {
    return {
      selectedProvider: null,
      authMethod: null,
      oauthLoading: false,
      oauthStatus: null,
      apiKey: '',
      baseUrl: '',
      openrouterKey: '',
      modelSearch: '',
      selectedModel: 'openrouter/free',
      vastaiKey: '',
      vllmEndpoint: '',
      selectedVllmModel: 'qwen2.5-72b',
      numGpus: 4,
      agentsPerRun: 100000,
      parallelRuns: 10,

      providers: [
        {
          id: 'anthropic', name: 'Anthropic', desc: 'Claude Opus & Sonnet — sign in or API key',
          svg: `<svg fill="#000" fill-rule="evenodd" viewBox="0 0 24 24" width="22" xmlns="http://www.w3.org/2000/svg"><path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017l-1.344 3.46H0L6.57 3.522zm4.132 9.959L8.453 7.687 6.205 13.48H10.7z"></path></svg>`
        },
        {
          id: 'openai', name: 'OpenAI', desc: 'GPT-4o & o3 — sign in or API key',
          svg: `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 256 260"><path d="M239.184 106.203a64.716 64.716 0 0 0-5.576-53.103C219.452 28.459 191 15.784 163.213 21.74A65.586 65.586 0 0 0 52.096 45.22a64.716 64.716 0 0 0-43.23 31.36c-14.31 24.602-11.061 55.634 8.033 76.74a64.665 64.665 0 0 0 5.525 53.102c14.174 24.65 42.644 37.324 70.446 31.36a64.72 64.72 0 0 0 48.754 21.744c28.481.025 53.714-18.361 62.414-45.481a64.767 64.767 0 0 0 43.229-31.36c14.137-24.558 10.875-55.423-8.083-76.483Zm-97.56 136.338a48.397 48.397 0 0 1-31.105-11.255l1.535-.87 51.67-29.825a8.595 8.595 0 0 0 4.247-7.367v-72.85l21.845 12.636c.218.111.37.32.409.563v60.367c-.056 26.818-21.783 48.545-48.601 48.601Zm-104.466-44.61a48.345 48.345 0 0 1-5.781-32.589l1.534.921 51.722 29.826a8.339 8.339 0 0 0 8.441 0l63.181-36.425v25.221a.87.87 0 0 1-.358.665l-52.335 30.184c-23.257 13.398-52.97 5.431-66.404-17.803ZM23.549 85.38a48.499 48.499 0 0 1 25.58-21.333v61.39a8.288 8.288 0 0 0 4.195 7.316l62.874 36.272-21.845 12.636a.819.819 0 0 1-.767 0L41.353 151.53c-23.211-13.454-31.171-43.144-17.804-66.405v.256Zm179.466 41.695-63.08-36.63L161.73 77.86a.819.819 0 0 1 .768 0l52.233 30.184a48.6 48.6 0 0 1-7.316 87.635v-61.391a8.544 8.544 0 0 0-4.4-7.213Zm21.742-32.69-1.535-.922-51.619-30.081a8.39 8.39 0 0 0-8.492 0L99.98 99.808V74.587a.716.716 0 0 1 .307-.665l52.233-30.133a48.652 48.652 0 0 1 72.236 50.391v.205ZM88.061 139.097l-21.845-12.585a.87.87 0 0 1-.41-.614V65.685a48.652 48.652 0 0 1 79.757-37.346l-1.535.87-51.67 29.825a8.595 8.595 0 0 0-4.246 7.367l-.051 72.697Zm11.868-25.58 28.138-16.217 28.188 16.218v32.434l-28.086 16.218-28.188-16.218-.052-32.434Z"/></svg>`
        },
        {
          id: 'openrouter', name: 'OpenRouter', desc: '30+ frontier models — free and paid options',
          svg: `<svg width="22" height="22" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg" fill="#111" stroke="#111"><g clip-path="url(#c)"><path d="M3 248.945C18 248.945 76 236 106 219C136 202 136 202 198 158C276.497 102.293 332 120.945 423 120.945" stroke-width="90" fill="none"/><path d="M511 121.5L357.25 210.268L357.25 32.7324L511 121.5Z"/><path d="M0 249C15 249 73 261.945 103 278.945C133 295.945 133 295.945 195 339.945C273.497 395.652 329 377 420 377" stroke-width="90" fill="none"/><path d="M508 376.445L354.25 287.678L354.25 465.213L508 376.445Z"/></g></svg>`
        },
        {
          id: 'vllm', name: 'Self-Hosted GPU', desc: 'Vast.ai + vLLM — run 100K+ agents for ~$5',
          svg: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#111" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3m6-3v3M9 20v3m6-3v3M20 9h3M20 15h3M1 9h3M1 15h3"/></svg>`
        },
      ],

      vllmModels: [
        { id: 'qwen2.5-72b', name: 'Qwen 2.5 72B', gpus: '2–4× A100', costPerHour: 3.0, strengths: 'Best JSON reliability. Recommended.' },
        { id: 'deepseek-v3', name: 'DeepSeek V3', gpus: '4–8× A100', costPerHour: 6.0, strengths: 'Best reasoning accuracy.' },
        { id: 'llama3-70b', name: 'Llama 3.1 70B', gpus: '2–4× A100', costPerHour: 3.0, strengths: 'Balanced reasoning and speed.' },
        { id: 'qwen2.5-14b', name: 'Qwen 2.5 14B', gpus: '1× RTX 4090', costPerHour: 0.4, strengths: 'Fastest. Cheapest. Good for mass agents.' },
      ],

      openrouterModels: [
        { id: 'google/gemma-3-27b-it:free', name: 'Gemma 3 27B', provider: 'Google', price: '', free: true, context: '96K' },
        { id: 'mistralai/mistral-small-3.1-24b-instruct:free', name: 'Mistral Small 3.1', provider: 'Mistral', price: '', free: true, context: '96K' },
        { id: 'deepseek/deepseek-r1:free', name: 'DeepSeek R1', provider: 'DeepSeek', price: '', free: true, context: '64K' },
        { id: 'qwen/qwen3-32b:free', name: 'Qwen 3 32B', provider: 'Alibaba', price: '', free: true, context: '40K' },
        { id: 'meta-llama/llama-4-maverick:free', name: 'Llama 4 Maverick', provider: 'Meta', price: '', free: true, context: '128K' },
        { id: 'openrouter/free', name: 'Auto (Best Free)', provider: 'OpenRouter', price: '', free: true, context: 'Auto' },
        { id: 'anthropic/claude-opus-4-6', name: 'Claude Opus 4.6', provider: 'Anthropic', price: '$15/M', free: false, context: '200K' },
        { id: 'anthropic/claude-sonnet-4-6', name: 'Claude Sonnet 4.6', provider: 'Anthropic', price: '$15/M', free: false, context: '200K' },
        { id: 'openai/gpt-4o', name: 'GPT-4o', provider: 'OpenAI', price: '$10/M', free: false, context: '128K' },
        { id: 'openai/o3', name: 'o3', provider: 'OpenAI', price: '$40/M', free: false, context: '200K' },
        { id: 'google/gemini-2.5-pro', name: 'Gemini 2.5 Pro', provider: 'Google', price: '$10/M', free: false, context: '1M' },
        { id: 'deepseek/deepseek-chat-v3-0324', name: 'DeepSeek V3', provider: 'DeepSeek', price: '$0.88/M', free: false, context: '64K' },
        { id: 'qwen/qwen3-235b-a22b', name: 'Qwen 3 235B', provider: 'Alibaba', price: '$1.20/M', free: false, context: '40K' },
        { id: 'mistralai/mistral-large-2411', name: 'Mistral Large', provider: 'Mistral', price: '$6/M', free: false, context: '128K' },
        { id: 'x-ai/grok-3-beta', name: 'Grok 3', provider: 'xAI', price: '$10/M', free: false, context: '131K' },
        { id: 'meta-llama/llama-4-maverick', name: 'Llama 4 Maverick', provider: 'Meta', price: '$0.50/M', free: false, context: '128K' },
      ],
    }
  },
  computed: {
    currentProvider() {
      return this.providers.find(p => p.id === this.selectedProvider) || {}
    },
    filteredModels() {
      const q = this.modelSearch.toLowerCase()
      if (!q) return this.openrouterModels
      return this.openrouterModels.filter(m =>
        m.name.toLowerCase().includes(q) || m.provider.toLowerCase().includes(q)
      )
    },
    estimatedCost() {
      const m = this.vllmModels.find(v => v.id === this.selectedVllmModel)
      if (!m) return 0
      const calls = this.agentsPerRun * 0.1 * 10 * this.parallelRuns
      const throughput = this.selectedVllmModel === 'qwen2.5-14b' ? 700 : 300
      return (calls / throughput / 3600) * m.costPerHour * this.numGpus
    },
    estimatedTime() {
      const calls = this.agentsPerRun * 0.1 * 10 * this.parallelRuns
      const throughput = this.selectedVllmModel === 'qwen2.5-14b' ? 700 : 300
      return Math.ceil(calls / throughput / 60)
    },
    totalCalls() {
      return this.agentsPerRun * 0.1 * 10 * this.parallelRuns
    },
  },
  methods: {
    selectProvider(id) { this.selectedProvider = id; this.authMethod = null },
    selectModel(id) { this.selectedModel = id },
    async startOAuthLogin() {
      this.oauthLoading = true
      try {
        const resp = await fetch('/api/auth/login/browser', { method: 'POST' })
        this.oauthStatus = await resp.json()
      } catch (e) { this.oauthStatus = { authenticated: false } }
      this.oauthLoading = false
    },
    saveApiKey() {
      localStorage.setItem('fors8_api_key', this.apiKey)
      localStorage.setItem('fors8_base_url', this.baseUrl)
      localStorage.setItem('fors8_provider', this.selectedProvider)
      alert('Saved')
    },
    saveOpenRouterKey() {
      localStorage.setItem('fors8_api_key', this.openrouterKey)
      localStorage.setItem('fors8_base_url', 'https://openrouter.ai/api/v1')
      localStorage.setItem('fors8_model', this.selectedModel)
      alert('Saved')
    },
    provisionGpus() {
      if (this.vllmEndpoint) {
        localStorage.setItem('fors8_vllm_endpoint', this.vllmEndpoint)
        alert('Connected')
      } else {
        alert('Launching GPUs on Vast.ai...')
      }
    },
  }
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=DM+Mono:wght@400;500&display=swap');

* { box-sizing: border-box; }

.settings-container {
  min-height: 100vh;
  background: #fff;
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
  color: #111;
}

/* Nav */
.settings-nav {
  height: 56px;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-link {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  color: #555;
  transition: all 0.15s;
}

.back-link:hover {
  background: #f3f3f3;
  color: #111;
}

.nav-brand {
  font-family: 'DM Mono', monospace;
  font-weight: 500;
  font-size: 14px;
  letter-spacing: 1.5px;
  color: #111;
}

.nav-page-title {
  font-size: 13px;
  color: #999;
  font-weight: 400;
}

/* Main */
.settings-main {
  max-width: 640px;
  margin: 0 auto;
  padding: 48px 24px 80px;
}

.page-header {
  margin-bottom: 40px;
}

.page-header h1 {
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.5px;
  margin: 0 0 8px;
}

.page-header p {
  font-size: 15px;
  color: #666;
  margin: 0;
  line-height: 1.5;
}

/* Provider Grid */
.provider-grid {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: #e8e8e8;
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  overflow: hidden;
}

.provider-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  background: #fff;
  cursor: pointer;
  transition: background 0.12s;
}

.provider-card:hover {
  background: #fafafa;
}

.card-logo {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
  border-radius: 10px;
  flex-shrink: 0;
}

.card-body { flex: 1; }
.card-name { font-weight: 600; font-size: 15px; margin-bottom: 2px; }
.card-desc { font-size: 13px; color: #888; }

.card-arrow {
  color: #ccc;
  flex-shrink: 0;
  transition: transform 0.15s;
}
.provider-card:hover .card-arrow {
  transform: translateX(3px);
  color: #999;
}

/* Provider Detail */
.provider-detail {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.detail-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  color: #888;
  font-size: 13px;
  cursor: pointer;
  padding: 4px 0;
  margin-bottom: 24px;
  font-family: inherit;
  transition: color 0.15s;
}
.detail-back:hover { color: #111; }

.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
}

.detail-logo {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
  border-radius: 12px;
}

.detail-header h2 {
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 2px;
  letter-spacing: -0.3px;
}

.detail-header p {
  font-size: 14px;
  color: #888;
  margin: 0;
}

/* Auth Cards */
.auth-cards {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: #e8e8e8;
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 24px;
}

.auth-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  background: #fff;
  cursor: pointer;
  transition: background 0.12s;
}
.auth-card:hover { background: #fafafa; }
.auth-card.active { background: #f7f7ff; }

.auth-card-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f3f3;
  border-radius: 10px;
  color: #555;
}
.auth-card.active .auth-card-icon { background: #eef; color: #333; }

.auth-card-body { flex: 1; }
.auth-card-title { font-weight: 500; font-size: 14px; }
.auth-card-sub { font-size: 12px; color: #999; margin-top: 1px; }

.free-tag {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: #16a34a;
  background: #f0fdf4;
  padding: 3px 8px;
  border-radius: 4px;
}

/* Forms */
.auth-form { margin-top: 4px; }

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #444;
  margin-bottom: 6px;
}

.optional {
  font-weight: 400;
  color: #aaa;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  background: #fff;
  color: #111;
  transition: border-color 0.15s;
  outline: none;
}

.form-group input:focus,
.form-group select:focus {
  border-color: #111;
}

.form-group input::placeholder {
  color: #bbb;
}

.form-divider {
  text-align: center;
  position: relative;
  margin: 20px 0;
  color: #ccc;
  font-size: 12px;
}
.form-divider::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: #eee;
}
.form-divider span {
  background: #fff;
  padding: 0 12px;
  position: relative;
}

.btn-primary {
  width: 100%;
  padding: 11px 20px;
  background: #111;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s;
}
.btn-primary:hover { background: #333; }
.btn-primary:disabled { background: #ddd; color: #999; cursor: not-allowed; }

.status-msg {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
}
.status-msg.success { background: #f0fdf4; color: #16a34a; }
.status-msg.error { background: #fef2f2; color: #dc2626; }

/* Model Search */
.model-section { margin-top: 8px; }

.model-search-wrap {
  position: relative;
  margin-bottom: 12px;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
}

.model-search {
  width: 100%;
  padding: 10px 14px 10px 38px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}
.model-search:focus { border-color: #111; }

.model-list {
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  overflow: hidden;
  max-height: 420px;
  overflow-y: auto;
}

.model-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f0;
  transition: background 0.1s;
}
.model-row:last-child { border-bottom: none; }
.model-row:hover { background: #fafafa; }
.model-row.selected { background: #f7f7ff; }

.model-info { display: flex; flex-direction: column; gap: 1px; }
.model-name { font-size: 14px; font-weight: 500; }
.model-provider { font-size: 12px; color: #999; }

.model-right { display: flex; align-items: center; gap: 10px; }
.model-free {
  font-size: 10px;
  font-weight: 700;
  color: #16a34a;
  background: #f0fdf4;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: 0.3px;
}
.model-price { font-size: 12px; color: #888; font-family: 'DM Mono', monospace; }
.model-ctx { font-size: 11px; color: #bbb; }

/* GPU Models */
.subsection-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 12px;
  color: #333;
}

.gpu-model-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 28px;
}

.gpu-model-card {
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.12s;
}
.gpu-model-card:hover { border-color: #ccc; }
.gpu-model-card.selected { border-color: #111; background: #fafafa; }

.gpu-model-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.gpu-model-meta { font-size: 12px; color: #888; }
.gpu-model-note { font-size: 11px; color: #aaa; margin-top: 6px; }

.scale-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  margin-bottom: 24px;
}

.cost-box {
  background: #f9f9f9;
  border: 1px solid #eee;
  border-radius: 10px;
  padding: 20px;
  text-align: center;
  margin-bottom: 16px;
}

.cost-label { font-size: 12px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; }
.cost-value { font-size: 32px; font-weight: 700; font-family: 'DM Mono', monospace; margin: 4px 0; }
.cost-detail { font-size: 12px; color: #aaa; }

/* Vast.ai CTA */
.vastai-cta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: #f9f9f9;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  margin-bottom: 20px;
  font-size: 13px;
  color: #666;
}

.vastai-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #111;
  font-weight: 500;
  text-decoration: none;
  transition: color 0.15s;
}
.vastai-link:hover { color: #3b82f6; }
</style>
