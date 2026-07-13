<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getOverviewHistory, getSystemOverview, getSystemStats } from '@/api/system'
import { getPolicyEvents } from '@/api/policy'
import type { OverviewHistoryPoint, SystemOverview, SystemStats } from '@/types/system'
import type { PolicyEvent } from '@/types/policy'

type MetricVariant = 'blue' | 'purple' | 'cyan' | 'orange'

type CockpitMetric = {
  key: string
  title: string
  label: string
  value: string
  unit?: string
  percent: number
  trend: number[]
  delta: string
  foot: string
  variant: MetricVariant
}

const overview = ref<SystemOverview>({
  cpu_usage: 49,
  memory_usage: 68,
  root_disk_usage: 49,
  zombie_processes: 3,
  tool_calls_today: 0,
  denied_today: 5,
  data_source: 'stub_executor',
  probed_tools: [],
  services: [
    { name: 'nginx', status: 'running' },
    { name: 'safeops-agent', status: 'running' },
    { name: 'auditd', status: 'running' }
  ]
})

const overviewLoadFailed = ref(false)

/** 历史时序点，来自 /api/system/overview/history，驱动四张指标卡 sparkline。 */
const historyPoints = ref<OverviewHistoryPoint[]>([])
/** 任务态势聚合数据，来自 /api/system/stats。 */
const stats = ref<SystemStats | null>(null)
/** stats 接口是否加载失败。 */
const statsLoadFailed = ref(false)

/** 从 /api/policy/events 拉取的最近策略事件，用于风险速览。 */
const riskEvents = ref<PolicyEvent[]>([])

function toNumber(value: unknown, fallback = 0) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : fallback
}

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value))
}

function serviceStatus(raw: string): string {
  if (raw === 'running' || raw === 'active') return 'success'
  if (raw === 'failed' || raw === 'stopped') return 'danger'
  return 'warning'
}

const cpuUsage = computed(() => clamp(toNumber(overview.value.cpu_usage, 49)))
const memoryUsage = computed(() => clamp(toNumber(overview.value.memory_usage, 68)))
const diskUsage = computed(() => clamp(toNumber(overview.value.root_disk_usage, 49)))
const zombieCount = computed(() => Math.max(0, toNumber(overview.value.zombie_processes, 0)))
const deniedToday = computed(() => Math.max(0, toNumber(overview.value.denied_today, 0)))
const services = computed(() => overview.value.services ?? [])

const servicesRunning = computed(() =>
  services.value.filter((service) => service.status === 'running' || service.status === 'active').length
)

const healthScore = computed(() => {
  const cpuPenalty = cpuUsage.value > 70 ? (cpuUsage.value - 70) * 0.5 : 0
  const memoryPenalty = memoryUsage.value > 60 ? (memoryUsage.value - 60) * 0.5 : 0
  const diskPenalty = diskUsage.value > 75 ? (diskUsage.value - 75) * 0.5 : 0
  const zombiePenalty = zombieCount.value * 3
  const denyPenalty = deniedToday.value * 3

  return Math.round(clamp(100 - cpuPenalty - memoryPenalty - diskPenalty - zombiePenalty - denyPenalty))
})

function chartPoints(values: number[], width = 190, height = 64) {
  if (!values.length) return ''

  const max = Math.max(...values)
  const min = Math.min(...values)
  const gap = values.length > 1 ? width / (values.length - 1) : 0

  return values
    .map((value, index) => {
      const rate = max === min ? 0.5 : (value - min) / (max - min)
      const x = Number((index * gap).toFixed(2))
      const y = Number((height - rate * (height - 10) - 5).toFixed(2))
      return `${x},${y}`
    })
    .join(' ')
}

function areaPoints(values: number[], width = 190, height = 64) {
  const line = chartPoints(values, width, height)
  return `0,${height} ${line} ${width},${height}`
}

/** 从 historyPoints 提取指定字段的时序数组，用于 sparkline。 */
function trendFor(field: keyof OverviewHistoryPoint): number[] {
  if (!historyPoints.value.length) return []
  return historyPoints.value.map(p => p[field] as number)
}

/** 从 historyPoints 计算指定字段的首尾差值文本。 */
function deltaFor(field: keyof OverviewHistoryPoint): string {
  const pts = historyPoints.value
  if (pts.length < 2) return '-'
  const first = pts[0][field] as number
  const last = pts[pts.length - 1][field] as number
  const diff = last - first
  if (Math.abs(diff) < 0.5) return '持平'
  return diff > 0 ? `↑ ${diff.toFixed(1)}` : `↓ ${Math.abs(diff).toFixed(1)}`
}

