<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import { callTool, getToolRegistry, listToolCalls } from '@/api/tools'
import type { ToolDefinition } from '@/types/tool'

/**
 * ToolsView.vue
 *
 * MCP 工具注册表页面。
 *
 * 页面作用：
 * - 展示系统当前可用的 MCP Tool；
 * - 展示每个工具的描述和默认风险等级；
 * - R0/R1 只读工具支持"手动调用"，直接调 POST /api/tools/call 并展示结果；
 * - R2+ 变更工具按钮置灰，提示"需走 Chat 审批链路"。
 *
 * 数据来源：
 * - 优先调用 GET /api/tools/registry；
 * - 后端不可用时保留默认工具列表。
 */
const tools = ref<ToolDefinition[]>([
  { tool: 'system.info', description: 'OS/内核/CPU/内存信息', risk: 'R0' },
  { tool: 'disk.usage', description: '磁盘使用率', risk: 'R0' },
  { tool: 'disk.large_files', description: '扫描指定目录大文件', risk: 'R1' },
  { tool: 'log.compress_rotate', description: '压缩并轮转日志', risk: 'R2' },
  { tool: 'service.restart', description: '重启服务', risk: 'R3' }
])

/** 风险等级 → 卡片配色映射。 */
const riskGradients: Record<string, { card: string; hover: string; icon: string; shadow: string }> = {
  R0: {
    card: 'linear-gradient(135deg, #eef6ff 0%, #f7fbff 48%, #e8f1ff 100%)',
    hover: 'linear-gradient(135deg, #dcecff 0%, #f1f7ff 45%, #d8e7ff 100%)',
    icon: 'linear-gradient(135deg, #2f80ed, #56ccf2)',
    shadow: 'rgba(47, 128, 237, 0.2)'
  },
  R1: {
    card: 'linear-gradient(135deg, #ecfffb 0%, #f8fffd 46%, #e1fbf4 100%)',
    hover: 'linear-gradient(135deg, #d6fff7 0%, #effffd 46%, #c9f5eb 100%)',
    icon: 'linear-gradient(135deg, #00b894, #00cec9)',
    shadow: 'rgba(0, 184, 148, 0.2)'
  },
  R2: {
    card: 'linear-gradient(135deg, #fff8e8 0%, #fffdf7 46%, #fff0cc 100%)',
    hover: 'linear-gradient(135deg, #fff0ca 0%, #fffaf0 46%, #ffe5a3 100%)',
    icon: 'linear-gradient(135deg, #f59e0b, #f97316)',
    shadow: 'rgba(245, 158, 11, 0.22)'
  },
  R3: {
    card: 'linear-gradient(135deg, #fff1f2 0%, #fffafa 46%, #ffe4e8 100%)',
    hover: 'linear-gradient(135deg, #ffe1e7 0%, #fff5f6 46%, #ffcfd9 100%)',
    icon: 'linear-gradient(135deg, #f43f5e, #fb7185)',
    shadow: 'rgba(244, 63, 94, 0.2)'
  },
  R4: {
    card: 'linear-gradient(135deg, #fff0f0 0%, #fffafa 46%, #ffe0e6 100%)',
    hover: 'linear-gradient(135deg, #fde0e0 0%, #fff2f4 46%, #fccfd5 100%)',
    icon: 'linear-gradient(135deg, #dc2626, #f43f5e)',
    shadow: 'rgba(220, 38, 38, 0.22)'
  },
  R5: {
    card: 'linear-gradient(135deg, #f9f0ff 0%, #fdfaff 46%, #f0e0ff 100%)',
    hover: 'linear-gradient(135deg, #f0e0ff 0%, #faf2ff 46%, #e5ccff 100%)',
    icon: 'linear-gradient(135deg, #7c3aed, #c026d3)',
    shadow: 'rgba(124, 58, 237, 0.22)'
  }
}

const defaultGradient = {
  card: 'linear-gradient(135deg, #f5efff 0%, #fbf8ff 46%, #eee4ff 100%)',
  hover: 'linear-gradient(135deg, #eadcff 0%, #f8f2ff 46%, #dfceff 100%)',
  icon: 'linear-gradient(135deg, #7c3aed, #a78bfa)',
  shadow: 'rgba(124, 58, 237, 0.2)'
}

function toolCardStyle(risk: string) {
  const current = riskGradients[risk] || defaultGradient
  return {
    '--tool-card-gradient': current.card,
    '--tool-card-hover-gradient': current.hover,
    '--tool-icon-gradient': current.icon,
    '--tool-card-shadow': current.shadow
  }
}


