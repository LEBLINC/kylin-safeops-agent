import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

/**
 * router/index.ts
 *
 * 前端路由配置文件。
 *
 * 作用：
 * - 定义浏览器路径和 Vue 页面之间的映射关系；
 * - 所有业务页面都挂在 MainLayout.vue 下面，共用左侧菜单和顶部栏。
 *
 * 设计说明：
 * - 采用懒加载 component: () => import(...)，减少首屏 JS 体积；
 * - 默认访问 / 时重定向到 /dashboard；
 * - ToolDetailView 使用动态参数 :callId，展示某次工具调用详情。
 */
export const router = createRouter({
  /** 使用 HTML5 history 模式，URL 不带 #。 */
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      redirect: '/dashboard',
      children: [
        /** 仪表盘首页：系统状态、风险统计、最近事件。 */
        { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue') },
        /** 智能对话页：会话、事件流、内联审批、打字机回复。 */
        { path: 'chat', name: 'Chat', component: () => import('@/views/ChatView.vue') },
        /** RCA 根因分析页：四类演示场景和证据链展示。 */
        { path: 'rca', name: 'RCA', component: () => import('@/views/RcaView.vue') },
        /** 风险审批页：管理员集中处理待审批操作。 */
        { path: 'approvals', name: 'Approvals', component: () => import('@/views/ApprovalView.vue') },
        /** 审计日志页：trace 回溯和哈希链校验。 */
        { path: 'audit', name: 'Audit', component: () => import('@/views/AuditView.vue') },
        /** 策略规则页：只读展示安全规则和风险等级。 */
        { path: 'policy', name: 'Policy', component: () => import('@/views/PolicyView.vue') },
        /** 工具列表页：展示 MCP 工具注册表。 */
        { path: 'tools', name: 'Tools', component: () => import('@/views/ToolsView.vue') },
        /** 工具调用详情页：展示某次工具调用参数、结果、风险等。 */
        { path: 'tools/:callId', name: 'ToolDetail', component: () => import('@/views/ToolDetailView.vue') },
        /** 演示场景页：准备/启动/清理比赛演示数据。 */
        { path: 'demo', name: 'Demo', component: () => import('@/views/DemoView.vue') },
        /** 系统设置页：只读展示前端配置和 mock 开关。 */
        { path: 'settings', name: 'Settings', component: () => import('@/views/SettingsView.vue') }
      ]
    }
  ]
})
