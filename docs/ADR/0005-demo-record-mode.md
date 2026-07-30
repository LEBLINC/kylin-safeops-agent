# ADR-0005：KYLIN_LLM_RECORD 录制模式（demo-record-mode）

- 状态：**已接受（Accepted）** — 2026-07-13
- 关联：[ADR-0003](0003-real-llm-demo-only-scope.md)（demo-only 默认锁死）、[ADR-0002](0002-stage5-real-llm-kylin-vm-closure.md)（阶段5 真 LLM 接入）、`backend/app/api/app.py:88 get_llm()`、`backend/tests/test_get_llm_record_mode.py`（新建）

## 背景（Context）

D 在 demo 录屏场景有"前端聊天 → live API → 真 LLM 推理"的录屏需求；当前 `get_llm()`
硬编码 `return build_fake_llm()`（[ADR-0003](0003-real-llm-demo-only-scope.md) demo-only 设计意图），
**前端聊天永远走 fake**，录屏拿不到真 LLM 推理回包。

ADR-0003 锁死的论据仍成立（多租户/计费/合规/用户级 rate limit 缺位 → live API 不应直连真 LLM）。
但 demo 录屏是**单用户、单会话、可控录制**场景——与生产 live API 安全边界审查
不在同一量级。需新增一个**最小侵入的 opt-in 录制模式**，而非撤 ADR-0003。

## 决策（Decision）

**新增 `KYLIN_LLM_RECORD` 录制模式（demo-record-mode）**——`get_llm()` 装配时
按 env 分支：

```python
if os.environ.get("KYLIN_LLM_RECORD", "").strip().lower() == "true":
    real = RealLLMClient()  # 读 KYLIN_LLM_BASE_URL / API_KEY / MODEL env
    return LLMAdapter(completion_fn=real.completion_fn)
return build_fake_llm()  # ADR-0003 默认
```

**配套守门（不破 ADR-0003 demo-only 锁死）**：

| env 状态 | get_llm() 返 | D2 §5 红线守门 |
|---|---|---|
| 未设 | `LLMAdapter(fake closure)` | T9/T10/completion_fn_spy 三件套 spy == 0 ✅ |
| `KYLIN_LLM_RECORD=false` | `LLMAdapter(fake closure)` | T3 fake fixture ✅ |
| `KYLIN_LLM_RECORD=true` | `LLMAdapter(RealLLMClient.completion_fn)` | T11 spy >= 1 ✅（录制模式显式放行） |

**显式边界**：

- `/api/llm/health?probe=true` **不受** `KYLIN_LLM_RECORD` 影响——probe 是 lifespan
  内显式构造 fake 实例做连通性自检，不经 `get_llm()` 装配
- **生产 `KYLIN_LLM_RECORD` 永远 false**（仅 demo 录屏 / 内网联调 opt-in 启用）
- 默认 `KYLIN_LLM_RECORD=false`（与 unset 等价），保留 ADR-0003 demo-only 锁死

## 后果（Consequences）

- 正面：D 在 demo 录屏场景可切真 LLM 推理回包，无需撤 ADR-0003（多租户/计费/合规
  仍不在范围）；与 demo 脚本 `scripts/demo_stage4_e2e.py --use-real-llm` 的
  `RealLLMClient` 复用同一份 `real_client.py`（不重复实现）
- 代价：增加 1 个 env 旋钮；增加 3 用例（test_get_llm_record_mode.py）+ 1 用例
  （test_d2_chat_always_fixture.py T11）的守门成本
- 对内：默认 web UI / live API 仍 fake（ADR-0003 守门不破）
- 对外：所有 demo 录屏材料、客户验收口径，必须明确"录制模式经
  `KYLIN_LLM_RECORD=true` opt-in 启用；live API 默认 fake"

## 不锁死（迁移路径）

若未来 web UI 需接真 LLM（非录制场景）：

1. 新增 ADR 重新审议（本决策**不**阻碍，只要求重新走决策流程）
2. `get_llm()` 按 `KYLIN_LLM_PROVIDER`（非 `KYLIN_LLM_RECORD`）装配
   `RealLLMClient(...).completion_fn + tool_specs`
3. 新增：每用户 rate limit / token 配额 / 审计（用户级）/ 内容合规闸
4. 跨切：前端 UI 需"真/假"切换可视化（让用户知道当前 LLM 是 fake 还是真）

## Revisit 条件

满足任一即重启评估：

1. **项目正式完成 = 阶段5 step 2 全套 6 commit 收口后**——撤 ADR-0005 + ADR-0003，
   `get_llm()` 改按 `KYLIN_LLM_PROVIDER` 装配真 LLM（live API 直连）
2. **多用户生产部署**（需用户级 rate limit / 配额 / 计费 / 合规）
3. **客户明确要求 web UI 接真 LLM**（非录制场景）

## 备选方案（Alternatives considered）

- **A. 撤 ADR-0003、`get_llm()` 直连真 LLM**：被否。理由见 ADR-0003 三条代价；
  当前阶段无 live API 直连真 LLM 的业务需求，仅 demo 录屏需要
- **B. 新增独立端点（如 `/api/chat/record`）走真 LLM**：被否。增加路由表面积 +
  前端要做路由切换；`KYLIN_LLM_RECORD` 单 env 旋钮更轻
- **C. `get_llm()` 按 env 分支（本次方案）**：采纳。最小侵入、与 demo 脚本复用
  `RealLLMClient`、守门三重钉死默认 fake + 显式 opt-in 录制模式
- **D. 完全不动 `get_llm()`，demo 录屏用 demo 脚本独立产出**：被否。demo 脚本
  是命令行 / 非交互场景，不支持前端聊天实时联调；客户验收需要 live API 路径

## 与既有契约的兼容

- ADR-0003（demo-only 默认锁死）：守门语义**不破**——默认 spy == 0 仍断言
- ADR-0002（阶段5 真 LLM 接入）：复用同一份 `RealLLMClient` 实现，
  `real_client.py` 内部不动
- S9（密钥走 env 绝不入库）：`RealLLMClient` 已实现 env 注入
  `KYLIN_LLM_BASE_URL` / `KYLIN_LLM_API_KEY` / `KYLIN_LLM_MODEL`，
  本 ADR 无新增密钥处理
- 决策①-⑬（已冻结）：本 ADR 不涉及
