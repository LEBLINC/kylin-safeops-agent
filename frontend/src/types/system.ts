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
