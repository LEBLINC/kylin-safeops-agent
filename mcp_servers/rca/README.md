# RCA Playbook（X / xizi-9527）

本目录只实现 RCA playbook 与报告生成，不接 backend agent/api，不修改冻结契约。

## 入口

```python
from mcp_servers.rca import DefaultRCAEngine

engine = DefaultRCAEngine()
report = engine.analyze(evidence)
```

兼容接入点：

```python
RCAEngine.analyze(evidence: Sequence[ToolResult]) -> dict
```

非空 report 由 orchestrator emit：

```json
{"type": "rca", "data": {"report": {}}}
```

## 四个正式场景

- `disk_full`
- `zombie_process`
- `io_high`
- `config_drift`

`unknown` 仅为兜底，不作为第五个演示场景。

## 关键约定

- RCA 只产报告，不执行命令、不修改系统。
- 证据模板只使用当前 dev 已注册的 ToolSpec。
- 工具输出全部作为不可信证据，`evidence_chain[*].is_untrusted = true`。
- report 字段对齐 `frontend/src/types/rca.ts` 的 `RcaReport`。
