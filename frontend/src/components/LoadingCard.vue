<!--
  LoadingCard.vue

  通用加载骨架屏组件。

  使用位置：
  - 后续需要展示“接口加载中”的卡片区域都可以复用。

  说明：
  - 使用 Element Plus 的 el-skeleton；
  - 当前组件没有 props，因为只承担统一 loading 样式；
  - 如果后续需要自定义行数，可以再添加 rows prop。
-->
<template>
  <div class="loading ks-card">
    <el-skeleton animated :rows="4" />
  </div>
</template>

<style scoped>
.loading {
  padding: 16px;
}
</style>
