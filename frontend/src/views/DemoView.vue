<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import StatusTag from '@/components/StatusTag.vue'
import { cleanupDemoScenario, prepareDemoScenario, runDemoScenario } from '@/api/demo'
import { isMockEnabled } from '@/api/mock'
import { ElMessage } from 'element-plus'

/**
 * DemoView.vue
 *
 * 演示场景页面。
 *
 * 页面作用：
 * - 为比赛演示提供一键准备/启动/清理入口；
 * - 覆盖五道安全闸的端到端演示；
 * - 展示每次演示的状态、事件类型、审计校验结果。
 *
 * 数据来源：
 * - 后端 scripts/demo_stage4_e2e.py _SCENARIOS（A-E）；
 * - 按钮操作调用 api/demo.ts 中的 REST 接口，展示返回结果。
 */

/** 风险等级 → 卡片配色映射（同 ToolsView）。 */
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
    '--tool-card-shadow': current.shadow
  }
}

/**
 * 演示场景列表（与后端 scripts/demo_stage4_e2e.py _SCENARIOS 对齐）。
 *
 * 后端只用 A/B/C/D/E 字母码（F 跳过防破坏审计）。
 */
const scenarios = [
  { id: 'A', title: '输入闸 deny（注入红队）', risk: 'R4', desc: '提示词注入 → 输入闸拦截，验证 PI001 规则生效' },
  { id: 'B', title: '策略闸 deny（FILE001）', risk: 'R4', desc: '敏感文件访问 → 策略闸 deny，验证 FILE001 规则生效' },
  { id: 'C', title: '确认闸 resume R3（service.restart）', risk: 'R3', desc: '重启服务 → R3 需 admin 审批，验证确认闸 + resume 全流程' },
  { id: 'D', title: '确认闸 resume R2（log.compress_rotate）', risk: 'R2', desc: '日志轮转 → R2 需 operator 审批，验证可逆变更确认流程' },
  { id: 'E', title: '结果闸 + 审计闸', risk: 'R2', desc: '工具输出 is_untrusted 标注 + 审计链完整性校验' }
]

/** 每个 scenario 的演示结果（最后一次 run 的返回）。 */
const results = ref<Record<string, any>>({})
/** 正在执行的操作：scenario → action。 */
const running = ref<Record<string, string>>({})

/** demo 状态 → StatusTag status 映射。 */
function demoStatus(scenarioId: string): string {
  const r = results.value[scenarioId]
  if (!r) return 'pending'
  const state = r.state || r.raw?.state || ''
  if (state === 'REJECTED') return 'rejected'
  if (state === 'FINISHED') return 'success'
  return 'running'
}

/** 演示结果中的关键指标。 */
function resultHighlights(result: any) {
  const raw = result?.raw || {}
  return {
    state: result?.state || raw.state || '-',
    eventTypes: raw.event_types || [],
    eventCount: raw.event_types?.length || 0,
    auditSeqCount: raw.audit_seq_count ?? 0,
    verifyValid: raw.verify_chain?.valid,
    verifyCount: raw.verify_chain?.record_count ?? 0,
    inputGate: raw.input_gate || null,
    rejectedCause: result?.rejected_cause || raw.rejected_cause || '',
    verifiedSummary: result?.verified_summary || ''
  }
}

/**
 * 执行演示场景操作。
 *
 * @param action 操作类型：prepare / run / cleanup。
 * @param scenario 场景 ID（A-E）。
 */
