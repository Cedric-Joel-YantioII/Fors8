<template>
  <div class="geo-sim-panel">
    <!-- Escalation Meter -->
    <div class="escalation-section">
      <div class="section-header">
        <span class="section-icon">&#9888;</span>
        <span class="section-title">Escalation Level</span>
        <span class="escalation-value" :class="escalationClass">{{ escalationLevel }}/10</span>
      </div>
      <div class="escalation-bar">
        <div class="escalation-fill" :style="{ width: (escalationLevel * 10) + '%' }" :class="escalationClass"></div>
        <div class="escalation-markers">
          <span v-for="n in 10" :key="n" class="marker" :class="{ active: n <= escalationLevel }"></span>
        </div>
      </div>
      <div class="phase-indicator">
        <span class="phase-label">Phase:</span>
        <span class="phase-value" :class="'phase-' + currentPhase">{{ currentPhase }}</span>
      </div>
    </div>

    <!-- Global Indicators -->
    <div class="indicators-grid">
      <div class="indicator">
        <span class="ind-label">Oil Price</span>
        <span class="ind-value mono">${{ oilPrice.toFixed(1) }}</span>
      </div>
      <div class="indicator">
        <span class="ind-label">Round</span>
        <span class="ind-value mono">{{ currentRound }}/{{ totalRounds }}</span>
      </div>
      <div class="indicator">
        <span class="ind-label">Hormuz</span>
        <span class="ind-value" :class="hormuzOpen ? 'status-open' : 'status-closed'">
          {{ hormuzOpen ? 'OPEN' : 'CLOSED' }}
        </span>
      </div>
      <div class="indicator">
        <span class="ind-label">Bab el-Mandeb</span>
        <span class="ind-value" :class="mandebOpen ? 'status-open' : 'status-closed'">
          {{ mandebOpen ? 'OPEN' : 'THREAT' }}
        </span>
      </div>
    </div>

    <!-- Action Domain Breakdown -->
    <div class="domain-breakdown">
      <div class="section-header">
        <span class="section-title">Actions by Domain</span>
      </div>
      <div class="domain-bars">
        <div class="domain-row" v-for="domain in domainStats" :key="domain.name">
          <span class="domain-name">{{ domain.name }}</span>
          <div class="domain-bar-container">
            <div class="domain-bar-fill" :style="{ width: domain.pct + '%' }" :class="'domain-' + domain.key"></div>
          </div>
          <span class="domain-count mono">{{ domain.count }}</span>
        </div>
      </div>
    </div>

    <!-- Recent Actions Feed -->
    <div class="action-feed">
      <div class="section-header">
        <span class="section-title">Geopolitical Action Feed</span>
      </div>
      <div class="feed-list">
        <div v-for="(action, idx) in recentActions" :key="idx" class="feed-item" :class="'domain-border-' + action.action_domain">
          <div class="feed-header">
            <span class="feed-actor">{{ action.agent_name }}</span>
            <span class="feed-round">R{{ action.round_num }}</span>
          </div>
          <div class="feed-action">
            <span class="feed-type">{{ formatActionType(action.action_type) }}</span>
            <span v-if="action.target_name" class="feed-target">&rarr; {{ action.target_name }}</span>
          </div>
          <div v-if="action.result" class="feed-result">{{ action.result }}</div>
          <div v-if="action.escalation_delta !== 0" class="feed-escalation" :class="action.escalation_delta > 0 ? 'esc-up' : 'esc-down'">
            {{ action.escalation_delta > 0 ? '+' : '' }}{{ action.escalation_delta }} escalation
          </div>
        </div>
        <div v-if="recentActions.length === 0" class="feed-empty">
          Waiting for simulation to start...
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'GeoSimPanel',
  props: {
    runStatus: {
      type: Object,
      default: () => ({})
    }
  },
  computed: {
    escalationLevel() {
      return this.runStatus.escalation_level || 5
    },
    escalationClass() {
      const level = this.escalationLevel
      if (level <= 3) return 'esc-low'
      if (level <= 5) return 'esc-medium'
      if (level <= 7) return 'esc-high'
      return 'esc-critical'
    },
    currentPhase() {
      return this.runStatus.current_phase || 'crisis'
    },
    oilPrice() {
      return this.runStatus.world_state_snapshot?.oil_price || 119.0
    },
    currentRound() {
      return this.runStatus.current_round || 0
    },
    totalRounds() {
      return this.runStatus.total_rounds || 30
    },
    hormuzOpen() {
      return this.runStatus.world_state_snapshot?.strait_of_hormuz_open ?? false
    },
    mandebOpen() {
      return this.runStatus.world_state_snapshot?.bab_el_mandeb_open ?? true
    },
    domainStats() {
      const domains = [
        { key: 'military', name: 'Military', count: this.runStatus.total_military_actions || 0 },
        { key: 'diplomatic', name: 'Diplomatic', count: this.runStatus.total_diplomatic_actions || 0 },
        { key: 'economic', name: 'Economic', count: this.runStatus.total_economic_actions || 0 },
        { key: 'intelligence', name: 'Intelligence', count: this.runStatus.total_intelligence_actions || 0 },
        { key: 'proxy', name: 'Proxy', count: this.runStatus.total_proxy_actions || 0 },
        { key: 'info', name: 'Info War', count: this.runStatus.total_info_actions || 0 },
      ]
      const max = Math.max(...domains.map(d => d.count), 1)
      return domains.map(d => ({ ...d, pct: (d.count / max) * 100 }))
    },
    recentActions() {
      return (this.runStatus.recent_actions || []).slice(0, 20)
    }
  },
  methods: {
    formatActionType(type) {
      return (type || '').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
    }
  }
}
</script>

