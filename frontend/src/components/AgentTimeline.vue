<script setup lang="ts">
/**
 * AgentTimeline.vue
 *
 * Agent 执行链路时间轴组件。
 *
 * 使用位置：ChatView.vue 右侧。
 * 数据来源：StreamEvent[]，即后端或 Mock 通过 SSE/WS 推送的 11 类事件。
 *
 * 组件职责：
 * - 不修改事件，只负责把事件转换成中文阶段名称和摘要；
 * - 展示意图识别、环境感知、计划生成、安全裁决、审批、执行、RCA、审计等阶段；
 * - 不展示模型私有推理链，只展示结构化摘要。
 */
import type { StreamEvent } from '@/types/chat'
import { formatTime } from '@/utils/time'
import { computed } from 'vue'

const props = defineProps<{
  events: StreamEvent[]
}>()

const stageMeta: Record<string, { title: string; status: 'success' | 'warning' | 'danger' | 'primary' | 'info' }> = {
  intent_parsed: { title: '意图识别', status: 'primary' },
  observation: { title: '环境感知', status: 'success' },
  plan_generated: { title: '计划生成', status: 'primary' },
  policy_verdict: { title: '安全裁决', status: 'warning' },
  await_approval: { title: '等待审批', status: 'warning' },
  executing: { title: '批量执行', status: 'primary' },
  tool_result: { title: '工具结果', status: 'success' },
  verified: { title: '结果验证', status: 'success' },
  rca: { title: '根因分析', status: 'primary' },
  audit_appended: { title: '审计落库', status: 'success' },
  error: { title: '异常错误', status: 'danger' }
}

function summary(event: StreamEvent) {
  const data = event.data || {}
  if (event.type === 'intent_parsed') {
    const intent = data.intent as Record<string, unknown> | undefined
    return String(intent?.justification || intent?.summary || intent?.intent || '已完成意图识别')
  }
  if (event.type === 'observation') {
    const results = (data.results as Array<Record<string, unknown>> | undefined) || []
    const untrusted = results.filter(item => item.is_untrusted).length
    return `观测结果 ${results.length} 条，其中不可信输出 ${untrusted} 条`
  }
  if (event.type === 'plan_generated') {
    const list = data.candidate_tools as unknown[] | undefined
    return `候选工具 ${list?.length || 0} 个`
  }
  if (event.type === 'policy_verdict') {
    const verdict = data.verdict as Record<string, unknown> | undefined
    const perTool = data.per_tool as unknown[] | undefined
    return `${String(verdict?.reason || verdict?.decision || '策略裁决完成')}；逐工具裁决 ${perTool?.length || 0} 条`
  }
  if (event.type === 'await_approval') {
    const tools = data.tools as Array<Record<string, unknown>> | undefined
    return `${String(data.reason || '该批工具计划需要人工确认')}；待批工具 ${tools?.length || 0} 个`
  }
  if (event.type === 'executing') return `执行工具：${((data.tools as string[]) || []).join(', ') || '-'}`
  if (event.type === 'tool_result') {
    const result = data.result as Record<string, unknown> | undefined
    return `${String(result?.tool || '工具返回结果')}${result?.is_untrusted ? '（不可信输出）' : ''}`
  }
  if (event.type === 'verified') return String(data.summary || '执行结果已验证')
  if (event.type === 'rca') return 'RCA 报告已生成'
  if (event.type === 'audit_appended') return `审计序号：${data.seq || '-'}，hash：${String(data.curr_hash || '').slice(0, 12)}...`
  if (event.type === 'error') return `${String(data.message || '执行失败')}（阶段：${data.phase || '-'}）`
  return JSON.stringify(data)
}

const normalized = computed(() =>
  props.events.map(event => ({
    ...event,
    meta: stageMeta[event.type] || { title: event.type, status: 'info' as const },
    summary: summary(event)
  }))
)
</script>

<template>
  <div class="timeline">
    <el-timeline v-if="normalized.length">
      <el-timeline-item
        v-for="event in normalized"
        :key="`${event.trace_id}-${event.type}-${event.ts}`"
        :type="event.meta.status"
        :timestamp="formatTime(event.ts)"
        placement="top"
      >
        <div class="item">
          <strong>{{ event.meta.title }}</strong>
          <p>{{ event.summary }}</p>
        </div>
      </el-timeline-item>
    </el-timeline>
    <div v-else class="placeholder">等待 Agent 事件流...</div>
  </div>
</template>

<style scoped>
.timeline {
  max-height: 540px;
  overflow: auto;
  padding-right: 6px;
}
.item strong {
  display: block;
  color: var(--ks-text);
}
.item p {
  margin: 6px 0 0;
  color: var(--ks-text-muted);
  font-size: 13px;
  line-height: 1.5;
}
.placeholder {
  min-height: 220px;
  display: grid;
  place-items: center;
  color: var(--ks-text-muted);
}
</style>
