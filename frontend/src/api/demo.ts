import { request } from './request'

/**
 * demo.ts
 *
 * 演示场景接口模块。
 *
 * 这个文件服务于 DemoView.vue，用于比赛演示准备和触发场景。
 * 演示接口通常只在开发/演示环境启用，生产环境应当由后端权限控制或禁用。
 *
 * 注意：
 * - 这些接口不是 stream.py 事件流契约；
 * - 它们只是“准备故障数据 / 触发演示 / 清理演示数据”的 REST 操作。
 */

/**
 * 准备某个演示场景的数据。
 *
 * 使用位置：
 * - src/views/DemoView.vue 点击“准备数据”。
 *
 * 请求方式：
 * - POST /api/demo/{scenario_id}/prepare
 *
 * 请求体：
 * @param scenario 场景 ID，例如 disk_full、zombie_process、prompt_injection、config_drift。
 *
 * 返回数据建议：
 * - { status: 'ready', message: '...' }
 */
export function prepareDemoScenario(scenario: string) {
  return request.post('/api/demo/{scenario_id}/prepare', { scenario })
}

/**
 * 运行某个演示场景。
 *
 * 使用位置：
 * - DemoView.vue 点击“开始演示”。
 *
 * 请求方式：
 * - POST /api/demo/{scenario_id}/run
 *
 * 请求体：
 * @param scenario 场景 ID。
 *
 * 返回数据建议：
 * - { trace_id, status }，后续可跳转到 ChatView 查看事件流。
 */
export function runDemoScenario(scenario: string) {
  return request.post(`/api/demo/${scenario}/run`)
}

/**
 * 清理某个演示场景产生的数据。
 *
 * 使用位置：
 * - DemoView.vue 点击“清理数据”。
 *
 * 请求方式：
 * - POST /api/demo/{scenario_id}/cleanup
 *
 * 请求体：
 * @param scenario 场景 ID。
 *
 * 返回数据建议：
 * - { status: 'cleaned', message: '...' }
 */
export function cleanupDemoScenario(scenario: string) {
  return request.post('/api/demo/{scenario_id}/cleanup', { scenario })
}