// ---- 工具详情弹窗 ----
const detailDialogVisible = ref(false)
const detailTarget = ref<ToolDefinition | null>(null)
const callHistory = ref<any[]>([])
const callHistoryLoading = ref(false)

async function openDetailDialog(tool: ToolDefinition) {
  detailTarget.value = tool
  callHistory.value = []
  detailDialogVisible.value = true
  // D7：拉历史调用列表
  callHistoryLoading.value = true
  try {
    const resp: any = await listToolCalls(tool.tool, 10)
    callHistory.value = resp?.items || []
  } catch {
    callHistory.value = []
  } finally {
    callHistoryLoading.value = false
  }
}

// ---- 手动调用 ----

/** 调用弹窗是否可见。 */
const callDialogVisible = ref(false)
/** 当前正在操作的工具定义。 */
const callTarget = ref<ToolDefinition | null>(null)
/** 表单模式下的参数对象。 */
const callArgsObject = ref<Record<string, unknown>>({})
/** 是否切换到 JSON 编辑模式。 */
const jsonEditMode = ref(false)
/** JSON 编辑模式下的文本。 */
const callArgsJson = ref('{}')
/** 最近一次调用结果（ToolCallResponse）。 */
const callResult = ref<{ executed: boolean; result?: any; verdict?: any; reason?: string } | null>(null)
/** 调用中。 */
const calling = ref(false)

/** R0/R1 只读工具允许手动调用，R2+ 须走 Chat→审批链路。 */
function isReadOnly(risk: string) {
  return risk === 'R0' || risk === 'R1'
}

/** 从 input_schema 提取属性定义列表，供表单渲染。 */
interface ArgField {
  key: string
  label: string
  type: 'text' | 'number' | 'switch' | 'list' | 'json'
  default: unknown
  description?: string
}
function argFields(schema: Record<string, unknown> | undefined): ArgField[] {
  const props = (schema as any)?.properties
  if (!props || typeof props !== 'object') return []
  return Object.keys(props).map(key => {
    const prop = (props as any)[key] || {}
    const propType = prop.type || 'string'
    let fieldType: ArgField['type'] = 'text'
    if (propType === 'number' || propType === 'integer') fieldType = 'number'
    else if (propType === 'boolean') fieldType = 'switch'
    else if (propType === 'object') fieldType = 'json'
    else if (propType === 'array') {
      const itemsType = prop?.items?.type || ''
      fieldType = (itemsType === 'string') ? 'list' : 'json'
    }

    return {
      key,
      label: prop.title || prop.description ? `${key}` : key,
      type: fieldType,
      default: prop.default,
      description: prop.title || prop.description || ''
    }
  })
}

function defaultArgs(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema as any)?.properties
  if (!props || typeof props !== 'object') return {}
  const args: Record<string, unknown> = {}
  for (const key of Object.keys(props)) {
    const prop = (props as any)[key]
    if (prop?.default !== undefined) {
      args[key] = prop.default
    } else if (prop?.type === 'number' || prop?.type === 'integer') {
      args[key] = 0
    } else if (prop?.type === 'boolean') {
      args[key] = false
    } else if (prop?.type === 'array') {
      args[key] = []
    } else if (prop?.type === 'object') {
      args[key] = {}
    } else {
      args[key] = ''
    }
  }
  return args
}

/** 打开调用弹窗：根据 input_schema 预填表单。 */
function openCallDialog(tool: ToolDefinition) {
  callTarget.value = tool
  jsonEditMode.value = false
  const schema = tool.input_schema || {}
  callArgsObject.value = defaultArgs(schema)
  callArgsJson.value = JSON.stringify(callArgsObject.value, null, 2)
  callResult.value = null
  callDialogVisible.value = true
}

/** 切换 JSON 编辑模式时同步数据。 */
function toggleJsonMode() {
  jsonEditMode.value = !jsonEditMode.value
  if (jsonEditMode.value) {
    // 表单 → JSON
    callArgsJson.value = JSON.stringify(callArgsObject.value, null, 2)
  } else {
    // JSON → 表单
    try {
      callArgsObject.value = JSON.parse(callArgsJson.value)
    } catch {
      // 解析失败留在 JSON 模式
      jsonEditMode.value = true
    }
  }
}

/** 表单模式下更新单个参数。 */
function setFormArg(key: string, value: unknown) {
  callArgsObject.value[key] = value
}

