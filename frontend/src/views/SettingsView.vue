<script setup lang="ts">
import PageHeader from '@/layouts/PageHeader.vue'
import PageSection from '@/components/PageSection.vue'

/**
 * SettingsView.vue
 *
 * 系统设置页面。
 *
 * 当前定位：只读配置展示。
 *
 * 页面作用：
 * - 展示当前前端使用的 API 地址；
 * - 展示事件流模式 SSE/WS；
 * - 展示主题信息。
 *
 * 为什么先做只读：
 * - 避免演示阶段误修改生产策略；
 * - 真正的模型配置、安全策略编辑需要权限控制，当前版本不展开。
 */

/** API 基础地址。来自 .env.development 或 .env.production。 */
const apiBase = import.meta.env.VITE_API_BASE_URL || '/api via vite proxy'

/** 事件流模式。当前建议使用 sse + REST 审批。 */
const streamMode = import.meta.env.VITE_STREAM_MODE || 'sse'
</script>

<template>
  <div class="ks-page">
    <PageHeader title="系统设置" subtitle="当前页面先做只读配置展示，避免误改生产策略" />

    <PageSection title="前端运行配置">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="API Base URL">{{ apiBase }}</el-descriptions-item>
        <el-descriptions-item label="事件流模式">{{ streamMode }}</el-descriptions-item>
        <el-descriptions-item label="主题">浅色数据驾驶舱</el-descriptions-item>
      </el-descriptions>
    </PageSection>
  </div>
</template>
