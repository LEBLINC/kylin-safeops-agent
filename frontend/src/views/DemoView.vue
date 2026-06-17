<script setup lang="ts">
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import StatusTag from '@/components/StatusTag.vue'
import { cleanupDemoScenario, prepareDemoScenario, runDemoScenario } from '@/api/demo'
import { ElMessage } from 'element-plus'

/**
 * DemoView.vue
 *
 * 演示场景页面。
 *
 * 页面作用：
 * - 为比赛演示提供一键准备/启动/清理入口；
 * - 覆盖磁盘满、僵尸进程、提示词注入、配置漂移四类场景；
 * - 让演示过程稳定可重复。
 *
 * 数据来源：
 * - 当前场景列表写在前端页面中；
 * - 按钮操作调用 api/demo.ts 中的 REST 接口。
 *
 * 注意：
 * - 这些接口应只在开发/演示环境启用；
 * - 生产环境不要暴露制造故障或清理数据的接口。
 */

/**
 * 演示场景列表。
 *
 * 字段说明：
 * @field id 场景 ID，会作为接口参数 scenario 传给后端。
 * @field title 场景标题。
 * @field risk 场景预期风险等级，用于 RiskTag 展示。
 * @field desc 场景说明，描述会触发哪些工具和安全逻辑。
 */
const scenarios = [
  {
    id: 'disk_full',
    title: '磁盘满安全清理',
    risk: 'R2',
    desc: '生成大日志，触发 disk.usage、large_files、lsof 与日志轮转审批'
  },
  {
    id: 'zombie_process',
    title: '僵尸进程根因分析',
    risk: 'R1',
    desc: '制造 Z 进程，追溯 PPID，不直接 kill 僵尸进程'
  },
  {
    id: 'prompt_injection',
    title: '提示词注入拦截',
    risk: 'R4',
    desc: '在日志中预埋恶意指令，验证结果闸与策略引擎'
  },
  {
    id: 'config_drift',
    title: '配置漂移检测',
    risk: 'R3',
    desc: '制造 sshd_config 漂移，禁止自动覆盖，进入人工确认'
  }
]

/**
 * 执行演示场景操作。
 *
 * @param action 操作类型：prepare 准备数据、run 开始演示、cleanup 清理数据。
 * @param scenario 场景 ID，例如 disk_full。
 *
 * 调用链：
 * 按钮点击
 *   → run(action, scenario)
 *   → api/demo.ts 对应接口
 *   → 后端执行演示脚本
 *
 * 失败处理：
 * - 后端暂不可用时给出前端演示模式提示。
 */
async function run(action: 'prepare' | 'run' | 'cleanup', scenario: string) {
  try {
    if (action === 'prepare') await prepareDemoScenario(scenario)
    if (action === 'run') await runDemoScenario(scenario)
    if (action === 'cleanup') await cleanupDemoScenario(scenario)
    ElMessage.success('操作已提交')
  } catch {
    ElMessage.info('后端暂不可用：当前为前端演示模式')
  }
}
</script>

<template>
  <div class="ks-page">
    <PageHeader title="演示场景" subtitle="比赛演示用：四个场景 + 安全拦截 + 审计回溯" />

    <div class="demo-grid">
      <PageSection v-for="item in scenarios" :key="item.id" :title="item.title" :subtitle="item.desc">
        <div class="meta">
          <RiskTag :level="item.risk" />
          <StatusTag status="pending" />
        </div>
        <div class="actions">
          <el-button @click="run('prepare', item.id)">准备数据</el-button>
          <el-button type="primary" @click="run('run', item.id)">开始演示</el-button>
          <el-button type="danger" plain @click="run('cleanup', item.id)">清理数据</el-button>
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
.scenario-a { border-left: 3px solid var(--el-color-danger, #f56c6c); }
.scenario-b { border-left: 3px solid var(--el-color-danger-light, #f89898); }
.scenario-c { border-left: 3px solid var(--el-color-warning, #e6a23c); }
.scenario-d { border-left: 3px solid var(--el-color-primary, #409eff); }
</style>
