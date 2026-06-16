<!--
  App.vue

  根组件。

  作用：
  - 只放 <router-view />，让 Vue Router 决定当前显示哪个页面；
  - 不在这里写具体业务页面，避免根组件变复杂。

  页面路径由 src/router/index.ts 管理。
-->
<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'

const chat = useChatStore()
onMounted(() => { chat.fetchWhoami() })
</script>
