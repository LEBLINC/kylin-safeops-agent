<script setup lang="ts">
/**
 * MainLayout.vue
 *
 * 全局主布局组件。
 * 当前版本改为浅色后台风格，并增加侧边栏 mouseenter/mouseleave 自动展开/收起交互。
 */
import { computed, ref } from 'vue'
import { useChatStore } from '@/stores/chat'
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

const chatStore = useChatStore()
const identityText = computed(() => {
  const u = chatStore.currentUser || 'dev'
  const roles = chatStore.currentUserRoles.length ? chatStore.currentUserRoles.join(', ') : chatStore.currentUserRole || 'viewer'
  return `${u} (${roles})`
})

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

const sidebarExpanded = ref(false)
</script>

<template>
  <div class="layout" :class="{ 'sidebar-expanded': sidebarExpanded }">
    <aside
      class="sidebar"
      @mouseenter="sidebarExpanded = true"
      @mouseleave="sidebarExpanded = false"
    >
      <div class="brand">
        <div class="brand-logo">K</div>
        <div class="brand-copy">
          <strong>Kylin SafeOps</strong>
          <span>安全智能运维 Agent</span>
        </div>
      </div>

      <el-menu
        router
        :default-active="$route.path"
        background-color="transparent"
        text-color="#64748b"
        active-text-color="#2563eb"
      >
        <el-menu-item v-for="menu in menus" :key="menu.path" :index="menu.path">
          <el-icon><component :is="menu.icon" /></el-icon>
          <span class="menu-label">{{ menu.title }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-hint">
        <span class="hint-dot" />
        <span class="hint-copy">移出侧栏自动收起</span>
      </div>
    </aside>

    <section class="main">
      <header class="topbar">
        <div class="environment">
          <span class="env-dot" />
          麒麟高级服务器版 V11 / LoongArch 演示环境
        </div>
        <div class="top-actions">
          <el-tag type="info" effect="light" size="small">{{ identityText }}</el-tag>
          <el-tag type="success" effect="light">Agent Online</el-tag>
          <el-tag type="warning" effect="light">安全护栏已启用</el-tag>
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
  --sidebar-width: 86px;
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.82), rgba(238, 244, 255, 0.70)),
    var(--ks-bg);
  transition: grid-template-columns 220ms ease;
}
.layout.sidebar-expanded {
  --sidebar-width: 264px;
}
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  border-right: 1px solid rgba(219, 227, 239, 0.82);
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(18px);
  padding: 18px 12px;
  overflow: hidden;
  box-shadow: 10px 0 30px rgba(15, 23, 42, 0.04);
  transition:
    width 220ms ease,
    background 180ms ease,
    box-shadow 180ms ease;
}
.sidebar:hover {
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 16px 0 44px rgba(37, 99, 235, 0.12);
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 236px;
  padding: 8px 8px 24px;
}
.brand-logo {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb, #06b6d4);
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.26);
  font-weight: 800;
}
.brand-copy,
.menu-label,
.hint-copy {
  opacity: 0;
  transform: translateX(-6px);
  pointer-events: none;
  white-space: nowrap;
  transition:
    opacity 160ms ease,
    transform 160ms ease;
}
.sidebar-expanded .brand-copy,
.sidebar-expanded .menu-label,
.sidebar-expanded .hint-copy {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}
.brand strong,
.brand span {
  display: block;
}
.brand strong {
  color: var(--ks-text);
}
.brand span {
  margin-top: 4px;
  color: var(--ks-text-muted);
  font-size: 12px;
}
.el-menu-item {
  height: 44px;
  border-radius: 12px;
  margin: 5px 0;
  transition:
    background 160ms ease,
    color 160ms ease,
    transform 160ms ease;
}
.el-menu-item:hover {
  background: #eef4ff;
  color: var(--ks-primary);
  transform: translateX(3px);
}
.el-menu-item.is-active {
  background: linear-gradient(135deg, #eaf1ff, #f7fbff);
  box-shadow: inset 3px 0 0 var(--ks-primary);
  font-weight: 700;
}
.sidebar-hint {
  position: absolute;
  left: 20px;
  right: 16px;
  bottom: 18px;
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 220px;
  color: var(--ks-text-muted);
  font-size: 12px;
}
.hint-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--ks-primary);
  box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.12);
}
.main {
  min-width: 0;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  height: 64px;
  border-bottom: 1px solid rgba(219, 227, 239, 0.82);
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--ks-text-muted);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px);
}
.environment {
  display: flex;
  align-items: center;
  min-width: 0;
  font-weight: 600;
}
.env-dot {
  width: 9px;
  height: 9px;
  display: inline-block;
  margin-right: 10px;
  border-radius: 999px;
  background: var(--ks-success);
  box-shadow: 0 0 0 6px rgba(22, 163, 74, 0.12);
}
.top-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.content {
  padding: 26px;
}
@media (max-width: 900px) {
  .layout,
  .layout.sidebar-expanded {
    --sidebar-width: 0px;
    display: block;
  }
  .sidebar {
    display: none;
  }
  .topbar {
    padding: 0 16px;
  }
  .content {
    padding: 18px;
  }
}
</style>