async function run(action: 'prepare' | 'run' | 'cleanup', scenario: string) {
  running.value[scenario] = action
  try {
    let data: any
    if (action === 'prepare') {
      data = await prepareDemoScenario(scenario)
      ElMessage.success(`场景 ${scenario} 准备就绪`)
    }
    if (action === 'run') {
      data = await runDemoScenario(scenario)
      results.value[scenario] = data
      const h = resultHighlights(data)
      const parts: string[] = [`状态: ${h.state}`]
      if (h.eventTypes.length) parts.push(`事件: ${h.eventTypes.join(' → ')}`)
      if (h.verifyValid !== undefined) parts.push(`审计链: ${h.verifyValid ? '✅ 完整' : '❌ 异常'}`)
      ElMessage.success(parts.join('  |  '))
    }
    if (action === 'cleanup') {
      data = await cleanupDemoScenario(scenario)
      results.value[scenario] = undefined
      ElMessage.success(`场景 ${scenario} 已清理`)
    }
  } catch (e: any) {
    if (isMockEnabled()) {
      ElMessage.info('后端暂不可用：当前为前端演示模式')
    } else {
      ElMessage.error(e?.message || '演示场景操作失败，请检查后端服务状态')
    }
  } finally {
    delete running.value[scenario]
  }
}
</script>

<template>
  <div class="ks-page">
    <PageHeader title="演示场景" subtitle="五道安全闸端到端演示：A 输入闸 → B 策略闸 → C/D 确认闸 → E 结果+审计闸" />

    <div class="demo-grid">
      <PageSection
        v-for="item in scenarios"
        :key="item.id"
        class="demo-card"
        :style="toolCardStyle(item.risk)"
        :title="`${item.id} · ${item.title}`"
        :subtitle="item.desc"
      >
        <div class="meta">
          <RiskTag :level="item.risk" />
          <StatusTag :status="demoStatus(item.id)" />
        </div>

        <!-- 演示结果 -->
        <div v-if="results[item.id]" class="result-bar">
          <template v-for="hl in [resultHighlights(results[item.id])]" :key="item.id">
            <div class="result-row">
              <span class="result-label">状态</span>
              <el-tag
                :type="hl.state === 'REJECTED' ? 'danger' : hl.state === 'FINISHED' ? 'success' : 'info'"
                size="small"
              >{{ hl.state }}</el-tag>
              <span v-if="hl.auditSeqCount" class="result-label">审计记录</span>
              <span v-if="hl.auditSeqCount" class="result-value">{{ hl.auditSeqCount }} 条</span>
              <span v-if="hl.verifyValid !== undefined" class="result-label">审计链</span>
              <el-tag
                v-if="hl.verifyValid !== undefined"
                :type="hl.verifyValid ? 'success' : 'danger'"
                size="small"
              >{{ hl.verifyValid ? '✅ 完整' : '❌ 异常' }}</el-tag>
            </div>
            <div v-if="hl.eventTypes.length" class="result-row">
              <span class="result-label">事件流</span>
              <el-tag v-for="et in hl.eventTypes" :key="et" size="small" effect="plain" class="event-chip">{{ et }}</el-tag>
            </div>
            <div v-if="hl.inputGate" class="result-row">
              <span class="result-label">输入闸</span>
              <span class="result-value">{{ hl.inputGate.category || '-' }} / {{ hl.inputGate.pattern_id || '-' }}</span>
            </div>
          </template>
        </div>

        <div class="actions">
          <el-button size="small" :loading="running[item.id] === 'prepare'" @click="run('prepare', item.id)">准备数据</el-button>
          <el-button size="small" type="primary" :loading="running[item.id] === 'run'" @click="run('run', item.id)">开始演示</el-button>
          <el-button size="small" type="danger" plain :loading="running[item.id] === 'cleanup'" @click="run('cleanup', item.id)">清理数据</el-button>
        </div>
      </PageSection>
    </div>
  </div>
</template>

<style scoped>
.demo-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.meta,
.actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.demo-card {
  background: var(--tool-card-gradient);
  border: 1px solid rgba(148, 163, 184, 0.24);
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease,
    border-color 0.24s ease,
    background 0.24s ease;
}
.demo-card:hover {
  transform: translateY(-4px);
  background: var(--tool-card-hover-gradient);
  border-color: rgba(59, 130, 246, 0.28);
  box-shadow: 0 16px 40px var(--tool-card-shadow);
}
.result-bar {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.18);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.result-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.result-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
  min-width: 48px;
}
.result-value {
  font-size: 13px;
  color: #1e293b;
  font-weight: 500;
}
.event-chip {
  font-size: 11px;
  font-family: monospace;
}
</style>
