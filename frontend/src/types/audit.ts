/**
 * audit.ts
 *
 * 审计与哈希链相关类型。
 *
 * 与 stream.py 的关系：
 * - stream.py 只规定实时事件 audit_appended -> { seq: int, curr_hash: str }；
 * - 本文件中的 AuditTrace、AuditRecord、HashChainVerifyResult 是 REST 审计查询接口的数据结构，
 *   不属于 stream.py 强类型约束，需要和后端 /api/audit/* 单独对齐。
 */

/**
 * AuditTrace
 *
 * 审计列表中的一条 trace 摘要。
 *
 * 使用位置：
 * - AuditView.vue 左侧或上方审计记录列表。
 *
 * 字段说明：
 * @field trace_id 单次请求的全链路追踪 ID，对应 StreamEvent.trace_id。
 * @field session_id 所属会话 ID，可用于从审计跳回聊天会话。
 * @field user 触发该请求的用户或账号名。
 * @field intent 意图名称，例如 disk_full_diagnosis。
 * @field risk_level 本次请求最终风险等级，通常为 R0~R4。
 * @field decision 本次请求最终裁决，例如 allow、deny、confirm。
 * @field created_at 请求创建时间。
 * @field summary 审计摘要，供列表快速浏览。
 */
/** 与后端 schemas.py AuditTraceSummary 字段对齐。 */
export interface AuditTrace {
  trace_id: string
  first_user_intent: string
  record_count: number
  state: string
  first_seen: string
  last_seen: string
}

/**
 * AuditRecord
 *
 * 某个 trace 下的一条结构化审计记录。
 *
 * 使用位置：
 * - AuditView.vue 审计详情；
 * - HashChainViewer.vue 可用其中 hash 字段展示链条。
 *
 * 字段说明：
 * @field id 审计记录 ID。
 * @field trace_id 所属 trace。
 * @field seq 审计链序号，从 1 开始递增。
 * @field record_type 记录类型，例如 user_input、tool_call、policy_event、approval、result。
 * @field content 记录内容，按 record_type 不同而不同。
 * @field prev_hash 上一条审计记录的 hash。
 * @field curr_hash 当前审计记录的 hash。
 * @field created_at 写入审计记录的时间。
 */
/** 与后端 schemas.py AuditRecord 字段对齐。 */
export interface AuditRecord {
  seq: number
  phase: string
  payload: Record<string, unknown>
  prev_hash: string
  curr_hash: string
  created_at: string
}

/**
 * HashChainVerifyResult
 *
 * 某个 trace 的哈希链校验结果。与后端 schemas.py AuditVerifyResponse 字段对齐。
 *
 * 使用位置：
 * - AuditView.vue 调用 verify() 后保存；
 * - HashChainViewer.vue 展示整体是否完整。
 *
 * 字段说明：
 * @field trace_id 被校验的 trace。
 * @field valid 整条链是否全部通过。
 * @field record_count 参与校验的记录数。
 * @field broken_seq 第一个校验失败的序号；null 表示全部通过。
 * @field reason 校验结论说明（通过或失败原因）。
 */
export interface HashChainVerifyResult {
  trace_id: string
  valid: boolean
  record_count: number
  broken_seq: number | null
  reason: string
}
