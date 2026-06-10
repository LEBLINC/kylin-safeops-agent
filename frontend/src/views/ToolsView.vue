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
      <PageSection v-for="tool in tools" :key="tool.tool" :title="tool.tool" :subtitle="tool.description">
        <RiskTag :level="tool.risk" />
      </PageSection>
    </div>
  </div>
</template>

<style scoped>
.tool-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
</style>
