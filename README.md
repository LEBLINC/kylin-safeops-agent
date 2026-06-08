# Kylin SafeOps Agent

部署于 LoongArch + 麒麟高级服务器版 V11 的 B/S 安全智能运维 Agent。
核心叙事：把大模型当**不可信顾问**，安全由确定性代码（策略引擎 + 最小权限 + 沙箱 + 哈希链审计）兜底。

## 五道安全闸
输入闸 → 策略引擎(allow/deny/confirm) → 人工确认闸 → 结果闸(不可信标记) → 审计闸(哈希链)

## 仓库结构
- `backend/app/` —— contracts(契约) / llm / mcp / agent / api / security / executor / audit / db
- `mcp_servers/` —— os_ops(感知与变更工具) / rca
- `third_party/` —— 原样保留的 fork 源码及其 LICENSE（见 NOTICE）
- `frontend/ deploy/ demo/ docs/` —— 前端 / 部署 / 演示 / 提交物

## 开发约定（铁律摘要）
1. 绝不 `subprocess(shell=True)`；命令只走模板白名单。
2. LLM 只输出"工具名 + 结构化参数 + 理由"的 JSON，绝不裸 shell。
3. 工具结果回喂 LLM 前包成 `ToolResult(is_untrusted=True)` 并加定界符。
4. 路径一律 canonicalize 且禁 `..` 逃逸。
5. 优先纯 Python；**前端在 x86 build**，绝不在 LoongArch 跑 npm build。

## 构建与校验
- 后端依赖：`pip install -r backend/requirements.txt`（LoongArch 上含 Rust/C 扩展依赖如 pydantic-core 需预编译 wheel）。
- 本地校验：`pre-commit run --all-files`（ruff + mypy[仅 contracts] + pytest）。
- CI 在 **x86** 跑（见 `.github/workflows/ci.yml`）；LoongArch 兼容性以真机另验，CI 不覆盖。

## 协议与模型
- MCP 协议层：官方 `mcp` Python SDK（pin v1.x）+ 自写薄 adapter。
- 模型：Qwen3 / DeepSeek 经 OpenAI 兼容网关接入。

> 第三方来源与许可见 `NOTICE`；许可证见 `LICENSE`（Apache-2.0）。
