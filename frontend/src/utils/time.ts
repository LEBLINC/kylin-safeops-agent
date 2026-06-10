import dayjs from 'dayjs'

/**
 * time.ts
 *
 * 时间格式化工具。
 *
 * 项目里后端时间可能有三种形态：
 * 1. stream.py 中 ts 是 epoch 秒；
 * 2. REST 接口可能返回 ISO 字符串；
 * 3. 前端本地生成 Date 对象。
 *
 * 本文件统一把这些时间转换成页面展示字符串。
 */

/**
 * 格式化时间。
 *
 * 使用位置：
 * - AgentTimeline.vue 展示事件时间；
 * - ChatView.vue 展示消息时间；
 * - AuditView.vue 展示审计时间。
 *
 * 入参：
 * @param input 支持 epoch 秒、ISO 字符串、Date 对象。
 *
 * 返回：
 * - "YYYY-MM-DD HH:mm:ss"。
 * - 空值返回 "-"。
 */
export function formatTime(input?: number | string | Date) {
  if (!input) return '-'
  if (typeof input === 'number') {
    return dayjs(input * 1000).format('YYYY-MM-DD HH:mm:ss')
  }
  return dayjs(input).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 格式化耗时。
 *
 * 使用位置：
 * - ToolCallCard.vue 展示工具调用耗时；
 * - ToolDetailView.vue 展示工具详情。
 *
 * 入参：
 * @param ms 毫秒数。
 *
 * 返回：
 * - 小于 1000 返回 "xxxms"；
 * - 大于等于 1000 返回 "x.xx s"。
 */
export function formatDuration(ms?: number) {
  if (ms === undefined || ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}
