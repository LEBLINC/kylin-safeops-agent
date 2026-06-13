<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import MetricCard from '@/components/MetricCard.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getSystemOverview } from '@/api/system'
import type { SystemOverview } from '@/types/system'

/**
 * DashboardView.vue
 *
 * 系统仪表盘页面。
 *
 * 页面作用：
 * - 作为系统首页展示整体运行状态；
 * - 展示 CPU、内存、磁盘、僵尸进程、今日工具调用、今日安全拦截；
 * - 展示关键服务状态和最近安全裁决摘要。
 *
 * 数据来源：
 * - 优先调用 api/system.ts 的 getSystemOverview()；
 * - 接口失败时保留本页面初始化的默认 Mock 数据，避免演示空白。
 *
 * 注意：
 * - 本页面不消费 stream.py 事件流；
 * - 它属于 REST 仪表盘数据展示页面。
 */

/**
 * overview
 *
 * 仪表盘系统总览数据。
 *
 * 字段来自 SystemOverview 类型：
 * - cpu_usage：CPU 使用率；
 * - memory_usage：内存使用率；
 * - root_disk_usage：根分区使用率；
 * - zombie_processes：僵尸进程数；
 * - tool_calls_today：今日工具调用数；
 * - denied_today：今日安全拒绝数；
 * - services：关键服务状态。
 */
const overview = ref<SystemOverview>({
  cpu_usage: 36,
  memory_usage: 68,
  root_disk_usage: 92,
  zombie_processes: 3,
  tool_calls_today: 128,
  denied_today: 5,
  data_source: 'stub_executor',
  probed_tools: [],
  services: [
    { name: 'nginx', status: 'running' },
    { name: 'safeops-agent', status: 'running' },
    { name: 'auditd', status: 'running' }
  ]
})

/**
 * 页面初始化时加载系统概览。
 *
 * 流程：
 * 1. 进入 DashboardView.vue；
 * 2. 调用 GET /api/system/overview；
 * 3. 成功则用真实数据覆盖 overview；
 * 4. 失败则继续使用默认 Mock 数据。
 */
/** 服务状态映射规则：running/active → success，failed/stopped → danger，其他 → warning。 */
function serviceStatus(raw: string): string {
  if (raw === 'running' || raw === 'active') return 'success'
  if (raw === 'failed' || raw === 'stopped') return 'danger'
  return 'warning'
}

/** 接口加载状态跟踪，用于降级提示。 */
const overviewLoadFailed = ref(false)

onMounted(async () => {
  try {
    overview.value = await getSystemOverview()
  } catch {
    overviewLoadFailed.value = true
    // 后端未启动时保留默认 Mock 数据，保证演示页可用。
  }
})
</script>

<template>
  <div class="ks-page">
    <PageHeader
      title="安全智能运维总览"
      subtitle="可对话、可管控、可追溯的麒麟安全智能运维平台"
    />


    <div v-if="overview.data_source === 'stub_executor'" class="datasource-stub-badge">
      <el-tag type="warning" size="small">桩数据</el-tag>
      <span v-if="!overview.probed_tools?.length" class="stub-hint">采集管道未接通</span>
    </div>
    <div v-else-if="overview.data_source === 'real'" class="datasource-real-badge">
      <el-tag type="success" size="small">真实采集</el-tag>
    </div>

    <div class="metric-grid">
      <MetricCard title="CPU 使用率" :value="`${overview.cpu_usage}%`" />
      <MetricCard title="内存使用率" :value="`${overview.memory_usage}%`" status="warning" />
      <MetricCard title="根分区使用率" :value="`${overview.root_disk_usage}%`" status="danger" />
      <MetricCard title="僵尸进程" :value="overview.zombie_processes" status="warning" />
      <MetricCard title="今日工具调用" :value="overview.tool_calls_today" />
      <MetricCard title="今日拦截" :value="overview.denied_today" status="danger" />
    </div>

    <div class="content-grid">
      <PageSection title="快捷诊断" subtitle="常用 RCA 与安全巡检入口">
        <div class="quick-actions">
          <el-button type="primary">系统巡检</el-button>
          <el-button>磁盘诊断</el-button>
          <el-button>日志分析</el-button>
          <el-button>配置漂移检测</el-button>
          <el-button>审计链校验</el-button>
        </div>
      </PageSection>

      <PageSection v-if="overviewLoadFailed" title="数据来源">
        <el-alert type="warning" show-icon :closable="false" title="接口加载失败" description="系统概览接口暂不可用，当前展示为演示数据" />
      </PageSection>

      <PageSection title="运行服务">
        <div class="service-list">
          <div v-for="service in overview.services" :key="service.name" class="service-row">
            <span>{{ service.name }}</span>
            <StatusTag :status="serviceStatus(service.status)" />
          </div>
        </div>
      </PageSection>

      <PageSection title="最近安全裁决">
        <div class="event-row">
          <RiskTag level="R4" />
          <span>CMD001 拒绝 rm -rf /</span>
        </div>
        <div class="event-row">
          <RiskTag level="R2" />
          <span>LOG001 日志轮转需审批</span>
        </div>
      </PageSection>
    </div>
  </div>
</template>

<style scoped>
.metric-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 16px;
}
.content-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 16px;
}
.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.service-list,
.event-row {
  display: grid;
  gap: 10px;
}
.service-row,
.event-row {
  padding: 10px 0;
  border-bottom: 1px solid var(--ks-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
@media (max-width: 1200px) {
  .metric-grid,
  .content-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.datasource-stub-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.datasource-real-badge {
  margin-bottom: 12px;
}
.stub-hint {
  color: var(--ks-text-secondary, #999);
  font-size: 12px;
}
</style>
