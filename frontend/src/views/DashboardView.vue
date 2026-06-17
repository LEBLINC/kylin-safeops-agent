<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getSystemOverview } from '@/api/system'
import type { SystemOverview } from '@/types/system'

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

const metrics = computed<CockpitMetric[]>(() => [
  {
    key: 'cpu',
    title: 'CPU 使用率',
    label: 'CPU 核心负载',
    value: `${Math.round(cpuUsage.value)}`,
    unit: '%',
    percent: cpuUsage.value,
    trend: [42, 48, 48, 45, 31, 33, 40, 49, 46, 50, 48, 42, 31, 34, 42, 50],
    delta: '+4.2%',
    foot: '近 15 分钟',
    variant: 'blue'
  },
  {
    key: 'memory',
    title: '内存水位',
    label: 'Memory 占用',
    value: `${Math.round(memoryUsage.value)}`,
    unit: '%',
    percent: memoryUsage.value,
    trend: [66, 68, 68, 66, 58, 59, 62, 68, 66, 69, 68, 65, 58, 60, 64, 70],
    delta: '+2.8%',
    foot: '近 15 分钟',
    variant: 'purple'
  },
  {
    key: 'disk',
    title: '根分区占用',
    label: 'Root Disk 容量',
    value: `${Math.round(diskUsage.value)}`,
    unit: '%',
    percent: diskUsage.value,
    trend: [45, 49, 49, 47, 39, 40, 44, 50, 47, 50, 49, 47, 39, 41, 45, 50],
    delta: diskUsage.value >= 85 ? '高风险' : '稳定',
    foot: '读写吞吐',
    variant: 'cyan'
  },
  {
    key: 'deny',
    title: '拦截命中',
    label: '今日安全拦截',
    value: `${Math.round(deniedToday.value)}`,
    percent: clamp(deniedToday.value * 14, 5, 100),
    trend: [4, 5, 5, 4, 1, 2, 5, 4, 5, 4, 1, 2, 5, 7],
    delta: deniedToday.value > 0 ? '需关注' : '正常',
    foot: '拦截 / 审批',
    variant: 'orange'
  }
])

const serviceBars = computed(() => [
  {
    label: '运行',
    value: servicesRunning.value,
    max: Math.max(services.value.length, 3),
    className: 'success'
  },
  {
    label: '告警',
    value: 0,
    max: Math.max(services.value.length, 3),
    className: 'warning'
  },
  {
    label: '异常',
    value: services.value.length - servicesRunning.value,
    max: Math.max(services.value.length, 3),
    className: 'danger'
  }
])

onMounted(async () => {
  try {
    overview.value = await getSystemOverview()
  } catch {
    overviewLoadFailed.value = true
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
            <strong>{{ servicesRunning }}/{{ services.length || 3 }}</strong>
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
      v-if="overviewLoadFailed || overview.data_source === 'stub_executor'"
      class="source-alert"
      type="warning"
      show-icon
      :closable="false"
      title="接口加载失败"
      description="系统概览接口暂不可用，当前展示为演示数据"
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

      <PageSection title="任务态势分布" subtitle="执行 / 审批 / 拦截状态可视化">
        <div class="mini-column-chart">
          <div class="column" style="--height: 72%">
            <i />
            <span>执行</span>
          </div>
          <div class="column" style="--height: 38%">
            <i />
            <span>审批</span>
          </div>
          <div class="column" style="--height: 56%">
            <i />
            <span>拦截</span>
          </div>
          <div class="column" style="--height: 24%">
            <i />
            <span>风险</span>
          </div>
        </div>
      </PageSection>

      <PageSection title="风险速览" subtitle="近期裁决与异常诊断入口">
        <div class="risk-list">
          <div class="risk-row">
            <RiskTag level="R4" />
            <span>CMD001 拒绝 rm -rf /</span>
          </div>
          <div class="risk-row">
            <RiskTag level="R2" />
            <span>LOG001 日志轮转需审批</span>
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
