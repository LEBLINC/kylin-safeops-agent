# 功能测试矩阵 F001–F006（提案，★待 L 确认）

> 背景：D19 功能测试 F001–F006 在现有规划文档(Build-Guide / 22天计划)中**未见精确定义**
> （仓库 grep 无命中）。本文据 orchestrator / api / 演示场景的现有能力**起草**一份功能测试
> 矩阵提案，编号待 L 拍板后固化。脚手架见 `backend/tests/test_functional_matrix.py`。
>
> 原则：不猜测、不硬编安全断言。依赖 D 真 PolicyEngine/Executor 的断言用 `pytest.skip`
> 待激活（同 L1 哨兵套路），D 真件合入即自动生效。

---

## 矩阵

| 编号 | 名称 | 验证点 | 依赖 | 脚手架状态 |
|---|---|---|---|---|
| **F001** | 只读单工具链路 | 只读工具(R0/R1)→allow→执行→VERIFIED→FINISHED | fake 可跑 | ✅ 已写 |
| **F002** | 观测→二次规划→审批→执行 | need_observation 多段，confirm 审批后执行（磁盘满场景） | fake 可跑 | ✅ 已写 |
| **F003** | 多工具原子计划（全 allow） | 批次内多只读工具按序执行，逐工具 tool_result 留痕 | fake 可跑 | ✅ 已写 |
| **F004** | 高危 R3 审批闸 | R3→confirm/admin→WAIT_APPROVAL→resume→执行；拒绝→REJECTED | fake 可跑 | ✅ 已写 |
| **F005** | 危险命令策略拦截 | 命中 deny 规则(如 /etc/shadow)→整批 REJECTED、不执行 | **D 真 evaluate** | ⏸️ skip 待激活 |
| **F006** | SSE 事件流端到端 | POST /api/chat→trace_id→SSE 收事件流至 done | fake 可跑 | ✅ 已覆盖(见下) |

---

## 说明

- **F001–F004**：在 orchestrator + fake 协作者上跑通，断言**终态 + 执行序 + 关键事件**，
  不断言"安全拦截结果"（happy-path 管道）。复用演示剧本与 `RiskBasedPolicy` 参考桩。
- **F005**：危险命令被 deny 属**策略实质行为**，依赖 D 的真 `evaluate`。脚手架用
  `pytest.importorskip` / try-import 待命，D 从 `backend.app.security` 导出 `PolicyEngine` 即激活
  （与 `test_e2e_real_policy.py` 同机制；该哨兵已覆盖 deny/原子计划，F005 在功能层再表述一次）。
- **F006**：SSE 端到端已由 `backend/tests/test_api_endpoints.py::test_chat_post_then_sse_to_done`
  覆盖；矩阵脚手架以引用方式登记，避免重复装配 ASGITransport。

## 待 L 确认项

1. F001–F006 的**编号与命名**是否采纳本提案（或对齐既有评分表/验收清单）。
2. 是否需要补充：F007 审批拒绝路径、F008 schema 校验拦截、F009 结果闸 is_untrusted 强制
   （这些已在单元层 test_orchestrator.py / test_mcp_gateway.py 覆盖，是否上升为功能用例）。
3. F005 deny 用例的"危险命令样本集"是否对齐红队 S001–S007（当前 DEFAULT_POLICY 已含 CMD/FILE 规则）。
