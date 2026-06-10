/**
 * format.ts
 *
 * 通用格式化工具函数。
 *
 * 该文件只负责把原始数据转换成页面更容易阅读的文本，
 * 不应该在这里写业务判断，也不应该在这里请求后端。
 */

/**
 * 格式化字节数。
 *
 * 使用位置：
 * - DashboardView.vue 展示磁盘/内存容量时可用；
 * - ToolCallCard.vue 展示工具返回的文件大小时可用。
 *
 * 入参：
 * @param bytes 原始字节数，例如 1073741824。
 *
 * 返回：
 * - 例如 1024 -> "1.0 KB"，1073741824 -> "1.0 GB"。
 * - 如果入参为空或不是数字，返回 "-"。
 */
export function formatBytes(bytes?: number) {
  if (bytes === undefined || bytes === null || Number.isNaN(bytes)) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

/**
 * 格式化百分比。
 *
 * 使用位置：
 * - DashboardView.vue 指标卡。
 *
 * 入参：
 * @param value 原始百分比数字，例如 92.4。
 *
 * 返回：
 * - "92%"。
 * - 空值返回 "-"。
 */
export function formatPercent(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return `${Math.round(value)}%`
}

/**
 * 安全格式化 JSON。
 *
 * 使用位置：
 * - ToolCallCard.vue 展示工具参数/结果；
 * - AuditView.vue 展示审计记录 content；
 * - ApprovalCard.vue 展示审批工具参数。
 *
 * 入参：
 * @param value 任意 JS 值。
 *
 * 返回：
 * - 如果可以 JSON.stringify，则返回带缩进的 JSON 字符串；
 * - 如果遇到循环引用或不可序列化对象，则降级为 String(value)。
 */
export function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
