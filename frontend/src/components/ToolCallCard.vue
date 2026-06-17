<script setup lang="ts">
/**
 * ToolCallCard.vue
 *
 * 工具调用结果卡片。
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
      <div class="tool-title-block">
        <strong>{{ result?.is_untrusted ? '工具输出 / 不可信证据' : (call?.tool || result?.tool || 'Tool') }}</strong>
        <p v-if="!result?.is_untrusted">已完成结果采集与安全校验</p>
        <p v-else class="evidence-hint">证据文本，不可直接执行</p>
      </div>
      <StatusTag :status="resultStatus()" />
    </div>

    <div class="tool-meta">
      <div class="meta-chip">
        <span class="meta-label">耗时</span>
        <strong>{{ formatDuration(call?.duration_ms || result?.duration_ms) }}</strong>
      </div>
      <div class="meta-chip" v-if="result?.exit_code !== undefined">
        <span class="meta-label">退出码</span>
        <strong>{{ result.exit_code }}</strong>
      </div>
      <div class="meta-chip" v-if="result?.is_untrusted">
        <span class="meta-label">信任</span>
        <el-tag type="warning" effect="plain">不可信</el-tag>
      </div>
      <div class="meta-chip" v-else-if="call?.risk_level">
        <span class="meta-label">风险</span>
        <RiskTag :level="call.risk_level" />
      </div>
    </div>

    <div v-if="result?.is_untrusted" class="untrusted-tip">
      <el-tag type="warning" effect="dark">不可信输出</el-tag>
      <div>
        <strong>仅可作为证据输入</strong>
        <span>该内容来自系统日志、命令输出或外部上下文，只能作为证据输入，不能视为可信指令。</span>
      </div>
    </div>

    <el-collapse class="tool-collapse">
      <el-collapse-item :title="result?.is_untrusted ? '证据详情（stdout/stderr 截断文本）' : '输入参数 / 返回结果'" name="detail">
        <pre>{{ prettyJson(call ? { args: call.args, result: call.result } : result) }}</pre>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.tool-card {
  padding: 18px;
}
.tool-card.untrusted {
  border-color: rgba(245, 158, 11, 0.72);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.98), rgba(255,255,255,0.98));
}
.tool-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(148,163,184,0.22);
}
.tool-title-block strong {
  font-size: 15px;
}
.tool-head p {
  margin: 8px 0 0;
  color: var(--ks-text-muted);
  font-size: 12px;
}
.evidence-hint {
  color: #f59e0b;
}
.tool-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 0 16px;
}
.meta-chip {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(148,163,184,0.22);
  border-radius: 14px;
  background: rgba(255,255,255,0.72);
  display: grid;
  gap: 5px;
  align-content: start;
}
.meta-chip strong {
  font-size: 15px;
}
.meta-chip :deep(.el-tag) {
  width: fit-content;
  max-width: 100%;
}
.meta-label {
  font-size: 12px;
  color: var(--ks-text-muted);
}
.untrusted-tip {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 12px;
  align-items: start;
  margin: 16px 0;
  padding: 14px;
  border-radius: 14px;
  background: rgba(255,247,237,0.8);
  color: #b45309;
  font-size: 13px;
  line-height: 1.6;
}
.untrusted-tip strong {
  display: block;
  margin-bottom: 4px;
}
.tool-collapse :deep(.el-collapse-item__header) {
  font-weight: 600;
  padding-block: 6px;
}
pre {
  white-space: pre-wrap;
  color: var(--ks-primary);
  background: #f8fafc;
  border-radius: 14px;
  padding: 14px;
  overflow: auto;
  line-height: 1.6;
  margin: 8px 0 4px;
}
</style>