/** 执行手动工具调用。 */
async function executeCall() {
  if (!callTarget.value || calling.value) return
  let args: Record<string, unknown> = {}
  if (jsonEditMode.value) {
    try {
      args = JSON.parse(callArgsJson.value)
    } catch {
      callResult.value = { executed: false, reason: '参数 JSON 格式错误' }
      return
    }
  } else {
    args = callArgsObject.value
  }
  calling.value = true
  try {
    const data: any = await callTool(callTarget.value.tool, args)
    callResult.value = data
  } catch (e: any) {
    callResult.value = { executed: false, reason: e?.message || '调用失败' }
  } finally {
    calling.value = false
  }
}

/** 加载工具注册表，失败时继续使用默认列表。 */
onMounted(async () => {
  try {
    tools.value = await getToolRegistry()
  } catch {
    // 后端工具注册表接口不可用时保留默认工具。
  }
})
</script>

<template>
  <div class="ks-page">

    <div class="tool-grid">
      <PageSection
        v-for="tool in tools"
        :key="tool.tool"
        class="tool-card" @click="openDetailDialog(tool)"
        :title="tool.tool"
        :style="toolCardStyle(tool.risk)"
        :subtitle="tool.description"
      >
        <div class="tool-card-body">
          <div class="tool-bottom">
            <RiskTag :level="tool.risk" />
            <div class="tool-pills">
              <span>白名单工具</span>
              <span>强类型参数</span>
            </div>
          </div>
          <div class="tool-info">
            <el-button
              v-if="isReadOnly(tool.risk)"
              type="primary"
              plain
              @click.stop="openCallDialog(tool)"
            >
              调用
            </el-button>
            <el-tooltip
              v-else
              content="R2+ 变更工具需走 Chat 审批链路，不支持手动调用"
              placement="top"
            >
              <span><el-button disabled>调用</el-button></span>
            </el-tooltip>
          </div>
        </div>
      </PageSection>
    </div>


    <!-- 工具详情弹窗 -->
    <el-dialog
      v-model="detailDialogVisible"
      :title="detailTarget?.tool ?? '工具详情'"
      width="640px"
      destroy-on-close
    >
      <template v-if="detailTarget">
        <p class="call-desc">{{ detailTarget.description }}</p>
        <div class="call-section">
          <RiskTag :level="detailTarget.risk" />
        </div>
        <div class="call-section">
          <label class="call-label">input_schema</label>
          <pre class="detail-pre">{{ JSON.stringify(detailTarget.input_schema ?? {}, null, 2) }}</pre>
        </div>
        <div class="call-section">
          <label class="call-label">调用示例（参数）</label>
          <pre class="detail-pre">{{ JSON.stringify(defaultArgs(detailTarget.input_schema ?? {}), null, 2) }}</pre>
        </div>
        <div class="call-section">
          <label class="call-label">历史调用记录</label>
          <div v-if="callHistoryLoading" class="empty-tip">加载中…</div>
          <div v-else-if="!callHistory.length" class="empty-tip">暂无调用记录</div>
          <div v-else class="history-list">
            <div v-for="item in callHistory" :key="item.call_id" class="history-row"
              @click="$router.push(`/tools/${item.call_id}`)">
              <code class="history-call-id">{{ item.call_id?.slice(0, 16) }}…</code>
              <StatusTag :status="item.status" />
              <span class="history-dur">{{ item.duration_ms }}ms</span>
              <RiskTag :level="item.risk_level || 'R0'" />
              <span class="history-time">{{ item.created_at?.slice(0, 16) }}</span>
            </div>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
    <!-- 调用弹窗 -->
    <el-dialog
      v-model="callDialogVisible"
      :title="callTarget ? `手动调用：${callTarget.tool}` : '手动调用'"
      width="560px"
      destroy-on-close
    >
      <template v-if="callTarget">
        <p class="call-desc">{{ callTarget.description }}</p>

        <!-- 参数表单 / JSON 切换 -->
        <div class="call-section">
          <div class="call-args-header">
            <label class="call-label">参数</label>
            <el-button size="small" text @click="toggleJsonMode">
              {{ jsonEditMode ? '切换表单' : '编辑 JSON' }}
            </el-button>
          </div>

          <!-- 表单模式 -->
          <template v-if="!jsonEditMode">
            <div v-if="!argFields(callTarget.input_schema).length" class="empty-tip">该工具无需参数</div>
            <div v-for="field in argFields(callTarget.input_schema)" :key="field.key" class="arg-field">
              <div class="arg-field-head">
                <code>{{ field.key }}</code>
                <span v-if="field.description" class="arg-field-desc">{{ field.description }}</span>
              </div>
              <el-input
                v-if="field.type === 'text'"
                :model-value="String(callArgsObject[field.key] ?? '')"
                @update:model-value="(v: unknown) => setFormArg(field.key, v)"
                size="small"
              />
              <el-input-number
                v-else-if="field.type === 'number'"
                :model-value="Number(callArgsObject[field.key] ?? 0)"
                @update:model-value="(v: unknown) => setFormArg(field.key, v)"
                size="small"
                controls-position="right"
                style="width: 100%"
              />
              <el-switch
                v-else-if="field.type === 'switch'"
                :model-value="Boolean(callArgsObject[field.key])"
                @update:model-value="(v: unknown) => setFormArg(field.key, v)"
                size="small"
              />
              <el-select
                v-else-if="field.type === 'list'"
                :model-value="Array.isArray(callArgsObject[field.key]) ? callArgsObject[field.key] as any[] : []"
                @update:model-value="(v: unknown) => setFormArg(field.key, v)"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="输入后回车添加…"
                size="small"
                style="width: 100%"
              />
              <el-input
                v-else
                :model-value="JSON.stringify(callArgsObject[field.key], null, 2)"
                @update:model-value="(v: unknown) => { try { callArgsObject[field.key] = JSON.parse(v as string) } catch {} }"
                type="textarea"
                :rows="3"
                size="small"
              />
            </div>
          </template>

          <!-- JSON 模式 -->
          <el-input
            v-else
            v-model="callArgsJson"
            type="textarea"
            :rows="6"
          />
        </div>

        <!-- 调用结果 -->
        <div v-if="callResult" class="call-result">
          <div class="result-header">
            <el-tag :type="callResult.executed ? 'success' : 'danger'" size="small">
              {{ callResult.executed ? '已执行' : '未执行' }}
            </el-tag>
            <span v-if="callResult.reason" class="result-reason">{{ callResult.reason }}</span>
          </div>

          <!-- 策略裁决 -->
          <div v-if="callResult.verdict" class="result-block">
            <label class="call-label">策略裁决</label>
            <div class="verdict-card">
              <div class="verdict-row">
                <span class="verdict-key">裁决</span>
                <el-tag :type="callResult.verdict.decision === 'allow' ? 'success' : callResult.verdict.decision === 'deny' ? 'danger' : 'warning'" size="small">
                  {{ callResult.verdict.decision }}
                </el-tag>
              </div>
              <div v-if="callResult.verdict.final_risk" class="verdict-row">
                <span class="verdict-key">风险等级</span>
                <RiskTag :level="callResult.verdict.final_risk" />
              </div>
              <div v-if="callResult.verdict.matched_rules?.length" class="verdict-row">
                <span class="verdict-key">命中规则</span>
                <span class="verdict-val">{{ callResult.verdict.matched_rules.join(', ') }}</span>
              </div>
              <div v-if="callResult.verdict.reason" class="verdict-row">
                <span class="verdict-key">原因</span>
                <span class="verdict-val">{{ callResult.verdict.reason }}</span>
              </div>
            </div>
          </div>

          <!-- 执行结果 -->
          <div v-if="callResult.result" class="result-block">
            <label class="call-label">执行结果</label>
            <div class="result-detail-card">
              <div class="detail-row">
                <span class="detail-key">工具</span>
                <code>{{ callResult.result.tool }}</code>
              </div>
              <div v-if="callResult.result.exit_code !== undefined" class="detail-row">
                <span class="detail-key">退出码</span>
                <el-tag :type="callResult.result.exit_code === 0 ? 'success' : 'danger'" size="small">
                  {{ callResult.result.exit_code }}
                </el-tag>
              </div>
              <div v-if="callResult.result.duration_ms !== undefined" class="detail-row">
                <span class="detail-key">耗时</span>
                <span class="detail-val">{{ callResult.result.duration_ms }} ms</span>
              </div>
              <div v-if="callResult.result.is_untrusted !== undefined" class="detail-row">
                <span class="detail-key">可信度</span>
                <el-tag :type="callResult.result.is_untrusted ? 'warning' : 'success'" size="small">
                  {{ callResult.result.is_untrusted ? '不可信' : '可信' }}
                </el-tag>
              </div>
              <div v-if="callResult.result.stdout_truncated" class="detail-row full-width">
                <span class="detail-key">stdout</span>
                <pre class="stdout-block">{{ callResult.result.stdout_truncated }}</pre>
              </div>
              <div v-if="callResult.result.stderr_truncated" class="detail-row full-width">
                <span class="detail-key">stderr</span>
                <pre class="stderr-block">{{ callResult.result.stderr_truncated }}</pre>
              </div>
            </div>
          </div>
        </div>
      </template>

      <template #footer>
        <el-button @click="callDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="calling" @click="executeCall">执行调用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tool-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.tool-card {
  position: relative;
  min-height: 172px;
  cursor: pointer;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: var(--tool-card-gradient);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease,
    border-color 0.24s ease,
    background 0.24s ease;
}