<style scoped>
.geo-sim-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  font-size: 13px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.section-title {
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
}

.section-icon {
  font-size: 14px;
}

/* Escalation Meter */
.escalation-value {
  margin-left: auto;
  font-weight: 700;
  font-size: 16px;
  font-family: 'SF Mono', monospace;
}

.escalation-bar {
  position: relative;
  height: 8px;
  background: #1e293b;
  border-radius: 4px;
  overflow: hidden;
}

.escalation-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}

.esc-low { color: #22c55e; }
.esc-low.escalation-fill { background: #22c55e; }
.esc-medium { color: #eab308; }
.esc-medium.escalation-fill { background: #eab308; }
.esc-high { color: #f97316; }
.esc-high.escalation-fill { background: #f97316; }
.esc-critical { color: #ef4444; }
.esc-critical.escalation-fill { background: #ef4444; }

.escalation-markers {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-between;
  padding: 0 2px;
}

.marker {
  width: 2px;
  height: 8px;
  background: rgba(255,255,255,0.1);
}

.marker.active {
  background: rgba(255,255,255,0.3);
}

.phase-indicator {
  margin-top: 6px;
  display: flex;
  gap: 6px;
  align-items: center;
}

.phase-label {
  color: #64748b;
  font-size: 11px;
}

.phase-value {
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 4px;
}

.phase-tensions { background: #1e3a2f; color: #22c55e; }
.phase-crisis { background: #3b2f1e; color: #eab308; }
.phase-conflict { background: #3b1e1e; color: #f97316; }
.phase-escalation-critical { background: #4c1e1e; color: #ef4444; }
.phase-de-escalation { background: #1e2a3b; color: #3b82f6; }

/* Indicators Grid */
.indicators-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.indicator {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ind-label {
  font-size: 10px;
  text-transform: uppercase;
  color: #64748b;
  letter-spacing: 0.5px;
}

.ind-value {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}

.mono { font-family: 'SF Mono', 'Fira Code', monospace; }

.status-open { color: #22c55e; }
.status-closed { color: #ef4444; }

/* Domain Breakdown */
.domain-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.domain-name {
  width: 80px;
  font-size: 11px;
  color: #94a3b8;
}

.domain-bar-container {
  flex: 1;
  height: 6px;
  background: #1e293b;
  border-radius: 3px;
  overflow: hidden;
}

.domain-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.domain-military { background: #ef4444; }
.domain-diplomatic { background: #3b82f6; }
.domain-economic { background: #eab308; }
.domain-intelligence { background: #8b5cf6; }
.domain-proxy { background: #f97316; }
.domain-info { background: #06b6d4; }

.domain-count {
  width: 30px;
  text-align: right;
  font-size: 11px;
  color: #94a3b8;
}

/* Action Feed */
.feed-list {
  max-height: 400px;
  overflow-y: auto;
}

.feed-item {
  padding: 8px 10px;
  border-left: 3px solid #1e293b;
  margin-bottom: 6px;
  background: #0f172a;
  border-radius: 0 4px 4px 0;
}

.domain-border-military { border-left-color: #ef4444; }
.domain-border-diplomatic { border-left-color: #3b82f6; }
.domain-border-economic { border-left-color: #eab308; }
.domain-border-intelligence { border-left-color: #8b5cf6; }
.domain-border-proxy { border-left-color: #f97316; }
.domain-border-information { border-left-color: #06b6d4; }
.domain-border-passive { border-left-color: #64748b; }

.feed-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 2px;
}

.feed-actor {
  font-weight: 600;
  font-size: 12px;
  color: #e2e8f0;
}

.feed-round {
  font-size: 10px;
  color: #64748b;
  font-family: monospace;
}

.feed-action {
  font-size: 12px;
  color: #94a3b8;
}

.feed-type {
  color: #cbd5e1;
}

.feed-target {
  color: #f97316;
}

.feed-result {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

.feed-escalation {
  font-size: 10px;
  font-weight: 600;
  margin-top: 2px;
}

.esc-up { color: #ef4444; }
.esc-down { color: #22c55e; }

.feed-empty {
  text-align: center;
  color: #475569;
  padding: 20px;
  font-style: italic;
}
</style>
