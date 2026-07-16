<script setup lang="ts">
import { computed, ref } from 'vue'
import RiskTag from '@/components/RiskTag.vue'
import { cleanupDemoScenario, prepareDemoScenario, runDemoScenario } from '@/api/demo'
import { ElMessage } from 'element-plus'
import type { DemoResult, GateStatus, GateView, MetricItem, Scenario, ScenarioId } from '@/types/demo'
import { scenarios, mockResults, cloneMockResult, setMetric } from '@/api/demo-fixtures'








const paceOptions = [
  { label: '舒缓（推荐）', value: 1200 },
  { label: '标准', value: 800 },
  { label: '快速', value: 500 }
]
const useMock = ref(true)
const pace = ref(1200)
const activeId = ref<ScenarioId>('A')
const results = ref<Partial<Record<ScenarioId, DemoResult>>>({})
const prepared = ref<Partial<Record<ScenarioId, boolean>>>({})
const currentAction = ref<'prepare' | 'run' | 'cleanup' | ''>('')
const playing = ref(false)
const visibleGateCount = ref(0)
const showDecision = ref(false)
const showEvidence = ref(false)
const playToken = ref(0)

const activeScenario = computed(() => scenarios.find((item: Scenario) => item.id === activeId.value) || scenarios[0])
const activeResult = computed(() => results.value[activeId.value])
const activeBlueprint = computed(() => activeResult.value || mockResults[activeId.value])
const focusGateIndex = computed(() => activeBlueprint.value.gates.findIndex((gate: GateView) => gate.key === activeScenario.value.focusGate))
const paceText = computed(() => `${(pace.value / 1000).toFixed(1)} 秒 / 重点闸`)
const currentGate = computed(() => {
  if (!activeResult.value || visibleGateCount.value <= 0) return null
  return activeBlueprint.value.gates[Math.min(visibleGateCount.value - 1, activeBlueprint.value.gates.length - 1)]
})
const flowHint = computed(() => {
  if (!activeResult.value) return '点击“开始当前演示”查看逐步裁决'
  if (showDecision.value) return '流转完成，正在展示最终裁决与证据'
  const gate = currentGate.value
  if (!gate) return '准备进入第一道安全闸'
  const index = activeBlueprint.value.gates.findIndex((item: GateView) => item.key === gate.key)
  return isPresentationBypass(gate, index)
    ? `直接越过 ${gate.name}`
    : `${gate.name} · ${gate.label}`
})

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function gateIcon(status: GateStatus) {
  const iconMap: Record<GateStatus, string> = {
    protected: '盾',
    passed: '✓',
    waiting: '…',
    approved: '准',
    executed: '执',
    recorded: '链',
    skipped: '»',
    not_reached: '·',
    error: '!'
  }
  return iconMap[status]
}

function isPresentationBypass(gate: GateView, index: number) {
  if (gate.status === 'skipped' || gate.status === 'not_reached') return true
  return index < focusGateIndex.value && gate.status === 'passed'
}

function gateVisualStatus(gate: GateView, index: number): GateStatus {
  if (!activeResult.value || index >= visibleGateCount.value) return 'not_reached'
  if (gate.status === 'not_reached') return 'skipped'
  return gate.status
}

function gateVisualLabel(gate: GateView, index: number) {
  if (!activeResult.value || index >= visibleGateCount.value) return '等待'
  if (gate.status === 'skipped' || gate.status === 'not_reached') return '直接越过'
  if (isPresentationBypass(gate, index) && gate.status === 'passed') return '快速通过'
  return gate.label
}

function gateVisualDetail(gate: GateView, index: number) {
  if (!activeResult.value || index >= visibleGateCount.value) return '—'
  if (gate.status === 'not_reached') return '本场不展开该安全闸'
  return gate.detail
}

function gateDelay(gate: GateView, index: number) {
  if (isPresentationBypass(gate, index)) {
    return Math.max(180, Math.round(pace.value * 0.2))
  }
  if (index === focusGateIndex.value) return pace.value
  if (gate.key === 'audit') return Math.max(420, Math.round(pace.value * 0.65))
  return Math.max(360, Math.round(pace.value * 0.52))
}

function gateClass(gate: GateView, index: number) {
  const visible = Boolean(activeResult.value) && index < visibleGateCount.value
  const bypassed = visible && isPresentationBypass(gate, index)
  return [
    'gate-node',
    visible ? gateVisualStatus(gate, index) : 'idle',
    {
      visible,
      focused: index === focusGateIndex.value,
      bypassed,
      sweeping: bypassed && index === visibleGateCount.value - 1 && !showDecision.value,
      pulsing: visible && !bypassed && index === visibleGateCount.value - 1 && !showDecision.value
    }
  ]
}

function scenarioStatus(id: ScenarioId) {
  const result = results.value[id]
  if (result) return result.outcome
  if (prepared.value[id]) return 'prepared'
  return 'idle'
}

function scenarioStatusText(id: ScenarioId) {
  const status = scenarioStatus(id)
  const map: Record<string, string> = {
    idle: '待演示',
    prepared: '已准备',
    rejected: '已拦截',
    waiting: '待审批',
    completed: '已完成',
    failed: '异常'
  }
  return map[status]
}