.tool-card::before {
  content: '';
  position: absolute;
  right: -38px;
  top: -42px;
  width: 130px;
  height: 130px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.55);
  filter: blur(1px);
  pointer-events: none;
}

.tool-card::after {
  content: '';
  position: absolute;
  right: 22px;
  bottom: 18px;
  width: 84px;
  height: 84px;
  border-radius: 999px;
  background: var(--tool-icon-gradient);
  opacity: 0.12;
  filter: blur(2px);
  pointer-events: none;
  transition:
    opacity 0.24s ease,
    transform 0.24s ease;
}

.tool-card:hover {
  transform: translateY(-6px);
  border-color: rgba(59, 130, 246, 0.34);
  background: var(--tool-card-hover-gradient);
  box-shadow: 0 20px 46px var(--tool-card-shadow);
}

.tool-card:hover::after {
  opacity: 0.2;
  transform: scale(1.12);
}

.tool-card :deep(.section-header) {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}

.tool-card :deep(h3) {
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.tool-card :deep(p) {
  max-width: 92%;
  color: #64748b;
  line-height: 1.55;
}

.tool-card-body {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
}

.tool-info {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-end;
}

/* 调用按钮放大更醒目 */
.tool-info :deep(.el-button) {
  padding: 10px 22px;
  font-size: 14px;
  font-weight: 600;
}

.tool-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tool-pills span {
  padding: 5px 10px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.62);
  color: #475569;
  font-size: 12px;
  line-height: 1;
  backdrop-filter: blur(10px);
}

