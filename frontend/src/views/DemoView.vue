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
      <PageSection v-for="item in scenarios" :key="item.id" class="demo-card" :style="toolCardStyle(item.risk)" :title="item.title" :subtitle="item.desc">
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
</style>
