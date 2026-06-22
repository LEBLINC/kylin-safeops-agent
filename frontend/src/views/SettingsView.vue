<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import { request } from '@/api/request'

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

onMounted(async () => {
  try {
    const res = await request.get('/api/llm/health')
    llmHealth.value = res as unknown as LLMHealth
  } catch {
    llmHealthError.value = true
  }
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
</style>
