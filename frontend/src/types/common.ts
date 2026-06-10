/**
 * common.ts
 *
 * 全局通用类型文件。
 *
 * 这里放“多个 API / 页面都会用到”的基础类型，避免每个模块重复定义。
 * 这些类型不是 stream.py 的事件流契约，只是前端工程和 REST 接口常用结构。
 */

/**
 * ApiResponse<T>
 *
 * 通用后端响应包裹结构。
 *
 * 使用场景：
 * - 如果后端统一返回 { code, message, data }，就可以用这个类型。
 * - 当前 request.ts 做了 axios 封装，部分接口直接返回 data，因此不是所有接口都必须使用它。
 *
 * 字段说明：
 * @field code 后端业务状态码，例如 0 表示成功，非 0 表示业务错误。
 * @field message 后端提示信息，通常用于错误提示或操作结果说明。
 * @field data 真正的业务数据，类型由泛型 T 决定。
 */
export interface ApiResponse<T> {
  code?: number
  message?: string
  data: T
}

/**
 * PageResult<T>
 *
 * 通用分页列表结构。
 *
 * 使用场景：
 * - 审计日志列表；
 * - 会话列表；
 * - 工具调用历史列表。
 *
 * 字段说明：
 * @field items 当前页的数据数组。
 * @field total 符合查询条件的数据总数，用于分页控件。
 */
export interface PageResult<T> {
  items: T[]
  total: number
}

/**
 * LoadStatus
 *
 * 前端异步加载状态。
 *
 * 用途：
 * - 统一表示页面或组件的数据加载阶段。
 * - idle：还未开始加载；loading：正在加载；success：加载成功；error：加载失败。
 */
export type LoadStatus = 'idle' | 'loading' | 'success' | 'error'
