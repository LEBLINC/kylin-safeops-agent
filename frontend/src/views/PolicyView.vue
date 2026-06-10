<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getPolicyRules } from '@/api/policy'
import type { PolicyRule } from '@/types/policy'

/**
 * PolicyView.vue
 *
 * 策略规则页面。
 *
 * 页面作用：
 * - 只读展示安全护栏规则；
 * - 展示 R0~R4 风险等级；
 * - 展示保护路径，例如 /、/etc、/var/lib/mysql；
 * - 帮助评委理解系统为什么会 allow/deny/confirm。
 *
 * 数据来源：
 * - 优先调用 GET /api/policy/rules；
 * - 失败时保留本页面初始化的默认规则。
 *
 * 与 stream.py 的关系：
 * - stream.py 的 policy_verdict 只推送“某次请求命中了哪些规则”；
 * - 本页面展示的是“规则定义列表”，不属于 stream.py 强约束字段。
 */
const rules = ref<PolicyRule[]>([
  { rule_id: 'PI001', name: '提示词注入：忽略规则', severity: 'high', action: 'deny', reason: '禁止用户要求绕过安全规则' },
  { rule_id: 'CMD001', name: '危险 rm -rf /', severity: 'critical', action: 'deny', reason: '禁止删除根目录' },
  { rule_id: 'SVC001', name: '服务重启需管理员确认', severity: 'high', action: 'confirm', reason: '影响服务可用性' },
  { rule_id: 'DBLOG001', name: '数据库日志保护', severity: 'critical', action: 'confirm', reason: '数据库 binlog 涉及恢复链路' }
])

/**
 * 页面初始化时加载策略规则。
 *
 * 成功：使用后端真实规则覆盖默认规则。
 * 失败：保留默认规则，保证页面可演示。
 */
onMounted(async () => {
  try {
    rules.value = await getPolicyRules()
  } catch {
    // 后端策略规则接口不可用时保留默认规则。
  }
})
</script>

<template>
  <div class="ks-page">
    <PageHeader title="策略规则" subtitle="只读展示当前安全护栏规则、风险等级与保护路径" />

    <div class="risk-row">
      <PageSection title="风险等级">
        <div class="risk-list">
          <RiskTag level="R0" />
          <RiskTag level="R1" />
          <RiskTag level="R2" />
          <RiskTag level="R3" />
          <RiskTag level="R4" />
        </div>
      </PageSection>

      <PageSection title="保护路径">
        <div class="paths">
          <code>/</code>
          <code>/boot</code>
          <code>/etc</code>
          <code>/usr</code>
          <code>/var/lib/mysql</code>
          <code>/var/lib/pgsql</code>
        </div>
      </PageSection>
    </div>

    <PageSection title="规则列表">
      <el-table :data="rules">
        <el-table-column prop="rule_id" label="规则 ID" width="140" />
        <el-table-column prop="name" label="规则名称" />
        <el-table-column prop="severity" label="严重性" width="120" />
        <el-table-column label="处置" width="120">
          <template #default="{ row }">
            <StatusTag :status="row.action" />
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" />
        <el-table-column prop="safer_alternative" label="安全替代方案" />
      </el-table>
    </PageSection>
  </div>
</template>

<style scoped>
.risk-row {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 16px;
}
.risk-list,
.paths {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
code {
  padding: 6px 10px;
  background: #0b1220;
  border: 1px solid var(--ks-border);
  border-radius: 8px;
  color: #93c5fd;
}
</style>