function resetStage() {
  visibleGateCount.value = 0
  showDecision.value = false
  showEvidence.value = false
}

function selectScenario(id: ScenarioId) {
  if (playing.value) stopPlayback(false)
  activeId.value = id
  resetStage()
  if (results.value[id]) {
    visibleGateCount.value = 5
    showDecision.value = true
    showEvidence.value = true
  }
}

async function ensurePrepared(id: ScenarioId, silent = false) {
  if (prepared.value[id]) return
  if (useMock.value) {
    await sleep(480)
  } else {
    await prepareDemoScenario(id)
  }
  prepared.value[id] = true
  if (!silent) ElMessage.success(`场景 ${id} 已准备就绪`)
}

async function prepareCurrent() {
  if (currentAction.value || playing.value) return
  currentAction.value = 'prepare'
  try {
    await ensurePrepared(activeId.value)
  } catch (error: any) {
    ElMessage.error(error?.message || '准备场景失败，请检查后端服务')
  } finally {
    currentAction.value = ''
  }
}



function normalizeApiResult(id: ScenarioId, payload: any): DemoResult {
  const result = cloneMockResult(id)
  const raw = payload?.raw || payload || {}
  const state = payload?.state || raw.state || ''
  const events: string[] = raw.event_types || []
  const inputGate = raw.input_gate
  const policyVerdict = raw.policy_verdict
  const verifyValid = raw.verify_chain?.valid
  const exitCode = raw.tool_execution?.exit_code ?? raw.exit_code

  result.raw = payload
  result.traceId = payload?.trace_id || raw.trace_id || result.traceId
  result.requestText = raw.request?.text || payload?.request?.text || result.requestText
  result.actor = raw.request?.actor || payload?.request?.actor || result.actor
  result.action = raw.request?.action || payload?.request?.action || result.action
  result.target = raw.request?.target || payload?.request?.target || result.target

  if (state === 'REJECTED') {
    result.outcome = 'rejected'
    result.outcomeLabel = '请求已拒绝'
  } else if (state === 'WAITING_APPROVAL') {
    result.outcome = 'waiting'
    result.outcomeLabel = '等待审批'
  } else if (state === 'FAILED' || (exitCode !== undefined && Number(exitCode) !== 0)) {
    result.outcome = 'failed'
    result.outcomeLabel = '执行异常'
    result.decisionTitle = '工具执行没有成功完成'
    result.decisionReason = `工具退出码为 ${exitCode ?? 'unknown'}，页面不再将该结果标记为“通过”。`
    const resultGate = result.gates.find((gate: GateView) => gate.key === 'result')
    if (resultGate) {
      resultGate.status = 'error'
      resultGate.label = '执行异常'
      resultGate.detail = `exit code ${exitCode ?? 'unknown'}`
    }
  } else if (state === 'FINISHED') {
    result.outcome = 'completed'
  }

  if (inputGate?.triggered) {
    result.decisionReason = `输入闸命中 ${inputGate.pattern_id || 'PI001'}：${inputGate.category || '提示词注入'}。`
  } else if (policyVerdict?.decision === 'deny') {
    result.decisionReason = policyVerdict.reason || payload?.rejected_cause || raw.rejected_cause || result.decisionReason
  } else if (payload?.verified_summary || raw.verified_summary) {
    result.decisionReason = payload?.verified_summary || raw.verified_summary
  }

  if (raw.audit_seq_count !== undefined) {
    setMetric(result, '审计记录', `${raw.audit_seq_count} 条`)
  }
  if (events.length) {
    const existing = result.metrics.find((item: MetricItem) => item.label === '审计事件')
    if (existing) existing.value = `${events.length} 个`
    else result.metrics.push({ label: '审计事件', value: `${events.length} 个`, note: '来自实时接口' })
  }
  if (verifyValid === false) {
    const auditGate = result.gates.find((gate: GateView) => gate.key === 'audit')
    if (auditGate) {
      auditGate.status = 'error'
      auditGate.label = '链异常'
      auditGate.detail = raw.verify_chain?.reason || '审计链校验未通过'
    }
  }

  return result
}

async function animateResult(token: number) {
  const gates = activeBlueprint.value.gates
  for (let index = 0; index < gates.length; index += 1) {
    if (token !== playToken.value) return false
    visibleGateCount.value = index + 1
    await sleep(gateDelay(gates[index], index))
  }
  if (token !== playToken.value) return false
  showDecision.value = true
  await sleep(Math.round(pace.value * 0.75))
  if (token !== playToken.value) return false
  showEvidence.value = true
  return true
}

async function runScenario(id: ScenarioId, fromAutoPlay = false, token = playToken.value) {
  activeId.value = id
  resetStage()
  currentAction.value = 'run'

  try {
    await ensurePrepared(id, true)
    // Mock 分支直接用内置演示数据；真实分支拿后端裸 payload 后统一归一化为 DemoResult
    let normalized: DemoResult
    if (useMock.value) {
      await sleep(420)
      normalized = cloneMockResult(id)
    } else {
      normalized = normalizeApiResult(id, await runDemoScenario(id))
    }
    results.value[id] = normalized

    const completed = await animateResult(token)
    if (completed && !fromAutoPlay) {
      ElMessage.success(`${id} · ${normalized.outcomeLabel}`)
    }
    return completed
  } catch (error: any) {
    if (!fromAutoPlay) {
      ElMessage.error(error?.message || '运行场景失败，请检查后端服务')
    }
    return false
  } finally {
    currentAction.value = ''
  }
}

