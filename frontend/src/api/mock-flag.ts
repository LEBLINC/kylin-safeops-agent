/** H11：isMockEnabled 抽离为零依赖独立文件，防止 mock.ts 554 行随主 bundle 打包。
 *
 * 从原 mock.ts:41 抽出，逻辑完全不变。零依赖，不进 mock.ts 的 fake agent 逻辑链。
 */
export function isMockEnabled(): boolean {
  return String(import.meta.env.VITE_MOCK_ENABLED || '').toLowerCase() === 'true'
}
