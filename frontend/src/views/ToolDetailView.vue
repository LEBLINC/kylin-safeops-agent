<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/layouts/PageHeader.vue'
import ToolCallCard from '@/components/ToolCallCard.vue'
import RiskTag from '@/components/RiskTag.vue'
import { getToolCallDetail, getToolRegistry } from '@/api/tools'
import type { ToolCallLog, ToolDefinition } from '@/types/tool'
import { isMockEnabled } from '@/api/mock'

const route = useRoute()
const param = computed(() => String(route.params.callId))

// call_id mode
const call = ref<ToolCallLog | null>(null)

// tool_name mode
const toolDef = ref<ToolDefinition | null>(null)
const allTools = ref<ToolDefinition[]>([])

const isCallId = computed(() => /^[0-9a-f-]{32,}$/.test(param.value) || param.value.startsWith('call_'))

async function loadCallDetail() {
  try {
    call.value = await getToolCallDetail(param.value)
  } catch {
    if (!isMockEnabled()) { call.value = null; return }
    call.value = {
      call_id: param.value,
      trace_id: 'mock_trace',
      tool: 'disk.large_files',
      args: { path: '/var/log', min_size_mb: 500 },
      result: [{ path: '/var/log/app.log', size: '18GB' }],
      status: 'success',
      duration_ms: 1230,
      risk_level: 'R1'
    }
  }
}

async function loadToolByName() {
  try {
    allTools.value = (await getToolRegistry()) as ToolDefinition[]
  } catch {
    allTools.value = []
    if (isMockEnabled()) {
      allTools.value = [
        { tool: 'system.info', description: 'System info', risk: 'R0', input_schema: { type: 'object', properties: {} } },
        { tool: 'disk.usage', description: 'Disk usage', risk: 'R0', input_schema: { type: 'object', properties: { path: { type: 'string', default: '/' } } } }
      ]
    }
  }
  toolDef.value = allTools.value.find(t => t.tool === param.value) ?? null
}

onMounted(async () => {
  if (isCallId.value) {
    await loadCallDetail()
  } else {
    await loadToolByName()
  }
})

function curlExample(tool: ToolDefinition): string {
  const props = (tool.input_schema as any)?.properties ?? {}
  const args: Record<string, unknown> = {}
  for (const key of Object.keys(props)) {
    const prop = props[key]
    if (prop?.default !== undefined) args[key] = prop.default
    else if (prop?.type === 'number' || prop?.type === 'integer') args[key] = 0
    else if (prop?.type === 'boolean') args[key] = false
    else if (prop?.type === 'array') args[key] = []
    else if (prop?.type === 'object') args[key] = {}
    else args[key] = ''
  }
  return `curl -X POST http://localhost:8000/api/tools/call \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify({ tool: tool.tool, args })}'`
}
</script>

<template>
  <div class="ks-page">
    <PageHeader
      v-if="isCallId"
      title="工具调用详情"
      subtitle="查看单次 MCP Tool 的参数、结果、耗时与风险等级"
    />
    <PageHeader
      v-else
      :title="toolDef?.tool ?? param"
      subtitle="工具注册信息 · 参数 Schema · 调用示例"
    />

    <ToolCallCard v-if="isCallId && call" :call="call" />
    <div v-else-if="isCallId && !isMockEnabled()" class="ks-page-section">
      <el-alert type="warning" show-icon :closable="false"
        title="工具调用详情加载失败"
        description="GET /api/tools/calls/{call_id} 接口返回异常，请确认 call_id 有效且后端服务正常。" />
    </div>

    <div v-if="!isCallId && toolDef" class="ks-page-section">
      <div class="tool-detail-meta">
        <div class="tool-detail-row">
          <span class="tool-detail-label">Tool</span>
          <code>{{ toolDef.tool }}</code>
        </div>
        <div class="tool-detail-row">
          <span class="tool-detail-label">Description</span>
          <span>{{ toolDef.description }}</span>
        </div>
        <div class="tool-detail-row">
          <span class="tool-detail-label">Risk</span>
          <RiskTag :level="toolDef.risk" />
        </div>
      </div>

      <h3 style="margin-top: 16px;">ToolSpec (input_schema)</h3>
      <pre class="tool-detail-schema">{{ JSON.stringify(toolDef.input_schema, null, 2) }}</pre>

      <h3 style="margin-top: 16px;">调用示例</h3>
      <pre class="tool-detail-curl">{{ curlExample(toolDef) }}</pre>

      <h3 style="margin-top: 16px;">历史调用记录</h3>
      <el-alert type="info" show-icon :closable="false"
        title="暂无数据"
        description="后端 GET /api/tools/calls?tool= 暂未实现，此处为预留栏位。" />
    </div>

    <div v-if="!isCallId && !toolDef && allTools.length > 0" class="ks-page-section">
      <el-alert type="warning" show-icon :closable="false"
        title="未找到此工具"
        :description="`工具 ${param} 不在当前注册表中。`" />
    </div>
  </div>
</template>

<style scoped>
.tool-detail-meta {
  display: grid;
  gap: 8px;
}
.tool-detail-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.tool-detail-label {
  font-weight: 600;
  min-width: 100px;
  color: var(--ks-text-secondary, #606266);
}
.tool-detail-schema,
.tool-detail-curl {
  background: var(--ks-bg-secondary, #f5f7fa);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
}
</style>