/**
 * system.ts
 *
 * 系统仪表盘相关类型。
 *
 * 这些字段来自 /api/system/* REST 接口，不属于 stream.py 事件流契约。
 * 当前 DashboardView.vue 使用这些字段展示 CPU、内存、磁盘、服务等状态。
 */

/**
 * MetricPoint
 *
 * 通用指标卡数据结构。
 *
 * 使用位置：
 * - MetricCard.vue 的数据来源可以转换成这个结构。
 *
 * 字段说明：
 * @field label 指标名称，例如 CPU 使用率。
 * @field value 指标值，可以是数字或已经格式化好的字符串。
 * @field status 指标状态，normal/warning/danger 决定卡片样式。
 * @field description 指标说明或补充信息。
 */
export interface MetricPoint {
  label: string
  value: string | number
  status?: 'normal' | 'warning' | 'danger'
  description?: string
}

/**
 * SystemOverview
 *
 * 仪表盘首页的系统总览数据。
 *
 * 使用位置：
 * - DashboardView.vue。
 *
 * 字段说明：
 * @field cpu_usage CPU 使用率百分比，例如 36 表示 36%。
 * @field memory_usage 内存使用率百分比。
 * @field root_disk_usage 根分区使用率百分比。
 * @field zombie_processes 僵尸进程数量。
 * @field tool_calls_today 今日工具调用次数，用于展示平台活跃度。
 * @field denied_today 今日安全策略拒绝次数，用于展示安全护栏效果。
 * @field services 关键服务状态列表，例如 nginx、safeops-agent、auditd。
 */
export interface SystemOverview {
  cpu_usage: number
  memory_usage: number
  root_disk_usage: number
  zombie_processes: number
  tool_calls_today: number
  denied_today: number
  services?: Array<{ name: string; status: string }>
  data_source: 'stub_executor' | 'partial' | 'real'
  probed_tools: string[]
}

/**
 * OverviewHistoryPoint
 *
 * 单条时序采样点，来自 GET /api/system/overview/history。
 * 字段名与后端 schemas.py OverviewHistoryPoint 严格对齐。
 *
 * 使用位置：
 * - DashboardView.vue 的 sparkline 趋势图。
 *
 * 字段说明：
 * @field ts epoch 秒，小时桶起点。
 * @field cpu CPU 使用率 %。
 * @field mem 内存使用率 %。
 * @field disk 根分区使用率 %。
 */
export interface OverviewHistoryPoint {
  ts: number
  cpu: number
  mem: number
  disk: number
}

/**
 * OverviewHistoryResponse
 *
 * GET /api/system/overview/history 的完整响应体。
 * 与后端 schemas.py OverviewHistoryResponse 严格对齐。
 */
export interface OverviewHistoryResponse {
  hours: number
  series: OverviewHistoryPoint[]
}

/**
 * SystemStats
 *
 * 任务态势聚合数据，来自 GET /api/system/stats。
 * 与后端 schemas.py SystemStats 严格对齐。
 *
 * 字段说明：
 * @field hours 回看窗口小时数。
 * @field by_tool 工具调用次数按 tool_name 聚合（来自 EXECUTING/EXECUTED records）。
 * @field by_risk 按 risk_level（R0/R1/R2/R3）分布（来自 INTENT_PARSED records）。
 * @field by_status 按终态 status（FINISHED/REJECTED/WAIT_APPROVAL）分布。
 */
export interface SystemStats {
  hours: number
  by_tool: Record<string, number>
  by_risk: Record<string, number>
  by_status: Record<string, number>
}