async function runCurrent() {
  if (currentAction.value || playing.value) return
  const token = ++playToken.value
  await runScenario(activeId.value, false, token)
}

async function cleanupCurrent() {
  if (currentAction.value || playing.value) return
  currentAction.value = 'cleanup'
  const id = activeId.value
  try {
    if (useMock.value) {
      await sleep(360)
    } else {
      await cleanupDemoScenario(id)
    }
    delete results.value[id]
    delete prepared.value[id]
    resetStage()
    ElMessage.success(`场景 ${id} 已清理`)
  } catch (error: any) {
    ElMessage.error(error?.message || '清理场景失败，请检查后端服务')
  } finally {
    currentAction.value = ''
  }
}

async function playAll() {
  if (playing.value || currentAction.value) return
  const token = ++playToken.value
  playing.value = true

  try {
    for (const scenario of scenarios) {
      if (token !== playToken.value) break
      const completed = await runScenario(scenario.id, true, token)
      if (!completed || token !== playToken.value) break
      await sleep(Math.round(pace.value * 1.25))
    }
    if (token === playToken.value) {
      ElMessage.success('五道安全闸演示已完成')
    }
  } finally {
    if (token === playToken.value) playing.value = false
  }
}

function stopPlayback(showMessage = true) {
  playToken.value += 1
  playing.value = false
  currentAction.value = ''
  if (showMessage) ElMessage.info('自动演示已暂停')
}

function handleModeChange() {
  stopPlayback(false)
  results.value = {}
  prepared.value = {}
  resetStage()
  ElMessage.info(useMock.value ? '已切换到 Mock 演示数据' : '已切换到实时 API')
}
</script>

