# ADR-0006: real-mode-by-default (阶段5 step 2 收口生效)

- **状态**: Accepted (2026-07-14)
- **上下文**: 阶段5 step 2 真接 LLM 上线工单完成 (5 commit: 5.1 fake planner 修真 / 5.2 S3 schema retry / 5.3 rate+token audit / 5.4 决策⑫ 真验 / 5.5 ADR-0006 收口)
- **决策**: 默认走真接 LLM (KYLIN_LLM_BASE_URL/KYLIN_LLM_API_KEY/KYLIN_LLM_MODEL env 注入)
- **不再默认**: ADR-0003 demo-only (已标注退役,录制场景通过 KYLIN_LLM_RECORD=true 兼容)

## 守门
- `get_llm()` 默认真接;`KYLIN_LLM_FAKE=true` 显式 opt-in 回 fake 模式 (演示用)
- `KYLIN_LLM_RECORD=true` 录制模式 (ADR-0005 兼容)
- 4 commit pytest 守门 8 用例 (T1-T8)

## 不属本工单 (P4 backlog)
- 生产 SSO/LDAP 反代替换
- 审计库 retention/rotation
- Prometheus /metrics + 告警
- Dockerfile + systemd unit
- 压测 + token 预算
- 漏洞扫描 + Threat Model
- 灾备 + HA
- OpenAPI 文档 + 运维手册