/** 趋势脚注文本：有数据时显示采样范围，无数据时提示。 */
function trendFoot(): string {
  if (!historyPoints.value.length) return '暂无数据'
  const n = historyPoints.value.length
  const rangeSec = historyPoints.value.length >= 2
    ? Math.round(historyPoints.value[n - 1].ts - historyPoints.value[0].ts)
    : 0
  const rangeMin = rangeSec >= 60 ? `${Math.round(rangeSec / 60)}min` : `${rangeSec}s`
  return `${n} 个采样点 / ${rangeMin}`
}

const metrics = computed<CockpitMetric[]>(() => [
  {
    key: 'cpu',
    title: 'CPU 使用率',
    label: 'CPU 核心负载',
    value: `${Math.round(cpuUsage.value)}`,
    unit: '%',
    percent: cpuUsage.value,
    trend: trendFor('cpu'),
    delta: deltaFor('cpu'),
    foot: trendFoot(),
    variant: 'blue'
  },
  {
    key: 'memory',
    title: '内存水位',
    label: 'Memory 占用',
    value: `${Math.round(memoryUsage.value)}`,
    unit: '%',
    percent: memoryUsage.value,
    trend: trendFor('mem'),
    delta: deltaFor('mem'),
    foot: trendFoot(),
    variant: 'purple'
  },
  {
    key: 'disk',
    title: '根分区占用',
    label: 'Root Disk 容量',
    value: `${Math.round(diskUsage.value)}`,
    unit: '%',
    percent: diskUsage.value,
    trend: trendFor('disk'),
    delta: deltaFor('disk'),
    foot: trendFoot(),
    variant: 'cyan'
  },
  {
    key: 'deny',
    title: '拦截命中',
    label: '今日安全拦截',
    value: `${Math.round(deniedToday.value)}`,
    percent: clamp(deniedToday.value * 14, 5, 100),
    trend: [],
    delta: deniedToday.value > 0 ? '需关注' : '正常',
    foot: trendFoot(),
    variant: 'orange'
  }
])

/** 按工具调用次数计算 bar 宽度百分比。 */
function barPct(count: number, dict: Record<string, number>): string {
  const max = Math.max(...Object.values(dict), 1)
  return `${Math.max(4, (count / max) * 100)}%`
}

function serviceWarningCount() {
  return services.value.filter(s => s.status !== 'running' && s.status !== 'active' && s.status !== 'failed' && s.status !== 'stopped').length
}

const serviceBars = computed(() => {
  const total = services.value.length
  return [
    { label: '运行', value: servicesRunning.value, max: total || 1, className: 'success' },
    { label: '告警', value: serviceWarningCount(), max: total || 1, className: 'warning' },
    { label: '异常', value: services.value.filter(s => s.status === 'failed' || s.status === 'stopped').length, max: total || 1, className: 'danger' }
  ]
})

onMounted(async () => {
  try {
    overview.value = await getSystemOverview()
  } catch {
    overviewLoadFailed.value = true
  }

  // 后台拉策略事件用于风险速览
  try {
    riskEvents.value = await getPolicyEvents()
  } catch {
    // 接口不可用时留空
  }

  // 拉历史时序用于 sparkline 趋势
  try {
    const hist = await getOverviewHistory()
    historyPoints.value = hist?.series || []
  } catch {
    // 接口不可用时 trend 留空，sparkline 显示"暂无数据"
  }

  // 拉任务态势聚合统计
  try {
    stats.value = await getSystemStats()
  } catch {
    statsLoadFailed.value = true
  }
})
</script>

