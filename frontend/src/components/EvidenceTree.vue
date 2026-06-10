<script setup lang="ts">
/**
 * EvidenceTree.vue
 *
 * RCA 证据树组件。
 *
 * 使用位置：
 * - ChatView.vue 右侧 RCA 证据链；
 * - RcaView.vue 独立 RCA 页面。
 *
 * 数据来源：
 * - RcaResult.evidence_tree：旧版树形结构；
 * - RcaReport.evidence_chain：新版证据链结构。
 *
 * 安全要求：
 * 如果证据节点 is_untrusted=true，页面必须显示“不可信证据”，
 * 表示该内容来自工具输出或日志，只能作为证据，不代表可信指令。
 */
import type { RcaEvidenceItem, RcaEvidenceNode } from '@/types/rca'
import { computed } from 'vue'

const props = defineProps<{
  nodes?: RcaEvidenceNode[]
  evidence?: RcaEvidenceItem[]
}>()

const treeData = computed<RcaEvidenceNode[]>(() => {
  if (props.nodes?.length) return props.nodes
  return (props.evidence || []).map(item => ({
    id: item.id,
    label: `${item.source_tool} · ${item.title}`,
    value: item.is_untrusted ? '不可信证据' : '可信',
    status: item.is_untrusted ? 'warning' : 'success',
    children: [{ id: `${item.id}_detail`, label: item.detail }]
  }))
})
</script>

<template>
  <el-tree
    class="evidence-tree"
    :data="treeData"
    node-key="id"
    default-expand-all
    :expand-on-click-node="false"
  >
    <template #default="{ data }">
      <div class="tree-node">
        <span>{{ data.label }}</span>
        <el-tag v-if="data.value" size="small" effect="dark" :type="data.status === 'warning' ? 'warning' : 'info'">
          {{ data.value }}
        </el-tag>
      </div>
    </template>
  </el-tree>
</template>

<style scoped>
.evidence-tree {
  background: transparent;
  color: var(--ks-text);
}
:deep(.el-tree-node__content) {
  min-height: 34px;
}
:deep(.el-tree-node__content:hover) {
  background: rgba(59, 130, 246, 0.14);
}
.tree-node {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
