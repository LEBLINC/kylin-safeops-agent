# ADR-0003：真 LLM 接入范围冻结为 demo 脚本 + D VM 实证,live API 仍 fake

- 状态：**已接受（Accepted）** — 2026-06-19
- 关联：[ADR-0002](0002-stage5-real-llm-kylin-vm-closure.md)（阶段5 收口）、决策⑨（RBAC 反代签名）、`backend/app/api/app.py:91 get_llm()`

## 背景（Context）

阶段5 真实 LLM 接入（ADR-0002）已在麒麟 V11 实机收口——但**作用域是 `scripts/demo_stage4_e2e.py --use-real-llm` + D 在 VM 上真跑**。另一窗口对 dev=`e2bd033` 架构审阅指出：`backend/app/api/app.py:91` `get_llm()` 仍 `return build_fake_llm()`（docstring 自承"待接真实 LLM 端点"），**前端聊天 → live API → fake LLM**。real_client.py / S3 真校验 / O18 去毒在产品运行态根本不执行。

需就此明确"真 LLM 接入范围"以避免对外口径虚高。

## 决策（Decision）

**真 LLM 接入范围冻结为两条窄路径**：

1. **演示脚本**：`scripts/demo_stage4_e2e.py --use-real-llm --user-intent "..."`（场景 G）
2. **D 在 VM 上的真端点实证**：VM 上 export `KYLIN_LLM_PROVIDER=real` + base_url/api_key/model 走 demo 脚本

**`backend/app/api/app.py get_llm()` 保持 fake 不接真 LLM**——这是有意识的设计，不是 TODO。理由：

- **真 LLM 是不可信顾问**，"接进 live API 让前端用户直连真模型"超出本阶段安全边界审查范围（决策⑨ 边界、反代认证审计、注入红队全套只覆盖 fake 模式）
- 真 LLM 接入要新增：模型配额管理 / 多租户隔离 / 用户级 rate limit / 真实计费 / 内容合规审计——这些都不在阶段5 范围
- demo 脚本 + VM 实证已足证明"地板 + 真 LLM 共存时被注入也被拦死"——这是 ADR-0002 的核心论据，不需要 live API 重复

## 后果（Consequences）

- 正面：对外口径清晰——"真 LLM 仅 demo 脚本 + D VM 实证；web UI/live API 仍 fake"。避免叙事虚高。
- 代价：客户若想在 web UI 体验真 LLM，必须另开 ADR 重新审议（多租户、计费、合规）。
- 对内：`get_llm()` docstring 改为"保持 fake 是设计意图，非 TODO"，移除"待接真实 LLM 端点"措辞。
- 对外：所有交付材料、demo 录屏、客户验收口径，必须明确"web UI 走 fake，demo 脚本走真 LLM"。

## 不锁死（迁移路径）

若未来 web UI 需接真 LLM：

1. 新增 ADR 重新审议（本决策**不**阻碍，只要求重新走决策流程）
2. `get_llm()` 按 `KYLIN_LLM_PROVIDER` 装配 `RealLLMClient(...).completion_fn + tool_specs`
3. 新增：每用户 rate limit / token 配额 / 审计（用户级）/ 内容合规闸
4. 跨切：前端 UI 需"真/假"切换可视化（让用户知道当前 LLM 是 fake 还是真）

## Revisit 条件

满足任一即重启评估：

1. **客户明确要求 web UI 接真 LLM**（典型场景：要让用户在生产环境体验 LLM 产 intent）
2. **多用户生产部署**（需用户级 rate limit / 配额）
3. **合规要求**（金融/医疗需真模型推理留痕）
4. **demo 脚本被废**（若 demo 阶段走完，live 必接）

## 备选方案（Alternatives considered）

- **接 live API**：被否。理由见"决策"三条。当前阶段无该需求 + 多租户/计费/合规超出范围。
- **完全废弃 demo 脚本**：被否。demo 脚本是 ADR-0002 论证基础，废弃意味着 ADR-0002 论据失效。
