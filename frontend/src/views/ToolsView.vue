<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'
import RiskTag from '@/components/RiskTag.vue'
import { getToolRegistry } from '@/api/tools'
import type { ToolDefinition } from '@/types/tool'

/**
 * ToolsView.vue
 *
 * MCP 工具注册表页面。
 *
 * 页面作用：
 * - 展示系统当前可用的 MCP Tool；
 * - 展示每个工具的描述和默认风险等级；
 * - 让评委理解“LLM 不能直接执行 Shell，只能选择白名单工具”。
 *
 * 数据来源：
 * - 优先调用 GET /api/tools/registry；
 * - 后端不可用时保留默认工具列表。
 *
 * 与 stream.py 的关系：
 * - stream.py 的 plan_generated/tool_result 会出现工具名和工具结果；
 * - 但工具注册表本身不在 stream.py 中，需要 REST 接口单独提供。
 */
const tools = ref<ToolDefinition[]>([
  { tool: 'system.info', description: 'OS/内核/CPU/内存信息', risk: 'R0' },
  { tool: 'disk.usage', description: '磁盘使用率', risk: 'R0' },
  { tool: 'disk.large_files', description: '扫描指定目录大文件', risk: 'R1' },
  { tool: 'log.compress_rotate', description: '压缩并轮转日志', risk: 'R2' },
  { tool: 'service.restart', description: '重启服务', risk: 'R3' }
])

/** 风险等级 → 卡片配色映射。 */
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

/** 未知风险等级兜底：中性灰紫。 */
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
    '--tool-icon-gradient': current.icon,
    '--tool-card-shadow': current.shadow
  }
}

/** 加载工具注册表，失败时继续使用默认列表。 */
onMounted(async () => {
  try {
    tools.value = await getToolRegistry()
  } catch {
    // 后端工具注册表接口不可用时保留默认工具。
  }
})
</script>

<template>
  <div class="ks-page">
    <PageHeader title="工具调用" subtitle="MCP Tool 注册表，所有工具均为强类型参数化调用" />

    <div class="tool-grid">
      <PageSection
        v-for="tool in tools"
        :key="tool.tool"
        class="tool-card"
        :style="toolCardStyle(tool.risk)"
        :title="tool.tool"
        :subtitle="tool.description"
      >
        <div class="tool-card-body">
          <!-- <div class="tool-mark">
            <span>{{ tool.tool.slice(0, 1).toUpperCase() }}</span>
          </div> -->
          <div class="tool-bottom">
            <RiskTag :level="tool.risk" />
            <span class="tool-status">MCP Registry</span>
          </div>
          <div class="tool-info">
            <div class="tool-pills">
              <span>白名单工具</span>
              <span>强类型参数</span>
            </div>
          </div>
        </div>
      </PageSection>
    </div>
  </div>
</template>

<style scoped>
.tool-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.tool-card {
  position: relative;
  min-height: 172px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: var(--tool-card-gradient);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease,
    border-color 0.24s ease,
    background 0.24s ease;
}

.tool-card::before {
  content: '';
  position: absolute;
  right: -38px;
  top: -42px;
  width: 130px;
  height: 130px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.55);
  filter: blur(1px);
  pointer-events: none;
}

.tool-card::after {
  content: '';
  position: absolute;
  right: 22px;
  bottom: 18px;
  width: 84px;
  height: 84px;
  border-radius: 999px;
  background: var(--tool-icon-gradient);
  opacity: 0.12;
  filter: blur(2px);
  pointer-events: none;
  transition:
    opacity 0.24s ease,
    transform 0.24s ease;
}

.tool-card:hover {
  transform: translateY(-6px);
  border-color: rgba(59, 130, 246, 0.34);
  background: var(--tool-card-hover-gradient);
  box-shadow: 0 20px 46px var(--tool-card-shadow);
}

.tool-card:hover::after {
  opacity: 0.2;
  transform: scale(1.12);
}

.tool-card :deep(.section-header) {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}

.tool-card :deep(h3) {
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.tool-card :deep(p) {
  max-width: 92%;
  color: #64748b;
  line-height: 1.55;
}

.tool-card-body {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
}

.tool-mark {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  border-radius: 18px;
  background: var(--tool-icon-gradient);
  color: #fff;
  font-size: 22px;
  font-weight: 800;
  box-shadow: 0 12px 26px var(--tool-card-shadow);
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease;
}

.tool-card:hover .tool-mark {
  transform: translateY(-3px) rotate(-3deg);
  box-shadow: 0 16px 34px var(--tool-card-shadow);
}

.tool-info {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  align-items: flex-end;
  gap: 14px;
}

.tool-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.tool-pills span {
  padding: 5px 10px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.62);
  color: #475569;
  font-size: 12px;
  line-height: 1;
  backdrop-filter: blur(10px);
}

.tool-bottom {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.tool-status {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

@media (max-width: 1180px) {
  .tool-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .tool-grid {
    grid-template-columns: 1fr;
  }

  .tool-card-body {
    align-items: flex-start;
    flex-direction: column;
  }

  .tool-info {
    align-items: flex-start;
  }

  .tool-pills,
  .tool-bottom {
    justify-content: flex-start;
  }
}
</style>
