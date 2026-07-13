import { request } from './request'
import type { OverviewHistoryResponse, SystemOverview, SystemStats } from '@/types/system'

/**
 * system.ts
 *
 * 系统概览接口模块。
 *
 * 这个文件只负责“向后端拿系统状态数据”，不负责页面展示。
 * 页面展示在 DashboardView.vue 中完成。
 *
 * 典型数据流：
 * DashboardView.vue onMounted()
 *   → getSystemOverview()
 *   → request.ts 统一发送 HTTP 请求
 *   → 后端返回 CPU、内存、磁盘、进程、服务状态等数据
 *   → DashboardView.vue 用 MetricCard / StatusTag 展示
 *
 * Mock 说明：
 * 当前 v1.3 中 DashboardView.vue 内部仍保留默认展示数据。
 * 如果真实接口请求失败，页面会继续显示默认数据，避免演示时空白。
 * 后续若要更规范，可以把这些默认数据迁移到 src/api/mock.ts。
 */

/**
 * 获取系统总览数据。
 *
 * 使用位置：
 * - src/views/DashboardView.vue
 *
 * 请求方式：
 * - GET /api/system/overview
 *
 * 请求参数：
 * - 无
 *
 * 返回数据：
 * - SystemOverview
 * - 包含 CPU 使用率、内存使用率、根分区使用率、僵尸进程数、今日工具调用数、今日拒绝数、服务状态等。
 *
 * 字段契约说明：
 * - 该接口不是 stream.py 事件流契约的一部分。
 * - 字段由 Dashboard 仪表盘页面展示需求决定，需要后端单独对齐。
 */
export function getSystemOverview() {
  return request.get<SystemOverview, SystemOverview>('/api/system/overview')
}

/**
 * 获取磁盘使用详情。
 *
 * 使用位置：
 * - 预留给 DashboardView.vue 或后续磁盘详情弹窗使用。
 *
 * 请求方式：
 * - GET /api/system/disk
 *
 * 返回数据建议：
 * - 挂载点列表、总容量、已用容量、使用率、文件系统类型。
 *
 * 说明：
 * - 当前页面主流程暂未强依赖这个接口。
 */
export function getDiskUsage() {
  return request.get('/api/system/disk')
}

/**
 * 获取进程列表。
 *
 * 使用位置：
 * - 预留给系统仪表盘或进程诊断页面。
 *
 * 请求方式：
 * - GET /api/system/processes
 *
 * 返回数据建议：
 * - pid、ppid、command、cpu、memory、stat、是否僵尸进程。
 */
export function getProcessList() {
  return request.get('/api/system/processes')
}

/**
 * 获取服务状态列表。
 *
 * 使用位置：
 * - DashboardView.vue 的服务状态卡片；
 * - 后续服务异常 RCA 页面也可以复用。
 *
 * 请求方式：
 * - GET /api/system/services
 *
 * 返回数据建议：
 * - 服务名、active/inactive/failed 状态、最近启动时间、失败原因。
 */
export function getServiceStatus() {
  return request.get('/api/system/services')
}

/**
 * 获取系统概览历史时序数据。
 *
 * 使用位置：
 * - DashboardView.vue 的四张指标卡 sparkline 趋势图。
 *
 * 请求方式：
 * - GET /api/system/overview/history?range=15m
 *
 * 请求参数：
 * @param range 时间范围，默认 "15m"（支持 5m / 15m / 1h）。
 *
 * 返回数据：
 * - { points: TrendPoint[], range_seconds: number }
 * - points 按 ts 升序排列，前端按 key 提取各指标数组驱动 sparkline。
 */
export function getOverviewHistory(hours = 24) {
  return request.get<OverviewHistoryResponse, OverviewHistoryResponse>(
    '/api/system/overview/history',
    { params: { hours } }
  )
}

/**
 * 获取任务态势聚合统计。
 *
 * 使用位置：
 * - DashboardView.vue 的任务态势分布柱状图。
 *
 * 请求方式：
 * - GET /api/system/stats
 *
 * 请求参数：
 * @param since 统计起始时间（ISO），默认当日 00:00。
 * @param until 统计截止时间（ISO），默认当前。
 *
 * 返回数据：
 * - { executed, approved, denied, risk_total }
 */
export function getSystemStats(hours = 24) {
  return request.get<SystemStats, SystemStats>('/api/system/stats', {
    params: { hours }
  })
}