.tool-bottom {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

/* 调用弹窗 */
.call-desc {
  color: #64748b;
  font-size: 13px;
  margin: 0 0 16px;
}

.call-section {
  margin-bottom: 16px;
}

.call-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
}

/* 参数表单 */
.call-args-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.arg-field {
  margin-top: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.arg-field-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.arg-field-head code {
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.arg-field-desc {
  font-size: 12px;
  color: #94a3b8;
}

.call-result {
  margin-top: 8px;
  padding: 14px;
  background: #f8fafc;
  border: 1px solid var(--ks-border);
  border-radius: 10px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.result-reason {
  font-size: 13px;
  color: #64748b;
}

.result-block {
  margin-top: 12px;
}

/* 裁决卡片 */
.verdict-card {
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  gap: 8px;
}

.verdict-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.verdict-key {
  min-width: 60px;
  font-weight: 600;
  color: #64748b;
}

.verdict-val {
  color: #334155;
  line-height: 1.5;
}

/* 执行结果卡片 */
.result-detail-card {
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: grid;
  gap: 8px;
}

.detail-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.detail-row.full-width {
  flex-direction: column;
  align-items: flex-start;
}

.detail-key {
  min-width: 48px;
  font-weight: 600;
  color: #64748b;
}

.detail-val {
  color: #334155;
}

.detail-row code {
  font-size: 12px;
  color: #2563eb;
  background: rgba(37, 99, 235, 0.06);
  padding: 2px 8px;
  border-radius: 4px;
}

.stdout-block {
  margin: 4px 0 0;
  padding: 10px 12px;
  width: 100%;
  box-sizing: border-box;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow: auto;
}

.stderr-block {
  margin: 4px 0 0;
  padding: 10px 12px;
  width: 100%;
  box-sizing: border-box;
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow: auto;
}

@media (max-width: 1180px) {
  .tool-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .tool-grid {
    grid-template-columns: 1fr;
  }

  .tool-card-body {
    align-items: flex-start;
    flex-direction: column;
  }

  .tool-info {
    align-items: flex-start;
  }

  .tool-pills,
  .tool-bottom {
    justify-content: flex-start;
  }
}

.detail-pre {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
}

.history-list {
  display: grid;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}
.history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.15s;
}
.history-row:hover {
  background: #f1f5f9;
}
.history-call-id {
  font-size: 11px;
  color: #64748b;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-dur {
  color: #94a3b8;
  font-family: monospace;
}
.history-time {
  color: #94a3b8;
  font-size: 11px;
  margin-left: auto;
}</style>
