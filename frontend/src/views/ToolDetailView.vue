<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/layouts/PageHeader.vue'
import ToolCallCard from '@/components/ToolCallCard.vue'
import { getToolCallDetail } from '@/api/tools'
import type { ToolCallLog } from '@/types/tool'

/**
 * ToolDetailView.vue
 *
 * 工具调用详情页面。
 *
 * 页面作用：
 * - 展示某一次 MCP Tool 调用的参数、结果、耗时、风险等级；
 * - 适合从审计日志或工具调用列表跳转查看。
 *
 * 数据来源：
 * - 路由参数 route.params.callId；
 * - api/tools.ts 的 getToolCallDetail(callId)。
 *
 * 与 stream.py 的关系：
 * - stream.py 的 tool_result 事件只推送实时 ToolResult；
 * - 本页面的 ToolCallLog 是事后详情接口数据，不完全由 stream.py 规定。
 */
const route = useRoute()

/** 当前工具调用详情。为空时页面不展示 ToolCallCard。 */
const call = ref<ToolCallLog | null>(null)

/**
 * 页面初始化时根据路由参数加载工具调用详情。
 *
 * 流程：
 * 1. 从 URL /tools/:callId 取 callId；
 * 2. 请求 GET /api/tools/calls/{callId}；
 * 3. 成功后赋值给 call；
 * 4. 失败时使用 mock 工具调用，保证演示页面可用。
 */
onMounted(async () => {
  const callId = String(route.params.callId)
  try {
    call.value = await getToolCallDetail(callId)
  } catch {
    call.value = {
      call_id: callId,
      trace_id: 'mock_trace',
      tool: 'disk.large_files',
      args: { path: '/var/log', min_size_mb: 500 },
      result: [{ path: '/var/log/app.log', size: '18GB' }],
      status: 'success',
      duration_ms: 1230,
      risk_level: 'R1'
    }
  }
})
</script>

<template>
  <div class="ks-page">
    <PageHeader title="工具调用详情" subtitle="查看单次 MCP Tool 的参数、结果、耗时与风险等级" />
    <ToolCallCard v-if="call" :call="call" />
  </div>
</template>
