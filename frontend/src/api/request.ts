import axios from 'axios'

/**
 * request.ts
 *
 * Axios 基础请求封装。
 *
 * 本项目所有真实后端 REST 请求都从这里发出，页面和 Store 不直接使用 axios。
 * 好处：
 * 1. 后端地址集中由 VITE_API_BASE_URL 控制；
 * 2. 超时时间、错误处理集中管理；
 * 3. 后续要加 token、登录态、统一错误提示时只改本文件。
 *
 * Mock 说明：
 * - Mock 不在这里判断；
 * - 各业务 api 文件，例如 api/chat.ts、api/rca.ts，会先判断 VITE_MOCK_ENABLED；
 * - 只有关闭 Mock 时，才会真正调用本 request 实例。
 */

/**
 * 后端 API 基础地址。
 *
 * 示例：
 * - 本地代理：空字符串，走 Vite proxy；
 * - 直连后端：http://127.0.0.1:8000；
 * - 部署环境：https://safeops.example.com。
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/** Axios 实例。 */
export const request = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000
})

/**
 * 请求拦截器：注入 X-User-Role。
 *
 * L 的 4 个新 Router（approvals/audit/policy/demo）统一使用
 * require_proxy_identity 依赖，dev 模式下要求此 header，否则 401。
 * Chat 等老端点用 verify_token，dev 模式下不校验此 header，带了也无害。
 */
request.interceptors.request.use(config => {
  const role = import.meta.env.VITE_CURRENT_USER_ROLE
  if (role) {
    config.headers.set('X-User-Role', role)
  }
  return config
})

/**
 * 响应拦截器。
 *
 * 成功时：直接返回 response.data，让 api 文件拿到业务数据。
 * 失败时：统一转成 Error(message)，Store/View 可以直接显示 error.message。
 */
request.interceptors.response.use(
  response => response.data,
  error => {
    const message = error?.response?.data?.detail || error?.response?.data?.message || error?.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

/**
 * 拼接 SSE/REST URL。
 *
 * 使用位置：api/chat.ts 的 connectChatStream()。
 *
 * @param path 后端返回的 stream_url，或默认的 /api/chat/{trace_id}/events。
 * @returns 可直接传给 EventSource 的完整 URL。
 */
export function buildApiUrl(path: string) {
  if (/^https?:\/\//.test(path)) return path
  const base = API_BASE_URL || ''
  if (!base) return path
  return `${base.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
}
