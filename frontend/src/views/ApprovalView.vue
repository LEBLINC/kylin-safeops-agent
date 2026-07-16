<script setup lang="ts">
import { computed, onMounted } from 'vue'
import {
  ArrowRight,
  Clock,
  DocumentChecked,
  Lock,
  Refresh,
  Tickets,
  UserFilled,
  Warning
} from '@element-plus/icons-vue'
import ApprovalCard from '@/components/ApprovalCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useApprovalStore } from '@/stores/approval'
import { formatTime } from '@/utils/time'

const approval = useApprovalStore()

const riskLevels = [
  { level: 'R4', label: '禁止级', color: '#b91c1c' },
  { level: 'R3', label: '高风险', color: '#ef4444' },
  { level: 'R2', label: '需确认', color: '#f59e0b' },
  { level: 'R1', label: '轻量诊断', color: '#0891b2' },
  { level: 'R0', label: '只读查询', color: '#10b981' }
] as const

const highRiskCount = computed(() =>
  approval.pending.filter(item => item.risk_level === 'R3' || item.risk_level === 'R4').length
)

const adminRequiredCount = computed(() =>
  approval.pending.filter(item => item.approval_role === 'admin').length
)

const riskDistribution = computed(() => {
  const total = approval.pending.length
  return riskLevels.map(risk => {
    const count = approval.pending.filter(item => item.risk_level === risk.level).length
    return {
      ...risk,
      count,
      percent: total ? Math.round((count / total) * 100) : 0
    }
  })
})

const roleDistribution = computed(() => {
  const count = (role: string | null) =>
    approval.pending.filter(item => item.approval_role === role).length

  const known = count('admin') + count('operator')
  return [
    { key: 'admin', label: '管理员', count: count('admin') },
    { key: 'operator', label: '运维操作员', count: count('operator') },
    {
      key: 'other',
      label: '未声明或其他角色',
      count: Math.max(0, approval.pending.length - known)
    }
  ]
})

const oldestApproval = computed(() => {
  return [...approval.pending].sort(
    (a, b) => parseCreatedAt(a.created_at) - parseCreatedAt(b.created_at)
  )[0]
})

