<!--
  App.vue

  根组件。

  作用：
  - 只放 <router-view />，让 Vue Router 决定当前显示哪个页面；
  - 不在这里写具体业务页面，避免根组件变复杂。

  页面路径由 src/router/index.ts 管理。
-->
<template>
  <!-- whoami 失败提示：fail-closed 到 viewer 是正确的，但不能静默
       让用户看到按钮变灰却不知为何。banner 不阻断操作，给出说明即可。-->
  <el-alert
    v-if="chat.whoamiError"
    type="warning"
    show-icon
    :closable="true"
    style="position:fixed;top:0;left:0;right:0;z-index:9999;"
  >
    身份获取失败，当前按只读权限展示。请检查网络或联系管理员，刷新页面后重试。
  </el-alert>
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
