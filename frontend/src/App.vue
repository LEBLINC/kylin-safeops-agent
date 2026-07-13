<!--
  App.vue

  根组件。

  作用：
  - 只放 <router-view />，让 Vue Router 决定当前显示哪个页面；
  - 不在这里写具体业务页面，避免根组件变复杂。

  页面路径由 src/router/index.ts 管理。
-->
<template>
  <router-view v-if="!appError" />
  <div v-else class="app-error-fallback">
    <h2>页面加载异常</h2>
    <p>{{ appError }}</p>
    <el-button type="primary" @click="reload">刷新页面</el-button>
  </div>
</template>

<script setup lang="ts">
import { onErrorCaptured, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useChatStore } from '@/stores/chat'

const appError = ref('')
const chat = useChatStore()
const route = useRoute()

// 切换路由时清除错误状态
watch(() => route.fullPath, () => { appError.value = '' })

onErrorCaptured((err: Error) => {
  console.error('[App] captured error:', err)
  appError.value = err?.message || String(err)
  return false
})

function reload() {
  window.location.reload()
}

onMounted(() => { chat.fetchWhoami() })
</script>

<style scoped>
.app-error-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 16px;
  color: #475569;
}
.app-error-fallback h2 { margin: 0; color: #dc2626; }
</style>
