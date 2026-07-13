<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import { buildApiUrl, request } from '@/api/request'

/**
 * SettingsView.vue
 *
 * 系统设置页面。
 *
 * 当前定位：只读配置展示。
 *
 * 页面作用：
 * - 展示当前前端使用的 API 地址；
 * - 展示事件流模式 SSE/WS；
 * - 展示 LLM 配置健康状态。
 *
 * 为什么先做只读：
 * - 避免演示阶段误修改生产策略；
 * - 真正的模型配置、安全策略编辑需要权限控制，当前版本不展开。
 */

/** API 基础地址。来自 .env.development 或 .env.production。 */
const apiBase = import.meta.env.VITE_API_BASE_URL || '/api via vite proxy'

/** 事件流模式。当前建议使用 sse + REST 审批。 */
const streamMode = import.meta.env.VITE_STREAM_MODE || 'sse'

/** LLM 健康检查响应。 */
interface LLMHealth {
  provider: 'fixture' | 'real'
  model: string
  base_url: string
  api_key_configured: boolean
  rate_limit_per_minute: number
  token_cap: number
  status: string
}

const llmHealth = ref<LLMHealth | null>(null)
/** 请求失败时置 true，用于降级展示。 */
const llmHealthError = ref(false)

/** probe 失败事件记录。来自 /api/llm/health/events SSE 订阅。 */
interface ProbeFailEvent {
  ts: number
  trace_id: string
  curr_hash: string
  seq: number
}
const probeEvents = ref<ProbeFailEvent[]>([])
const probeConnected = ref(false)
let probeSource: EventSource | null = null

function connectProbeSSE() {
  const url = buildApiUrl('/api/llm/health/events')
  probeSource = new EventSource(url)

  probeSource.onopen = () => {
    probeConnected.value = true
  }

  probeSource.onmessage = (msg) => {
    if (!msg.data) return
    try {
      const evt = JSON.parse(msg.data)
      // 后端推的是 audit_appended 事件（channel "probe-watch"）
      if (evt.type === 'audit_appended' && evt.data?.phase === 'probe_failed') {
        probeEvents.value.unshift({
          ts: evt.ts || Date.now() / 1000,
          trace_id: evt.data.trace_id || '',
          curr_hash: evt.data.curr_hash || '',
          seq: evt.data.seq ?? 0
        })
        // 最多保留最近 50 条
        if (probeEvents.value.length > 50) {
          probeEvents.value = probeEvents.value.slice(0, 50)
        }
      }
    } catch {
      // 非 JSON 消息忽略
    }
  }

  probeSource.onerror = () => {
    probeConnected.value = false
    probeSource?.close()
    // 30s 后自动重连
    setTimeout(() => {
      if (probeSource && probeSource.readyState === EventSource.CLOSED) {
        connectProbeSSE()
      }
    }, 30000)
  }
}

onMounted(async () => {
  try {
    const res = await request.get('/api/llm/health')
    llmHealth.value = res as unknown as LLMHealth
  } catch {
    llmHealthError.value = true
  }

  // 订阅 probe SSE 流
  connectProbeSSE()
})

onBeforeUnmount(() => {
  probeSource?.close()
  probeSource = null
})
</script>

<template>
  <div class="ks-page">
    <PageHeader title="系统设置" subtitle="当前页面先做只读配置展示，避免误改生产策略" />

    <PageSection title="前端运行配置">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="API Base URL">{{ apiBase }}</el-descriptions-item>
        <el-descriptions-item label="事件流模式">{{ streamMode }}</el-descriptions-item>
        <el-descriptions-item label="主题">浅色数据驾驶舱</el-descriptions-item>
      </el-descriptions>
    </PageSection>

    <PageSection title="LLM 配置状态">
      <!-- 请求失败降级展示 -->
      <div v-if="llmHealthError" class="llm-health-error">
        <span class="status-dot error" />
        LLM 端点不可达
      </div>

      <el-descriptions v-else-if="llmHealth" :column="1" border>
        <el-descriptions-item label="Provider">
          <el-tag :type="llmHealth.provider === 'real' ? 'success' : 'info'" size="small">
            {{ llmHealth.provider }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="模型">{{ llmHealth.model }}</el-descriptions-item>
        <el-descriptions-item label="Base URL">{{ llmHealth.base_url }}</el-descriptions-item>
        <el-descriptions-item label="API Key">
          <span class="key-status" :class="{ configured: llmHealth.api_key_configured }">
            <span class="status-dot" :class="llmHealth.api_key_configured ? 'ok' : 'error'" />
            {{ llmHealth.api_key_configured ? '已配置' : '未配置' }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="速率限制">{{ llmHealth.rate_limit_per_minute }} 次/分钟</el-descriptions-item>
        <el-descriptions-item label="Token 上限">{{ llmHealth.token_cap }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ llmHealth.status }}</el-descriptions-item>
      </el-descriptions>

      <div v-else class="llm-health-loading">加载中…</div>
    </PageSection>

    <PageSection title="LLM 连通性探测">
      <template #title>
        <div class="probe-header">
          <span>LLM 连通性探测</span>
          <span class="probe-status-dot" :class="{ connected: probeConnected }" />
          <span class="probe-status-text">{{ probeConnected ? 'SSE 已连接' : 'SSE 断开' }}</span>
        </div>
      </template>

      <div v-if="!probeEvents.length" class="probe-empty">
        <span>暂无探测失败记录</span>
        <span class="probe-hint">probe 失败时自动推送至此</span>
      </div>

      <div v-else class="probe-list">
        <div v-for="(evt, idx) in probeEvents" :key="idx" class="probe-row">
          <span class="probe-time">{{ new Date(evt.ts * 1000).toLocaleTimeString() }}</span>
          <el-tag type="danger" size="small">probe_failed</el-tag>
          <code class="probe-trace">{{ evt.trace_id }}</code>
          <span class="probe-hash" :title="evt.curr_hash">{{ evt.curr_hash.slice(0, 12) }}…</span>
        </div>
      </div>
    </PageSection>
  </div>
</template>

<style scoped>
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.status-dot.ok { background: #22c55e; }
.status-dot.error { background: #ef4444; }

.key-status {
  display: inline-flex;
  align-items: center;
  font-size: 13px;
}
.key-status.configured { color: #22c55e; }

.llm-health-error {
  display: flex;
  align-items: center;
  color: #ef4444;
  font-size: 14px;
}
.llm-health-loading {
  color: var(--ks-text-muted, #6b7280);
  font-size: 14px;
}

/* probe SSE 面板 */
.probe-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.probe-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
  flex-shrink: 0;
}
.probe-status-dot.connected {
  background: #22c55e;
}

.probe-status-text {
  font-size: 12px;
  font-weight: 400;
  color: var(--ks-text-muted);
  margin-left: 4px;
}

.probe-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 20px;
  color: var(--ks-text-muted);
  font-size: 14px;
}

.probe-hint {
  font-size: 12px;
  color: #94a3b8;
}

.probe-list {
  display: grid;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
}

.probe-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(239, 68, 68, 0.18);
  border-radius: 8px;
  background: rgba(254, 242, 242, 0.6);
  font-size: 13px;
}

.probe-time {
  color: var(--ks-text-muted);
  font-family: monospace;
  white-space: nowrap;
}

.probe-trace {
  font-size: 12px;
  color: #dc2626;
  background: rgba(220, 38, 38, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.probe-hash {
  font-size: 11px;
  color: #94a3b8;
  font-family: monospace;
  margin-left: auto;
}
</style>
