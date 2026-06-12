<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import EvidenceTree from '@/components/EvidenceTree.vue'
import RiskTag from '@/components/RiskTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getRcaResult, startRcaAnalysis } from '@/api/rca'
import type { RcaProblemType, RcaResult } from '@/types/rca'

/**
 * RcaView.vue
 *
 * 独立 RCA 根因分析页面。
 *
 * 页面作用：
 * - 用户选择一个问题类型，例如磁盘满、僵尸进程、I/O 异常、配置漂移；
 * - 前端调用 api/rca.ts 发起分析；
 * - Mock 模式下由 api/mock.ts 返回四类演示 RCA 报告；
 * - 真实模式下由后端 /api/rca/analyze 和 /api/rca/{trace_id} 返回结果。
 *
 * 与 ChatView 的区别：
 * - ChatView 中的 RCA 来自事件流 rca.data.report；
 * - RcaView 是独立页面，通过 REST 接口主动发起分析。
 *
 * 重要约定：
 * stream.py 只规定 rca -> { report: dict }，没有强约束 report 内部字段。
 * 本页面使用的 RcaResult 字段来自 src/types/rca.ts，是前端与 RCA 实现侧建议对齐的结构。
 */

const problemType = ref<RcaProblemType>('disk_full')
const description = ref('根分区使用率超过 90%，请分析原因并给出安全建议')
const loading = ref(false)
const result = ref<RcaResult | null>(null)

/** 页面首次展示时使用的默认提示，不再直接写死完整 RCA 假数据。 */
const hasResult = computed(() => Boolean(result.value))

/** 将 dangerous_actions_rejected 统一转成可展示文本。兼容 string[] 和对象数组。 */
function dangerActionText(item: unknown) {
  if (typeof item === 'string') return item
  if (item && typeof item === 'object') {
    const data = item as { action?: string; reason?: string; rule_id?: string }
    return `${data.action || '危险操作'}：${data.reason || '-'}${data.rule_id ? `（${data.rule_id}）` : ''}`
  }
  return String(item)
}

/**
 * 发起 RCA 分析。
 *
 * 数据流：
 * 1. 用户选择 problem_type 并点击“开始分析”；
 * 2. startRcaAnalysis() 请求 POST /api/rca/analyze 或 mockStartRcaAnalysis()；
 * 3. 拿到 trace_id；
 * 4. getRcaResult(trace_id) 请求 GET /api/rca/{trace_id} 或 mockGetRcaResult()；
 * 5. 页面把返回的 RcaResult 渲染成证据树、根因候选、安全建议和危险操作拦截。
 */
async function analyze() {
  loading.value = true
  try {
    const response = await startRcaAnalysis({
      problem_type: problemType.value,
      description: description.value
    })
    result.value = await getRcaResult(response.trace_id)
  } catch (error) {
    ElMessage.error(`RCA 分析失败：${(error as Error).message}`)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="ks-page">
    <PageHeader title="根因分析 RCA" subtitle="确定性 playbook 采证 + LLM 归纳，输出证据化根因" />

    <PageSection title="发起分析" subtitle="RCA 页面通过 api/rca.ts 获取数据；Mock 模式下由 api/mock.ts 返回四类场景报告。">
      <div class="form-row">
        <el-select v-model="problemType">
          <el-option label="磁盘满" value="disk_full" />
          <el-option label="僵尸进程" value="zombie_process" />
          <el-option label="I/O 异常" value="io_high" />
          <el-option label="配置漂移" value="config_drift" />
          <el-option label="服务异常" value="service_failure" />
        </el-select>
        <el-input v-model="description" />
        <el-button type="primary" :loading="loading" @click="analyze">开始分析</el-button>
      </div>
    </PageSection>

    <EmptyState v-if="!hasResult" title="还没有 RCA 报告" description="选择问题类型并点击开始分析" />

    <template v-if="result">
      <PageSection title="RCA 总结">
        <p class="summary">{{ result.summary || '暂无总结' }}</p>
      </PageSection>

      <div class="rca-grid">
        <PageSection title="证据树 / 证据链">
          <EvidenceTree :nodes="result.evidence_tree || []" :evidence="result.evidence_chain || []" />
        </PageSection>

        <PageSection title="根因候选">
          <div v-for="candidate in result.root_cause_candidates" :key="candidate.cause" class="candidate">
            <strong>{{ candidate.cause }}</strong>
            <el-progress :percentage="Math.round(candidate.confidence * 100)" />
            <ul>
              <li v-for="evidence in candidate.evidence" :key="evidence">{{ evidence }}</li>
            </ul>
          </div>
        </PageSection>
      </div>

      <div class="rca-grid">
        <PageSection title="安全建议">
          <ul>
            <li v-for="action in result.safe_actions" :key="action">{{ action }}</li>
          </ul>
        </PageSection>

        <PageSection title="危险操作拦截">
          <div v-for="item in result.dangerous_actions_rejected" :key="dangerActionText(item)" class="danger-row">
            <RiskTag level="R4" />
            <span>{{ dangerActionText(item) }}</span>
          </div>
        </PageSection>
      </div>

      <PageSection title="建议下一步" v-if="result.recommended_next_steps?.length">
        <ul>
          <li v-for="step in result.recommended_next_steps" :key="step">{{ step }}</li>
        </ul>
      </PageSection>
    </template>
  </div>
</template>

<style scoped>
.form-row {
  display: grid;
  grid-template-columns: 180px 1fr 120px;
  gap: 12px;
}
.rca-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.summary {
  color: var(--ks-text);
  line-height: 1.7;
  margin: 0;
}
.candidate {
  padding: 14px;
  border: 1px solid var(--ks-border);
  border-radius: 12px;
}
.danger-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
}
@media (max-width: 1000px) {
  .form-row,
  .rca-grid {
    grid-template-columns: 1fr;
  }
}
</style>
