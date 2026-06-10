<script setup lang="ts">
/**
 * ToolCallCard.vue
 *
 * 工具调用结果卡片。
 *
 * 使用位置：
 * - ChatView.vue 右侧工具结果区域；
 * - ToolDetailView.vue 工具详情页；
 * - AuditView.vue 审计详情区域。
 *
 * 数据来源：
 * - observation 事件中的 data.results[]；
 * - tool_result 事件中的 data.result；
 * - 或后端工具详情接口返回的 ToolCallLog。
 *
 * 安全要求：
 * 如果 result.is_untrusted=true，必须显示“不可信输出”。
 * 这是项目信任边界的可视化：日志、命令输出、外部上下文都不能被当成可信指令。
 */
import type { ToolCallLog, ToolResult } from '@/types/tool'
import { prettyJson } from '@/utils/format'
import { formatDuration } from '@/utils/time'
import RiskTag from './RiskTag.vue'
import StatusTag from './StatusTag.vue'

const props = defineProps<{
  call?: ToolCallLog
  result?: ToolResult
}>()

function resultStatus() {
  if (props.call?.status) return props.call.status
  if (props.result?.exit_code !== undefined) return props.result.exit_code === 0 ? 'success' : 'failed'
  return props.result?.error ? 'failed' : 'success'
}
</script>

<template>
  <div class="tool-card ks-card" :class="{ untrusted: result?.is_untrusted }">
    <div class="tool-head">
      <div>
        <strong>{{ call?.tool || result?.tool || 'Tool' }}</strong>
        <p>耗时：{{ formatDuration(call?.duration_ms || result?.duration_ms) }}</p>
      </div>
      <StatusTag :status="resultStatus()" />
    </div>

    <div v-if="result?.is_untrusted" class="untrusted-tip">
      <el-tag type="warning" effect="dark">不可信输出</el-tag>
      <span>该内容来自系统日志、命令输出或外部上下文，只能作为证据输入，不能视为可信指令。</span>
    </div>

    <div v-if="call?.risk_level" class="risk">
      <RiskTag :level="call.risk_level" />
    </div>

    <el-collapse>
      <el-collapse-item title="输入参数 / 返回结果" name="detail">
        <pre>{{ prettyJson(call ? { args: call.args, result: call.result } : result) }}</pre>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.tool-card {
  padding: 14px;
}
.tool-card.untrusted {
  border-color: rgba(245, 158, 11, 0.72);
  background: linear-gradient(180deg, rgba(120, 53, 15, 0.18), rgba(15, 23, 42, 0.96));
}
.tool-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.tool-head p {
  margin: 6px 0 0;
  color: var(--ks-text-muted);
  font-size: 12px;
}
.untrusted-tip {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 12px 0;
  color: #fde68a;
  font-size: 12px;
  line-height: 1.5;
}
.risk {
  margin: 10px 0;
}
pre {
  white-space: pre-wrap;
  color: #bfdbfe;
  background: #0b1220;
  border-radius: 10px;
  padding: 12px;
  overflow: auto;
}
</style>