<template>
  <div class="ks-page demo-page">
    <section class="demo-toolbar">
      <div class="toolbar-copy">
        <span class="eyebrow">LIVE SECURITY STORY</span>
        <strong>每一步只讲一个结论，关键证据随流程逐步出现</strong>
        <span>重点安全闸慢速讲解，非关键闸自动快速越过，适合答辩、录屏和大屏讲解。</span>
      </div>

      <div class="toolbar-controls">
        <div class="control-group">
          <span class="control-label">数据源</span>
          <el-switch
            v-model="useMock"
            inline-prompt
            active-text="Mock"
            inactive-text="API"
            @change="handleModeChange"
          />
        </div>

        <div class="control-group">
          <span class="control-label">演示节奏</span>
          <el-select v-model="pace" class="pace-select" :disabled="playing">
            <el-option
              v-for="option in paceOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <span class="pace-hint">{{ paceText }}</span>
        </div>

        <el-button
          class="play-all-button"
          :type="playing ? 'warning' : 'primary'"
          @click="playing ? stopPlayback() : playAll()"
        >
          {{ playing ? '暂停演示' : '一键完整演示' }}
        </el-button>
      </div>
    </section>

    <div class="story-layout">
      <aside class="scenario-panel">
        <div class="panel-heading">
          <span>演示步骤</span>
          <small>{{ scenarios.findIndex((item: Scenario) => item.id === activeId) + 1 }} / {{ scenarios.length }}</small>
        </div>

        <button
          v-for="item in scenarios"
          :key="item.id"
          class="scenario-card"
          :class="{ active: item.id === activeId }"
          type="button"
          @click="selectScenario(item.id)"
        >
          <span class="scenario-index">{{ item.id }}</span>
          <span class="scenario-content">
            <strong>{{ item.title }}</strong>
            <small>{{ item.technicalTitle }}</small>
          </span>
          <span class="scenario-state" :class="scenarioStatus(item.id)">
            {{ scenarioStatusText(item.id) }}
          </span>
        </button>
      </aside>

      <main class="stage-card">
        <div class="stage-glow" aria-hidden="true"></div>

        <header class="stage-header">
          <div>
            <div class="stage-kicker">
              <span>场景 {{ activeScenario.id }}</span>
              <RiskTag :level="activeScenario.risk" />
            </div>
            <h2>{{ activeScenario.title }}</h2>
            <p>{{ activeScenario.summary }}</p>
          </div>

          <span
            class="outcome-badge"
            :class="activeResult?.outcome || 'idle'"
          >
            {{ activeResult?.outcomeLabel || '等待运行' }}
          </span>
        </header>

        <section class="request-card">
          <div class="request-topline">
            <span>用户请求</span>
            <code>{{ activeScenario.action }}</code>
          </div>
          <blockquote>“{{ activeResult?.requestText || activeScenario.requestText }}”</blockquote>
          <div class="request-meta">
            <span><b>Actor</b>{{ activeResult?.actor || 'demo_user' }}</span>
            <span><b>Target</b>{{ activeResult?.target || activeScenario.target }}</span>
            <span><b>Trace</b>{{ activeResult?.traceId || '运行后生成' }}</span>
          </div>
        </section>

        <section class="gate-stage">
          <div class="section-caption">
            <span>安全闸流转</span>
            <small>{{ flowHint }}</small>
          </div>

          <div class="gate-flow">
            <template
              v-for="(gate, index) in activeBlueprint.gates"
              :key="gate.key"
            >
              <article :class="gateClass(gate, index)">
                <span class="gate-icon">{{ gateIcon(gateVisualStatus(gate, index)) }}</span>
                <strong>{{ gate.name }}</strong>
                <em>{{ gateVisualLabel(gate, index) }}</em>
                <small>{{ gateVisualDetail(gate, index) }}</small>
              </article>

              <span
                v-if="index < activeBlueprint.gates.length - 1"
                class="gate-arrow"
                :class="{
                  active: Boolean(activeResult) && visibleGateCount > index + 1,
                  sweeping: Boolean(activeResult) && visibleGateCount === index + 1 && isPresentationBypass(gate, index)
                }"
                aria-hidden="true"
              >
                →
              </span>
            </template>
          </div>
        </section>

        <Transition name="rise">
          <section v-if="showDecision && activeResult" class="decision-card" :class="activeResult.outcome">
            <span class="decision-mark">
              {{ activeResult.outcome === 'rejected' ? '!' : activeResult.outcome === 'failed' ? '×' : '✓' }}
            </span>
            <div>
              <small>系统最终决定</small>
              <h3>{{ activeResult.decisionTitle }}</h3>
              <p>{{ activeResult.decisionReason }}</p>
            </div>
          </section>
        </Transition>

        <Transition name="rise">
          <section v-if="showEvidence && activeResult" class="metric-grid">
            <article v-for="metric in activeResult.metrics" :key="metric.label" class="metric-card">
              <span>{{ metric.label }}</span>
              <strong>{{ metric.value }}</strong>
              <small>{{ metric.note }}</small>
            </article>
          </section>
        </Transition>

        <footer class="stage-actions">
          <el-button
            :loading="currentAction === 'prepare'"
            :disabled="playing"
            @click="prepareCurrent"
          >
            准备数据
          </el-button>
          <el-button
            type="primary"
            :loading="currentAction === 'run'"
            :disabled="playing"
            @click="runCurrent"
          >
            开始当前演示
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="currentAction === 'cleanup'"
            :disabled="playing"
            @click="cleanupCurrent"
          >
            清理场景
          </el-button>
        </footer>
      </main>

      <aside class="evidence-panel">
        <div class="panel-heading">
          <span>关键证据</span>
          <small>{{ showEvidence ? '已同步' : '等待结果' }}</small>
        </div>

        <div v-if="showEvidence && activeResult" class="evidence-list">
          <article
            v-for="item in activeResult.evidence"
            :key="item.label"
            class="evidence-card"
            :class="item.tone || 'normal'"
          >
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.note }}</small>
          </article>
        </div>

        <div v-else class="evidence-empty">
          <span class="empty-orbit"><i></i></span>
          <strong>证据将在裁决后出现</strong>
          <p>规则命中、审批人、工具调用和审计链不会提前剧透。</p>
        </div>

        <div class="timeline">
          <div class="timeline-title">事件时间线</div>
          <template v-if="showEvidence && activeResult">
            <article
              v-for="event in activeResult.events"
              :key="`${event.time}-${event.title}`"
              class="timeline-item"
            >
              <time>{{ event.time }}</time>
              <div>
                <strong>{{ event.title }}</strong>
                <p>{{ event.detail }}</p>
              </div>
            </article>
          </template>
          <p v-else class="timeline-placeholder">运行后展示真实发生顺序。</p>
        </div>

        <details v-if="showEvidence && activeResult?.raw" class="raw-details">
          <summary>查看原始技术数据</summary>
          <pre>{{ JSON.stringify(activeResult.raw, null, 2) }}</pre>
        </details>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.demo-page {
  --ink: #172033;
  --muted: #68758a;
  --line: rgba(108, 124, 153, 0.18);
  --primary: #4169e1;
  --primary-soft: rgba(65, 105, 225, 0.12);
  --success: #17a673;
  --warning: #e99a24;
  --danger: #e65367;
  --surface: rgba(255, 255, 255, 0.88);
  --shadow-soft: 0 14px 36px rgba(44, 60, 100, 0.08);
  --shadow-hover: 0 24px 58px rgba(44, 60, 100, 0.16);
  padding-bottom: 32px;
}

.demo-toolbar {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background:
    radial-gradient(circle at 0 0, rgba(93, 132, 255, 0.13), transparent 42%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.97), rgba(247, 249, 255, 0.9));
  box-shadow: var(--shadow-soft);
}

.demo-toolbar::after {
  content: '';
  position: absolute;
  top: -120%;
  left: -20%;
  width: 24%;
  height: 340%;
  transform: rotate(18deg);
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.86), transparent);
  opacity: 0;
  pointer-events: none;
}

.demo-toolbar:hover::after {
  opacity: 1;
  animation: toolbar-shine 1.1s ease;
}