<template>
  <div class="ks-page dashboard-page">
    <PageHeader
      title="安全智能运维总览"
      subtitle="数据驾驶舱：用图表化卡片展示资源、趋势、服务与安全态势"
    />

    <section class="dashboard-hero">
      <div class="hero-summary">
        <div class="hero-kicker">LoongArch / SafeOps Console</div>
        <h2>安全智能运维态势</h2>
        <p>
          聚合系统资源、服务健康、执行审计与安全裁决，帮助值班人员快速判断当前环境风险。
        </p>

        <div class="hero-summary-grid">
          <div>
            <strong>{{ healthScore }}</strong>
            <span>健康评分</span>
          </div>
          <div>
            <strong>{{ services.length ? `${servicesRunning}/${services.length}` : '-' }}</strong>
            <span>实时服务</span>
          </div>
          <div>
            <strong>{{ overview.probed_tools?.length || 0 }}</strong>
            <span>已采集工具</span>
          </div>
          <div>
            <strong>{{ zombieCount }}</strong>
            <span>异常进程</span>
          </div>
        </div>
      </div>

      <div class="hero-metric-matrix">
        <article
          v-for="metric in metrics"
          :key="metric.key"
          class="cockpit-card metric-card"
          :class="`metric-card--${metric.variant}`"
        >
          <div class="metric-head">
            <span>{{ metric.title }}</span>
            <em>{{ metric.delta }}</em>
          </div>

          <div class="metric-body">
            <div class="gauge" :style="{ '--percent': `${metric.percent}%` }">
              <div class="gauge-inner">
                <strong>{{ metric.value }}</strong>
                <small v-if="metric.unit">{{ metric.unit }}</small>
              </div>
            </div>

            <div class="spark-panel">
              <div class="spark-label">{{ metric.label }}</div>
              <svg viewBox="0 0 190 64" preserveAspectRatio="none" aria-hidden="true">
                <polygon class="spark-area" :points="areaPoints(metric.trend)" />
                <polyline class="spark-line" :points="chartPoints(metric.trend)" />
              </svg>
            </div>
          </div>

          <div class="metric-foot">
            <span>{{ metric.foot }}</span>
            <!-- <span>一眼可观</span> -->
          </div>
        </article>
      </div>
    </section>

    <el-alert
      v-if="overviewLoadFailed"
      class="source-alert"
      type="warning"
      show-icon
      :closable="false"
      title="接口加载失败"
      description="系统概览接口暂不可用，当前展示为默认数据"
    />
    <el-alert
      v-else-if="overview.data_source === 'stub_executor'"
      class="source-alert"
      type="info"
      show-icon
      :closable="false"
      title="采集管道未接通"
      :description="`data_source=${overview.data_source}，探针未返回真实指标。已采集工具：${(overview.probed_tools || []).join(', ') || '无'}`"
    />

    <section class="lower-grid">
      <PageSection title="服务运行矩阵" subtitle="按状态分组展示服务健康度">
        <div class="service-bars">
          <div v-for="bar in serviceBars" :key="bar.label" class="service-bar-row">
            <span>{{ bar.label }}</span>
            <div class="bar-track">
              <i :class="bar.className" :style="{ width: `${Math.max(4, (bar.value / bar.max) * 100)}%` }" />
            </div>
            <strong>{{ bar.value }}</strong>
          </div>
        </div>

        <div class="service-cards">
          <div v-for="service in services" :key="service.name" class="service-card">
            <i />
            <span>{{ service.name }}</span>
            <StatusTag :status="serviceStatus(service.status)" />
          </div>
          <div v-if="!services.length" class="empty-tip">暂无服务数据</div>
        </div>
      </PageSection>

      <PageSection title="任务态势分布" subtitle="按工具 / 风险 / 状态三维聚合（近 24h）">
        <div v-if="statsLoadFailed" class="empty-tip">统计接口暂不可用</div>
        <template v-else-if="stats">
          <div class="stats-section">
            <label class="stats-label">按工具（by_tool）</label>
            <div v-if="!Object.keys(stats.by_tool).length" class="empty-tip">暂无记录</div>
            <div v-else class="stats-bars">
              <div v-for="(count, tool) in stats.by_tool" :key="tool" class="stats-bar-row">
                <code>{{ tool }}</code>
                <div class="bar-track"><i class="bar-fill" :style="{ width: barPct(count, stats.by_tool) }" /></div>
                <strong>{{ count }}</strong>
              </div>
            </div>
          </div>
          <div class="stats-section">
            <label class="stats-label">按风险（by_risk）</label>
            <div v-if="!Object.keys(stats.by_risk).length" class="empty-tip">暂无记录</div>
            <div v-else class="stats-pills">
              <span v-for="(count, risk) in stats.by_risk" :key="risk" class="stats-pill">
                <RiskTag :level="risk as any" /><strong>{{ count }}</strong>
              </span>
            </div>
          </div>
          <div class="stats-section">
            <label class="stats-label">按终态（by_status）</label>
            <div v-if="!Object.keys(stats.by_status).length" class="empty-tip">暂无记录</div>
            <div v-else class="stats-pills">
              <span v-for="(count, status) in stats.by_status" :key="status" class="stats-pill">
                <StatusTag :status="status" /><strong>{{ count }}</strong>
              </span>
            </div>
          </div>
        </template>
        <el-alert v-else type="info" show-icon :closable="false"
          title="暂无数据"
          description="审计库中暂无聚合记录，发起一次 Chat 对话后即有数据。" />
      </PageSection>

      <PageSection title="风险速览" subtitle="近期策略事件">
        <div v-if="!riskEvents.length" class="risk-list">
          <div class="empty-tip">暂无策略事件记录</div>
        </div>
        <div v-else class="risk-list">
          <div v-for="evt in riskEvents.slice(0, 5)" :key="evt.event_id || evt.rule_id || evt.created_at" class="risk-row">
            <RiskTag :level="(evt.final_risk || 'R1') as any" />
            <span>{{ evt.rule_id || evt.reason || '-' }}</span>
          </div>
        </div>

        <div class="quick-actions">
          <el-button type="primary">系统巡检</el-button>
          <el-button>磁盘诊断</el-button>
          <el-button>日志分析</el-button>
          <el-button>配置漂移</el-button>
        </div>
      </PageSection>
    </section>
  </div>
