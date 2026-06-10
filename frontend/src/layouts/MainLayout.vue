<script setup lang="ts">
/**
 * MainLayout.vue
 *
 * 全局主布局组件。
 *
 * 页面结构：
 * 1. 左侧 sidebar：系统品牌和一级导航菜单；
 * 2. 顶部 topbar：当前演示环境、Agent 在线状态、安全护栏状态；
 * 3. 中间 content：router-view 渲染当前业务页面。
 *
 * 使用方式：
 * - router/index.ts 中把所有业务页面作为 MainLayout 的 children；
 * - 因此 Dashboard、Chat、Audit 等页面都共享同一套菜单和顶部栏。
 *
 * 注意：
 * - 本组件不处理业务数据；
 * - 不请求后端接口；
 * - 菜单顺序和路由路径在 menus 数组中维护。
 */
import {
  ChatDotRound,
  DataAnalysis,
  DocumentChecked,
  Lock,
  Monitor,
  Operation,
  Setting,
  VideoPlay,
  Warning
} from '@element-plus/icons-vue'

/**
 * 左侧导航菜单配置。
 *
 * 字段说明：
 * - title：菜单中文名；
 * - icon：Element Plus 图标组件；
 * - path：点击后跳转的路由路径，必须和 router/index.ts 中的 path 对应。
 */
const menus = [
  { title: '仪表盘', icon: Monitor, path: '/dashboard' },
  { title: '智能对话', icon: ChatDotRound, path: '/chat' },
  { title: '根因分析', icon: DataAnalysis, path: '/rca' },
  { title: '风险审批', icon: Warning, path: '/approvals' },
  { title: '审计日志', icon: DocumentChecked, path: '/audit' },
  { title: '策略规则', icon: Lock, path: '/policy' },
  { title: '工具调用', icon: Operation, path: '/tools' },
  { title: '演示场景', icon: VideoPlay, path: '/demo' },
  { title: '系统设置', icon: Setting, path: '/settings' }
]
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">K</div>
        <div>
          <strong>Kylin SafeOps</strong>
          <span>安全智能运维 Agent</span>
        </div>
      </div>

      <el-menu
        router
        :default-active="$route.path"
        background-color="transparent"
        text-color="#94a3b8"
        active-text-color="#f8fafc"
      >
        <el-menu-item v-for="menu in menus" :key="menu.path" :index="menu.path">
          <el-icon><component :is="menu.icon" /></el-icon>
          <span>{{ menu.title }}</span>
        </el-menu-item>
      </el-menu>
    </aside>

    <section class="main">
      <header class="topbar">
        <div>
          <span class="env-dot" />
          麒麟高级服务器版 V11 / LoongArch 演示环境
        </div>
        <div class="top-actions">
          <el-tag type="success" effect="dark">Agent Online</el-tag>
          <el-tag type="warning" effect="dark">安全护栏已启用</el-tag>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </section>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 260px 1fr;
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.18), transparent 34%),
    var(--ks-bg);
}
.sidebar {
  border-right: 1px solid var(--ks-border);
  background: rgba(15, 23, 42, 0.86);
  padding: 18px 12px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px 20px;
}
.brand-logo {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  font-weight: 800;
}
.brand strong,
.brand span {
  display: block;
}
.brand span {
  margin-top: 4px;
  color: var(--ks-text-muted);
  font-size: 12px;
}
.el-menu-item {
  border-radius: 10px;
  margin: 4px 0;
}
.el-menu-item.is-active {
  background: rgba(59, 130, 246, 0.18);
}
.main {
  min-width: 0;
}
.topbar {
  height: 64px;
  border-bottom: 1px solid var(--ks-border);
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--ks-text-muted);
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(12px);
}
.env-dot {
  width: 8px;
  height: 8px;
  display: inline-block;
  margin-right: 8px;
  border-radius: 999px;
  background: var(--ks-success);
  box-shadow: 0 0 16px var(--ks-success);
}
.top-actions {
  display: flex;
  gap: 8px;
}
.content {
  padding: 24px;
}
</style>