.toolbar-copy {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.toolbar-copy strong {
  color: var(--ink);
  font-size: 15px;
}

.toolbar-copy > span:last-child {
  color: var(--muted);
  font-size: 13px;
}

.eyebrow {
  color: var(--primary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.toolbar-controls {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
  flex-wrap: wrap;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-label,
.pace-hint {
  color: var(--muted);
  font-size: 12px;
}

.pace-select {
  width: 138px;
}

.play-all-button {
  min-width: 122px;
  transition:
    transform 0.22s ease,
    box-shadow 0.22s ease,
    filter 0.22s ease;
}

.play-all-button:hover {
  transform: translateY(-2px) scale(1.015);
  box-shadow: 0 10px 24px rgba(65, 105, 225, 0.24);
  filter: saturate(1.08);
}

.story-layout {
  display: grid;
  grid-template-columns: minmax(190px, 0.78fr) minmax(520px, 2.2fr) minmax(260px, 1fr);
  gap: 18px;
  align-items: start;
}

.scenario-panel,
.stage-card,
.evidence-panel {
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--surface);
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
}

.scenario-panel,
.evidence-panel {
  padding: 14px;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 4px 12px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 800;
}

.panel-heading small {
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
}

.scenario-card {
  position: relative;
  width: 100%;
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 10px;
  align-items: center;
  margin: 0 0 9px;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 14px;
  color: inherit;
  text-align: left;
  background: rgba(246, 248, 252, 0.76);
  cursor: pointer;
  overflow: hidden;
  transition:
    transform 0.28s cubic-bezier(.2, .8, .2, 1),
    box-shadow 0.28s ease,
    border-color 0.28s ease,
    background 0.28s ease;
}

.scenario-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(120deg, transparent 15%, rgba(255, 255, 255, 0.86) 45%, transparent 72%);
  transform: translateX(-120%);
  transition: transform 0.6s ease;
  pointer-events: none;
}

.scenario-card:hover {
  transform: translateX(5px) translateY(-2px);
  border-color: rgba(65, 105, 225, 0.2);
  background: #fff;
  box-shadow: 0 12px 28px rgba(44, 60, 100, 0.11);
}

.scenario-card:hover::before {
  transform: translateX(120%);
}

.scenario-card.active {
  border-color: rgba(65, 105, 225, 0.34);
  background:
    radial-gradient(circle at 0 0, rgba(91, 129, 255, 0.18), transparent 45%),
    linear-gradient(135deg, #f8faff, #eef3ff);
  box-shadow: 0 14px 34px rgba(65, 105, 225, 0.14);
}

.scenario-index {
  position: relative;
  z-index: 1;
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: var(--primary);
  font-size: 14px;
  font-weight: 900;
  background: #fff;
  box-shadow: 0 6px 14px rgba(55, 76, 130, 0.1);
  transition:
    transform 0.28s ease,
    background 0.28s ease,
    color 0.28s ease;
}

.scenario-card:hover .scenario-index,
.scenario-card.active .scenario-index {
  transform: rotate(-4deg) scale(1.08);
  color: #fff;
  background: linear-gradient(135deg, #4169e1, #738df0);
}

.scenario-content {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.scenario-content strong {
  color: var(--ink);
  font-size: 12px;
  line-height: 1.4;
}

.scenario-content small {
  color: var(--muted);
  font-size: 10px;
}

.scenario-state {
  grid-column: 2;
  justify-self: start;
  margin-top: -2px;
  padding: 2px 7px;
  border-radius: 999px;
  color: #7f8a9e;
  font-size: 10px;
  background: #edf0f5;
}

.scenario-state.prepared {
  color: #9a6b12;
  background: #fff3d8;
}

.scenario-state.rejected {
  color: #b9334a;
  background: #ffe6eb;
}

.scenario-state.completed {
  color: #087d56;
  background: #ddf8ed;
}

.scenario-state.waiting {
  color: #9a6b12;
  background: #fff3d8;
}

.scenario-state.failed {
  color: #fff;
  background: var(--danger);
}

.stage-card {
  position: relative;
  overflow: hidden;
  min-height: 680px;
  padding: 24px;
  transition:
    transform 0.32s cubic-bezier(.2, .8, .2, 1),
    box-shadow 0.32s ease,
    border-color 0.32s ease;
}

.stage-card:hover {
  transform: translateY(-3px);
  border-color: rgba(65, 105, 225, 0.24);
  box-shadow: var(--shadow-hover);
}

.stage-glow {
  position: absolute;
  top: -180px;
  right: -120px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(92, 129, 255, 0.17), transparent 68%);
  pointer-events: none;
  transition: transform 0.8s ease;
}

.stage-card:hover .stage-glow {
  transform: translate(-34px, 28px) scale(1.12);
}

.stage-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 18px;
}

.stage-kicker {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.stage-header h2 {
  margin: 0 0 8px;
  color: var(--ink);
  font-size: 24px;
  line-height: 1.25;
}

.stage-header p {
  max-width: 690px;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.65;
}

.outcome-badge {
  flex: 0 0 auto;
  padding: 7px 11px;
  border: 1px solid #dfe4ee;
  border-radius: 999px;
  color: #7c879a;
  font-size: 11px;
  font-weight: 800;
  background: #f6f8fb;
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease;
}

.outcome-badge:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(44, 60, 100, 0.1);
}

.outcome-badge.rejected,
.outcome-badge.failed {
  color: #b83249;
  border-color: #ffd2da;
  background: #fff0f3;
}

.outcome-badge.completed {
  color: #087e56;
  border-color: #c2f0de;
  background: #eafaf4;
}

.outcome-badge.waiting {
  color: #986817;
  border-color: #ffe1a5;
  background: #fff7e7;
}

.request-card {
  position: relative;
  z-index: 1;
  margin-bottom: 22px;
  padding: 17px 18px;
  overflow: hidden;
  border: 1px solid rgba(100, 118, 151, 0.16);
  border-radius: 16px;
  background:
    linear-gradient(135deg, rgba(249, 250, 253, 0.96), rgba(255, 255, 255, 0.9));
  transition:
    transform 0.28s ease,
    box-shadow 0.28s ease,
    border-color 0.28s ease;
}

.request-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: linear-gradient(180deg, #4169e1, #80a0ff);
  transform: scaleY(0.35);
  transform-origin: top;
  transition: transform 0.3s ease;
}

.request-card:hover {
  transform: translateY(-3px);
  border-color: rgba(65, 105, 225, 0.25);
  box-shadow: 0 16px 34px rgba(44, 60, 100, 0.1);
}

.request-card:hover::after {
  transform: scaleY(1);
}

.request-topline,
.request-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.request-topline {
  justify-content: space-between;
  color: var(--muted);
  font-size: 11px;
}

.request-topline code {
  padding: 4px 7px;
  border-radius: 7px;
  color: #3e5fc5;
  background: rgba(65, 105, 225, 0.08);
}

.request-card blockquote {
  margin: 11px 0 13px;
  color: var(--ink);
  font-size: 15px;
  font-weight: 650;
  line-height: 1.65;
}

.request-meta {
  color: var(--muted);
  font-size: 10px;
}

.request-meta span {
  display: flex;
  gap: 5px;
}

.request-meta b {
  color: #44506a;
}

.gate-stage {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}

.section-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--ink);
  font-size: 12px;
  font-weight: 800;
}

.section-caption small {
  color: var(--muted);
  font-size: 10px;
  font-weight: 500;
}

.gate-flow {
  display: grid;
  grid-template-columns: minmax(90px, 1fr) 18px minmax(90px, 1fr) 18px minmax(90px, 1fr) 18px minmax(90px, 1fr) 18px minmax(90px, 1fr);
  gap: 4px;
  align-items: center;
}

.gate-node {
  position: relative;
  min-height: 132px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 12px 8px;
  overflow: hidden;
  border: 1px dashed rgba(125, 139, 166, 0.28);
  border-radius: 15px;
  color: #8d98aa;
  background: rgba(246, 248, 251, 0.72);
  opacity: 0.68;
  transform: scale(0.96);
  transition:
    opacity 0.45s ease,
    transform 0.45s cubic-bezier(.2, .8, .2, 1),
    border-color 0.35s ease,
    box-shadow 0.35s ease,
    background 0.35s ease;
}

.gate-node::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  background: linear-gradient(135deg, transparent, rgba(255, 255, 255, 0.84), transparent);
  transform: translateX(-130%);
  transition: transform 0.65s ease;
  pointer-events: none;
}