const oldestWait = computed(() => {
  if (!oldestApproval.value) return '--'

  const createdAt = parseCreatedAt(oldestApproval.value.created_at)
  if (!Number.isFinite(createdAt)) return '--'

  const minutes = Math.max(0, Math.floor((Date.now() - createdAt) / 60000))
  if (minutes < 1) return '不足 1 分钟'
  if (minutes < 60) return `${minutes} 分钟`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小时`
  return `${Math.floor(minutes / (24 * 60))} 天`
})

const queueDescription = computed(() => {
  if (approval.loading) return '正在同步最新审批队列'
  if (approval.error) return '队列同步失败，请检查后端连接'
  if (!approval.pending.length) return '当前没有等待人工确认的操作'
  if (highRiskCount.value) return `其中 ${highRiskCount.value} 项为 R3 或 R4，请优先核对`
  return `当前有 ${approval.pending.length} 项操作等待人工确认`
})

onMounted(() => approval.load())

function parseCreatedAt(value?: string) {
  if (!value) return Number.NaN
  const numeric = Number(value)
  if (value.trim() && Number.isFinite(numeric)) {
    return numeric < 1_000_000_000_000 ? numeric * 1000 : numeric
  }

  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY
}

async function approveByTrace(traceId?: string) {
  if (!traceId) return
  await approval.approve(traceId)
}

async function rejectByTrace(traceId?: string) {
  if (!traceId) return
  await approval.reject(traceId)
}
</script>

<template>
  <div class="ks-page approval-page">
    <section class="approval-hero ks-card card-tone-blue">
      <div class="hero-copy">
        <h1>风险审批工作台</h1>
        <p>
          集中处理进入人工审批闸的执行链路。页面中的队列、风险、角色和时间信息
          均来自审批接口的真实返回字段。
        </p>
      </div>

      <div class="hero-actions">
        <div class="queue-status" :class="{ alert: highRiskCount > 0 || Boolean(approval.error) }">
          <span class="status-dot" />
          <div>
            <strong>{{ approval.pending.length }} 项待处理</strong>
            <span>{{ queueDescription }}</span>
          </div>
        </div>

        <el-button
          type="primary"
          :icon="Refresh"
          :loading="approval.loading"
          @click="approval.load()"
        >
          刷新队列
        </el-button>
      </div>
    </section>

    <el-alert
      v-if="approval.error"
      type="error"
      show-icon
      :closable="false"
      title="审批队列加载失败"
      :description="approval.error"
    />

    <section class="metric-grid" aria-label="审批队列概览">
      <article class="overview-card ks-card card-tone-blue">
        <div class="overview-icon"><el-icon><Tickets /></el-icon></div>
        <div>
          <span>待处理审批</span>
          <strong>{{ approval.pending.length }}</strong>
          <p>数据来源：GET /api/approvals</p>
        </div>
      </article>

      <article class="overview-card ks-card card-tone-rose">
        <div class="overview-icon"><el-icon><Warning /></el-icon></div>
        <div>
          <span>高风险操作</span>
          <strong>{{ highRiskCount }}</strong>
          <p>按后端 risk_level 统计 R3 / R4</p>
        </div>
      </article>

      <article class="overview-card ks-card card-tone-violet">
        <div class="overview-icon"><el-icon><UserFilled /></el-icon></div>
        <div>
          <span>需管理员审批</span>
          <strong>{{ adminRequiredCount }}</strong>
          <p>按后端 approval_role 统计</p>
        </div>
      </article>

      <article class="overview-card ks-card card-tone-cyan">
        <div class="overview-icon"><el-icon><Clock /></el-icon></div>
        <div>
          <span>最长等待</span>
          <strong class="wait-value">{{ oldestWait }}</strong>
          <p>
            {{ oldestApproval ? `最早入队：${formatTime(oldestApproval.created_at)}` : '当前队列为空' }}
          </p>
        </div>
      </article>
    </section>

    <div class="approval-workspace">
      <main class="queue-column">
        <div class="section-heading">
          <div>
            <h2>待审批队列</h2>
            <p>审批操作以 trace_id 为主键，通过或拒绝后由后端继续状态机流程。</p>
          </div>
          <el-tag v-if="approval.pending.length" type="warning" effect="plain" round>
            {{ approval.pending.length }} 项等待确认
          </el-tag>
        </div>

        <div v-if="approval.pending.length" class="approval-grid">
          <ApprovalCard
            v-for="item in approval.pending"
            :key="item.trace_id"
            :item="item"
            @approve="approveByTrace"
            @reject="rejectByTrace"
          />
        </div>

        <section v-else class="empty-panel ks-card card-tone-slate">
          <EmptyState
            title="暂无待审批操作"
            description="新的高风险操作进入 WAIT_APPROVAL 状态后，会自动显示在这里。"
          />
        </section>
      </main>

      <aside class="context-column">
        <section class="context-card ks-card card-tone-amber">
          <header class="context-head">
            <h3>风险分布</h3>
            <span>{{ approval.pending.length }} 项</span>
          </header>

          <div class="risk-list">
            <div v-for="risk in riskDistribution" :key="risk.level" class="risk-row">
              <div class="risk-meta">
                <span><b>{{ risk.level }}</b> {{ risk.label }}</span>
                <strong>{{ risk.count }}</strong>
              </div>
              <div class="risk-track">
                <span
                  :style="{
                    width: `${risk.percent}%`,
                    background: risk.color
                  }"
                />
              </div>
            </div>
          </div>
        </section>

        <section class="context-card ks-card card-tone-violet">
          <header class="context-head">
            <h3>审批角色</h3>
          </header>

          <div class="role-list">
            <div v-for="role in roleDistribution" :key="role.key" class="role-row">
              <span>{{ role.label }}</span>
              <strong>{{ role.count }}</strong>
            </div>
          </div>
        </section>

        <section class="context-card ks-card card-tone-mint">
          <header class="context-head">
            <h3>审批前检查</h3>
          </header>

          <ol class="review-list">
            <li>
              <span>01</span>
              <div>
                <strong>确认用户意图</strong>
                <p>检查操作描述是否与当前运维目标一致。</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>核对风险与角色</strong>
                <p>风险等级和审批角色均以后端策略结果为准。</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>保留 Trace ID</strong>
                <p>后续可在审计日志中按 Trace ID 回溯完整链路。</p>
              </div>
            </li>
          </ol>
        </section>

        <section class="context-card ks-card card-tone-cyan">
          <header class="context-head">
            <h3>关联信息</h3>
          </header>

          <nav class="quick-links" aria-label="审批相关页面">
            <router-link to="/audit" class="quick-link">
              <span class="link-icon"><el-icon><DocumentChecked /></el-icon></span>
              <span>
                <strong>审计日志</strong>
                <small>按 Trace ID 回溯执行链路</small>
              </span>
              <el-icon><ArrowRight /></el-icon>
            </router-link>

            <router-link to="/policy" class="quick-link">
              <span class="link-icon"><el-icon><Lock /></el-icon></span>
              <span>
                <strong>策略规则</strong>
                <small>查看风险等级与审批门槛</small>
              </span>
              <el-icon><ArrowRight /></el-icon>
            </router-link>
          </nav>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.approval-page {
  width: min(100%, 1480px);
  margin: 0 auto;
  display: grid;
  gap: 20px;
}

.approval-hero {
  position: relative;
  overflow: hidden;
  min-height: 148px;
  padding: 26px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
}

.approval-hero::after {
  content: '';
  position: absolute;
  width: 300px;
  height: 300px;
  right: -110px;
  top: -145px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.18), transparent 68%);
  pointer-events: none;
}

.hero-copy,
.hero-actions {
  position: relative;
  z-index: 1;
}

.hero-copy h1 {
  margin: 0 0 10px;
  font-size: clamp(25px, 2.5vw, 34px);
  letter-spacing: -0.035em;
}

.hero-copy p {
  max-width: 760px;
  margin: 0;
  color: var(--ks-text-muted);
  line-height: 1.75;
}

.hero-actions {
  min-width: 330px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 18px;
}

.queue-status {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 205px;
}

.status-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: var(--ks-success);
  box-shadow: 0 0 0 6px rgba(22, 163, 74, 0.12);
}

.queue-status.alert .status-dot {
  background: var(--ks-warning);
  box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.13);
}

.queue-status strong,
.queue-status span {
  display: block;
}

.queue-status strong {
  font-size: 14px;
}

.queue-status div > span {
  max-width: 225px;
  margin-top: 4px;
  color: var(--ks-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.overview-card {
  min-height: 112px;
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 15px;
}

.overview-icon {
  flex: 0 0 auto;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  color: var(--ks-accent);
  background: rgba(var(--ks-accent-rgb), 0.1);
  font-size: 22px;
}

.overview-card span,
.overview-card strong,
.overview-card p {
  display: block;
}

.overview-card span {
  color: var(--ks-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.overview-card strong {
  margin-top: 4px;
  font-size: 26px;
  line-height: 1.15;
}

.overview-card .wait-value {
  font-size: 20px;
}

.overview-card p {
  max-width: 230px;
  margin: 5px 0 0;
  overflow: hidden;
  color: var(--ks-text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.approval-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(300px, 0.72fr);
  gap: 20px;
  align-items: start;
}

.queue-column,
.context-column {
  min-width: 0;
}

.queue-column {
  display: grid;
  gap: 16px;
}

.context-column {
  display: grid;
  gap: 16px;
}

.section-heading,
.context-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.section-heading {
  padding: 4px 2px 0;
}

.section-heading h2,
.context-head h3 {
  margin: 0;
  color: var(--ks-text);
  letter-spacing: -0.02em;
}

.section-heading h2 {
  font-size: 21px;
}

.section-heading p {
  margin: 6px 0 0;
  color: var(--ks-text-muted);
  font-size: 13px;
}

.approval-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(430px, 100%), 1fr));
  gap: 16px;
  align-items: start;
}

.approval-grid > * {
  min-width: 0;
}

.empty-panel {
  min-height: 330px;
  display: grid;
  place-items: center;
}

.context-card {
  padding: 18px;
}

.context-head {
  align-items: center;
  margin-bottom: 16px;
}

.context-head h3 {
  font-size: 16px;
}

.context-head > span {
  color: var(--ks-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.risk-list {
  display: grid;
  gap: 13px;
}

.risk-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--ks-text-muted);
  font-size: 12px;
}

.risk-meta b,
.risk-meta strong {
  color: var(--ks-text);
}

.risk-meta b {
  margin-right: 4px;
}

.risk-track {
  height: 7px;
  margin-top: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.16);
}

.risk-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 220ms ease;
}

.role-list {
  display: grid;
  gap: 9px;
}

.role-row {
  padding: 11px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgba(124, 58, 237, 0.14);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.54);
  font-size: 12px;
}

.role-row span {
  color: var(--ks-text-muted);
}

.role-row strong {
  font-size: 14px;
}

.review-list {
  margin: 0;
  padding: 0;
  display: grid;
  gap: 14px;
  list-style: none;
}

.review-list li {
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 11px;
  align-items: start;
}

.review-list li > span {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: var(--ks-success);
  background: rgba(22, 163, 74, 0.1);
  font-size: 11px;
  font-weight: 800;
}

.review-list strong {
  font-size: 13px;
}

.review-list p {
  margin: 4px 0 0;
  color: var(--ks-text-muted);
  font-size: 11px;
  line-height: 1.55;
}

.quick-links {
  display: grid;
  gap: 8px;
}

.quick-link {
  padding: 11px;
  display: grid;
  grid-template-columns: 38px 1fr auto;
  align-items: center;
  gap: 10px;
  border: 1px solid transparent;
  border-radius: 13px;
  color: inherit;
  text-decoration: none;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    transform 160ms ease;
}

.quick-link:hover {
  border-color: rgba(8, 145, 178, 0.2);
  background: rgba(255, 255, 255, 0.68);
  transform: translateX(3px);
}

.link-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: var(--ks-cyan);
  background: rgba(8, 145, 178, 0.1);
  font-size: 18px;
}

.quick-link strong,
.quick-link small {
  display: block;
}

.quick-link strong {
  font-size: 13px;
}

.quick-link small {
  margin-top: 3px;
  color: var(--ks-text-muted);
  font-size: 11px;
}

.quick-link > .el-icon {
  color: var(--ks-text-muted);
}

@media (max-width: 1180px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .approval-workspace {
    grid-template-columns: minmax(0, 1fr);
  }

  .context-column {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .approval-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-actions {
    width: 100%;
    min-width: 0;
    justify-content: space-between;
  }
}

@media (max-width: 680px) {
  .approval-page {
    gap: 16px;
  }

  .approval-hero {
    padding: 21px 18px;
  }

  .hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .hero-actions .el-button {
    width: 100%;
  }

  .metric-grid,
  .context-column {
    grid-template-columns: minmax(0, 1fr);
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .risk-track span,
  .quick-link {
    transition: none;
  }

  .quick-link:hover {
    transform: none;
  }
}
</style>