</template>

<style scoped>
.dashboard-page {
  gap: 14px;
}

.source-alert {
  border: none;
  border-radius: 0;
  background: #fff7e8;
}

.dashboard-hero {
  display: grid;
  grid-template-columns: minmax(320px, 0.78fr) minmax(560px, 1.22fr);
  gap: 18px;
  align-items: stretch;
  padding: 18px 20px;
  border: 1px solid rgba(96, 165, 250, 0.45);
  border-radius: 18px;
  background:
    radial-gradient(circle at 78% 14%, rgba(37, 99, 235, 0.15), transparent 30%),
    linear-gradient(135deg, #f8fbff 0%, #eaf3ff 100%);
  box-shadow: 0 18px 46px rgba(15, 23, 42, 0.08);
}

.hero-summary {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.hero-kicker {
  color: #2563eb;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.hero-summary h2 {
  margin: 10px 0 0;
  color: var(--ks-text);
  font-size: 28px;
  line-height: 1.2;
}

.hero-summary p {
  max-width: 520px;
  margin: 12px 0 0;
  color: var(--ks-text-secondary);
  font-size: 14px;
  line-height: 1.8;
}

.hero-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
  max-width: 460px;
}

.hero-summary-grid div {
  padding: 12px;
  border: 1px solid rgba(226, 232, 240, 0.86);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
}

.hero-summary-grid strong,
.hero-summary-grid span {
  display: block;
}

.hero-summary-grid strong {
  color: var(--ks-text);
  font-size: 20px;
}

.hero-summary-grid span {
  margin-top: 4px;
  color: var(--ks-text-secondary);
  font-size: 12px;
}

.hero-metric-matrix {
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.cockpit-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(190, 211, 239, 0.74);
  border-radius: 18px;
  box-shadow: var(--ks-shadow);
  transition:
    transform 0.22s ease,
    box-shadow 0.22s ease,
    border-color 0.22s ease,
    background 0.22s ease;
}

.cockpit-card:hover {
  transform: translateY(-5px);
  border-color: rgba(37, 99, 235, 0.3);
  box-shadow: var(--ks-shadow-hover);
}

.metric-card {
  min-height: 148px;
  padding: 16px;
}

.metric-card::after {
  content: '';
  position: absolute;
  right: -54px;
  bottom: -68px;
  width: 154px;
  height: 154px;
  border-radius: 999px;
  opacity: 0.7;
  transition:
    transform 0.22s ease,
    opacity 0.22s ease;
}

.metric-card:hover::after {
  transform: scale(1.1);
  opacity: 0.96;
}

.metric-card--blue {
  background: linear-gradient(135deg, #f8fbff 0%, #e9f2ff 58%, #dce9ff 100%);
  --accent: #2563eb;
  --accent-soft: rgba(37, 99, 235, 0.16);
}

.metric-card--blue:hover {
  background: linear-gradient(135deg, #ffffff 0%, #e5efff 48%, #cfe0ff 100%);
}

.metric-card--blue::after {
  background: rgba(37, 99, 235, 0.13);
}

.metric-card--purple {
  background: linear-gradient(135deg, #fbfaff 0%, #f0eaff 56%, #e6ddff 100%);
  --accent: #7c3aed;
  --accent-soft: rgba(124, 58, 237, 0.14);
}

.metric-card--purple:hover {
  background: linear-gradient(135deg, #ffffff 0%, #ede6ff 48%, #ddd0ff 100%);
}

.metric-card--purple::after {
  background: rgba(124, 58, 237, 0.13);
}

.metric-card--cyan {
  background: linear-gradient(135deg, #f8ffff 0%, #e5fbff 54%, #d8f5f5 100%);
  --accent: #0891b2;
  --accent-soft: rgba(8, 145, 178, 0.14);
}

.metric-card--cyan:hover {
  background: linear-gradient(135deg, #ffffff 0%, #def8ff 48%, #c7f0ee 100%);
}

.metric-card--cyan::after {
  background: rgba(8, 145, 178, 0.12);
}

.metric-card--orange {
  background: linear-gradient(135deg, #fffdfa 0%, #fff3d7 55%, #ffe9b3 100%);
  --accent: #f59e0b;
  --accent-soft: rgba(245, 158, 11, 0.16);
}

.metric-card--orange:hover {
  background: linear-gradient(135deg, #ffffff 0%, #fff0ca 48%, #ffdf92 100%);
}

.metric-card--orange::after {
  background: rgba(245, 158, 11, 0.16);
}

.metric-head,
.metric-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.metric-head span {
  color: var(--ks-text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.metric-head em {
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.68);
  color: var(--accent);
  font-style: normal;
  font-size: 12px;
  font-weight: 800;
}

.metric-body {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  align-items: center;
  gap: 16px;
  margin-top: 12px;
}

.gauge {
  width: 72px;
  height: 72px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: conic-gradient(var(--accent) var(--percent), rgba(255, 255, 255, 0.72) 0);
}

.gauge-inner {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  color: var(--ks-text);
}

.gauge-inner strong {
  font-size: 18px;
  line-height: 1;
}

.gauge-inner small {
  color: var(--ks-text-muted);
  font-size: 11px;
  font-weight: 800;
}

.spark-panel {
  min-width: 0;
}

.spark-label {
  margin-bottom: 4px;
  color: var(--ks-text-secondary);
  font-size: 13px;
}

.spark-panel svg {
  width: 100%;
  height: 58px;
  display: block;
}

.spark-area {
  fill: var(--accent-soft);
}

.spark-line {
  fill: none;
  stroke: var(--accent);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.metric-foot {
  margin-top: 8px;
  color: var(--ks-text-muted);
  font-size: 12px;
}

.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr) minmax(320px, 0.8fr);
  gap: 16px;
}

.service-bars {
  display: grid;
  gap: 12px;
}

.service-bar-row {
  display: grid;
  grid-template-columns: 44px 1fr 28px;
  align-items: center;
  gap: 12px;
  color: var(--ks-text-secondary);
  font-size: 13px;
}

.service-bar-row strong {
  color: var(--ks-text);
  text-align: right;
}

.bar-track {
  height: 12px;
  overflow: hidden;
  border-radius: 999px;
  background: #e6eef8;
}

.bar-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.bar-track .success {
  background: linear-gradient(90deg, #22c55e, #06b6d4);
}

.bar-track .warning {
  background: linear-gradient(90deg, #f59e0b, #facc15);
}

.bar-track .danger {
  background: linear-gradient(90deg, #ef4444, #fb7185);
}

.service-cards {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.service-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(190, 211, 239, 0.72);
  border-radius: 14px;
  background: linear-gradient(135deg, #ffffff, #f2fbff);
}

.service-card i {
  width: 10px;
  height: 32px;
  border-radius: 999px;
  background: linear-gradient(180deg, #22c55e, #06b6d4);
}

.service-card span {
  flex: 1;
  color: var(--ks-text);
  font-weight: 700;
}

.empty-tip {
  color: var(--ks-text-muted);
  font-size: 13px;
}

.mini-column-chart {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  align-items: end;
  gap: 14px;
  height: 190px;
  padding: 12px 6px 0;
}

.column {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 8px;
  text-align: center;
  color: var(--ks-text-secondary);
  font-size: 12px;
}

.column i {
  width: 100%;
  height: var(--height);
  min-height: 20px;
  border-radius: 12px 12px 6px 6px;
  background: linear-gradient(180deg, #3b82f6, #06b6d4);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.18);
}

.risk-list {
  display: grid;
  gap: 10px;
}

.risk-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--ks-border);
}

.risk-row span:last-child {
  color: var(--ks-text);
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
}

/* stats 三维聚合 */
.stats-section {
  margin-bottom: 14px;
}
.stats-section:last-child { margin-bottom: 0; }

.stats-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 8px;
}

.stats-bars {
  display: grid;
  gap: 8px;
}

.stats-bar-row {
  display: grid;
  grid-template-columns: 130px 1fr 32px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.stats-bar-row code {
  font-size: 12px;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stats-bar-row strong {
  text-align: right;
  color: var(--ks-text);
}

.bar-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #3b82f6, #06b6d4);
}

.stats-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stats-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.7);
}

.stats-pill strong {
  font-size: 15px;
  color: #1e293b;
}

@media (max-width: 1280px) {
  .dashboard-hero,
  .lower-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .hero-metric-matrix {
    grid-template-columns: 1fr;
  }

  .metric-body {
    grid-template-columns: 74px minmax(0, 1fr);
  }
}
</style>