.gate-node:hover {
  transform: translateY(-5px) scale(1.025);
  box-shadow: 0 15px 30px rgba(44, 60, 100, 0.12);
}

.gate-node:hover::before {
  transform: translateX(130%);
}

.gate-node.visible {
  opacity: 1;
  transform: scale(1);
  border-style: solid;
}

.gate-node.focused {
  outline: 2px solid rgba(65, 105, 225, 0.12);
  outline-offset: 3px;
}

.gate-node.protected {
  color: #087d56;
  border-color: rgba(23, 166, 115, 0.34);
  background: linear-gradient(145deg, #effbf6, #ffffff);
}

.gate-node.passed,
.gate-node.approved,
.gate-node.executed,
.gate-node.recorded {
  color: #247254;
  border-color: rgba(54, 158, 113, 0.26);
  background: linear-gradient(145deg, #f2fbf7, #ffffff);
}

.gate-node.waiting {
  color: #946719;
  border-color: rgba(233, 154, 36, 0.36);
  background: linear-gradient(145deg, #fff8e9, #ffffff);
}

.gate-node.skipped,
.gate-node.not_reached {
  color: #65728a;
  border-color: rgba(101, 114, 138, 0.24);
  background: linear-gradient(145deg, #f7f9fc, #ffffff);
}

.gate-node.bypassed {
  border-style: dashed;
  opacity: 0.86;
  transform: scale(0.975);
  box-shadow: inset 0 0 0 1px rgba(101, 114, 138, 0.04);
}

.gate-node.bypassed .gate-icon {
  color: var(--primary);
  background: rgba(65, 105, 225, 0.07);
  box-shadow: inset 0 0 0 1px rgba(65, 105, 225, 0.12);
}

.gate-node.bypassed em {
  color: var(--primary);
}

.gate-node.sweeping {
  animation: gate-bypass 0.34s cubic-bezier(.2, .8, .2, 1) both;
}

.gate-node.error {
  color: #b52f47;
  border-color: rgba(230, 83, 103, 0.34);
  background: linear-gradient(145deg, #fff0f3, #ffffff);
}

.gate-node.pulsing {
  animation: gate-pulse 1.45s ease-in-out infinite;
}

.gate-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  color: currentColor;
  font-size: 14px;
  font-weight: 900;
  background: rgba(255, 255, 255, 0.9);
  box-shadow:
    inset 0 0 0 1px rgba(112, 126, 153, 0.12),
    0 7px 16px rgba(44, 60, 100, 0.08);
  transition:
    transform 0.3s ease,
    box-shadow 0.3s ease;
}

.gate-node:hover .gate-icon {
  transform: rotate(-5deg) scale(1.12);
  box-shadow:
    inset 0 0 0 1px rgba(112, 126, 153, 0.12),
    0 11px 22px rgba(44, 60, 100, 0.13);
}

.gate-node strong {
  color: var(--ink);
  font-size: 12px;
}

.gate-node em {
  font-size: 10px;
  font-style: normal;
  font-weight: 800;
}

.gate-node small {
  min-height: 28px;
  color: inherit;
  font-size: 9px;
  line-height: 1.45;
  text-align: center;
}

.gate-arrow {
  color: #ccd3df;
  font-size: 16px;
  text-align: center;
  transform: scaleX(0.8);
  transition:
    color 0.35s ease,
    transform 0.35s ease;
}

.gate-arrow.active {
  color: var(--primary);
  transform: scaleX(1.15);
}

.gate-arrow.sweeping {
  color: var(--primary);
  animation: arrow-bypass 0.34s ease both;
}

.decision-card {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 13px;
  align-items: start;
  margin-top: 16px;
  padding: 17px;
  border: 1px solid rgba(23, 166, 115, 0.2);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(239, 252, 247, 0.96), #fff);
  transition:
    transform 0.28s ease,
    box-shadow 0.28s ease;
}

.decision-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 16px 34px rgba(44, 60, 100, 0.11);
}

.decision-card.rejected,
.decision-card.failed {
  border-color: rgba(230, 83, 103, 0.22);
  background: linear-gradient(135deg, rgba(255, 240, 243, 0.96), #fff);
}

.decision-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  color: #fff;
  font-size: 20px;
  font-weight: 900;
  background: linear-gradient(135deg, #17a673, #4dc69a);
  box-shadow: 0 10px 20px rgba(23, 166, 115, 0.2);
}

.decision-card.rejected .decision-mark,
.decision-card.failed .decision-mark {
  background: linear-gradient(135deg, #e65367, #f18091);
  box-shadow: 0 10px 20px rgba(230, 83, 103, 0.2);
}

.decision-card small {
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
}

.decision-card h3 {
  margin: 3px 0 5px;
  color: var(--ink);
  font-size: 15px;
}

.decision-card p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

.metric-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 12px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 13px;
  border: 1px solid rgba(112, 126, 153, 0.14);
  border-radius: 14px;
  background: rgba(250, 251, 254, 0.9);
  transition:
    transform 0.24s ease,
    border-color 0.24s ease,
    box-shadow 0.24s ease;
}

.metric-card:hover {
  transform: translateY(-4px);
  border-color: rgba(65, 105, 225, 0.22);
  box-shadow: 0 12px 25px rgba(44, 60, 100, 0.1);
}

.metric-card span {
  color: var(--muted);
  font-size: 10px;
}

.metric-card strong {
  color: var(--ink);
  font-size: 18px;
}

.metric-card small {
  color: #8b95a6;
  font-size: 9px;
}

.stage-actions {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.stage-actions :deep(.el-button) {
  transition:
    transform 0.22s ease,
    box-shadow 0.22s ease;
}

.stage-actions :deep(.el-button:hover) {
  transform: translateY(-2px);
  box-shadow: 0 9px 20px rgba(44, 60, 100, 0.12);
}

.evidence-panel {
  transition:
    transform 0.3s ease,
    box-shadow 0.3s ease,
    border-color 0.3s ease;
}

.evidence-panel:hover {
  transform: translateY(-3px);
  border-color: rgba(65, 105, 225, 0.2);
  box-shadow: var(--shadow-hover);
}

.evidence-list {
  display: grid;
  gap: 9px;
}

.evidence-card {
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 3px 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid rgba(112, 126, 153, 0.14);
  border-radius: 13px;
  background: #fafbfe;
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease,
    border-color 0.24s ease;
}

.evidence-card::after {
  content: '';
  position: absolute;
  right: -22px;
  bottom: -22px;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  background: rgba(65, 105, 225, 0.06);
  transition: transform 0.35s ease;
}

.evidence-card:hover {
  transform: translateX(-4px) translateY(-2px);
  border-color: rgba(65, 105, 225, 0.22);
  box-shadow: 0 11px 24px rgba(44, 60, 100, 0.1);
}

.evidence-card:hover::after {
  transform: scale(1.7);
}

.evidence-card span {
  color: var(--muted);
  font-size: 10px;
}

.evidence-card strong {
  position: relative;
  z-index: 1;
  color: var(--ink);
  font-size: 13px;
}

.evidence-card small {
  grid-column: 1 / -1;
  color: #8b95a6;
  font-size: 9px;
}

.evidence-card.success {
  border-left: 3px solid var(--success);
}

.evidence-card.warning {
  border-left: 3px solid var(--warning);
}

.evidence-card.danger {
  border-left: 3px solid var(--danger);
}

.evidence-empty {
  min-height: 190px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 18px;
  color: var(--muted);
  text-align: center;
}

.evidence-empty strong {
  margin: 12px 0 5px;
  color: var(--ink);
  font-size: 12px;
}

.evidence-empty p {
  margin: 0;
  font-size: 10px;
  line-height: 1.55;
}

.empty-orbit {
  position: relative;
  width: 48px;
  height: 48px;
  display: block;
  border: 1px solid rgba(65, 105, 225, 0.2);
  border-radius: 50%;
}

.empty-orbit::before,
.empty-orbit::after {
  content: '';
  position: absolute;
  inset: 7px;
  border: 1px solid rgba(65, 105, 225, 0.16);
  border-radius: 50%;
}

.empty-orbit::after {
  inset: 16px;
  background: var(--primary);
  border: 0;
}

.empty-orbit i {
  position: absolute;
  top: 3px;
  left: 21px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #80a0ff;
  transform-origin: 3px 21px;
  animation: orbit 2.6s linear infinite;
}

.timeline {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.timeline-title {
  margin-bottom: 10px;
  color: var(--ink);
  font-size: 11px;
  font-weight: 800;
}

.timeline-item {
  position: relative;
  display: grid;
  grid-template-columns: 70px 1fr;
  gap: 9px;
  padding: 0 0 13px;
}

.timeline-item::before {
  content: '';
  position: absolute;
  top: 4px;
  left: 65px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 0 4px rgba(65, 105, 225, 0.09);
}

.timeline-item::after {
  content: '';
  position: absolute;
  top: 12px;
  bottom: -1px;
  left: 67px;
  width: 1px;
  background: rgba(65, 105, 225, 0.14);
}

.timeline-item:last-child::after {
  display: none;
}

.timeline-item time {
  color: #98a1b1;
  font-size: 8px;
}

.timeline-item strong {
  display: block;
  color: var(--ink);
  font-size: 10px;
}

.timeline-item p {
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 9px;
  line-height: 1.5;
}

.timeline-placeholder {
  color: #98a1b1;
  font-size: 10px;
}

.raw-details {
  margin-top: 12px;
  border-top: 1px solid var(--line);
}

.raw-details summary {
  padding: 12px 0 4px;
  color: var(--muted);
  font-size: 10px;
  cursor: pointer;
}

.raw-details pre {
  max-height: 220px;
  overflow: auto;
  padding: 10px;
  border-radius: 10px;
  color: #4b5870;
  font-size: 9px;
  background: #f5f7fb;
  white-space: pre-wrap;
}

.rise-enter-active,
.rise-leave-active {
  transition:
    opacity 0.5s ease,
    transform 0.5s cubic-bezier(.2, .8, .2, 1);
}

.rise-enter-from,
.rise-leave-to {
  opacity: 0;
  transform: translateY(14px) scale(0.98);
}

@keyframes gate-bypass {
  0% {
    opacity: 0.35;
    transform: translateX(-8px) scale(0.94);
  }
  55% {
    opacity: 1;
    transform: translateX(3px) scale(1.015);
  }
  100% {
    opacity: 0.86;
    transform: translateX(0) scale(0.975);
  }
}

@keyframes arrow-bypass {
  0% {
    opacity: 0.25;
    transform: translateX(-5px) scaleX(0.72);
  }
  60% {
    opacity: 1;
    transform: translateX(4px) scaleX(1.35);
  }
  100% {
    opacity: 0.85;
    transform: translateX(0) scaleX(1.05);
  }
}

@keyframes gate-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(65, 105, 225, 0.18);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(65, 105, 225, 0);
  }
}

@keyframes toolbar-shine {
  from {
    transform: translateX(0) rotate(18deg);
  }
  to {
    transform: translateX(600%) rotate(18deg);
  }
}

@keyframes orbit {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1280px) {
  .story-layout {
    grid-template-columns: 190px minmax(500px, 1fr);
  }

  .evidence-panel {
    grid-column: 1 / -1;
  }

  .evidence-list {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .demo-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-controls {
    justify-content: flex-start;
  }

  .story-layout {
    grid-template-columns: 1fr;
  }

  .scenario-panel {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 9px;
  }

  .scenario-panel .panel-heading {
    grid-column: 1 / -1;
  }

  .scenario-card {
    margin: 0;
  }

  .evidence-panel {
    grid-column: auto;
  }

  .gate-flow {
    grid-template-columns: 1fr;
  }

  .gate-arrow {
    transform: rotate(90deg);
  }

  .gate-arrow.active {
    transform: rotate(90deg) scaleX(1.15);
  }

  .gate-arrow.sweeping {
    animation: none;
    transform: rotate(90deg) scaleX(1.15);
  }

  .metric-grid,
  .evidence-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 620px) {
  .stage-card {
    min-height: auto;
    padding: 17px;
  }

  .stage-header {
    flex-direction: column;
  }

  .stage-header h2 {
    font-size: 20px;
  }

  .scenario-panel {
    grid-template-columns: 1fr;
  }

  .toolbar-controls,
  .control-group,
  .stage-actions {
    width: 100%;
  }

  .stage-actions {
    flex-direction: column;
  }

  .pace-select {
    flex: 1;
  }

  .request-meta {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
