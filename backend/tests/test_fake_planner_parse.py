"""步骤 1：fake planner 解析 user_intent 回归。

安全层 94bdac9 把 `target_service` / `target_log_path` 参数化（默认仍 cron.service /
/var/log/app.log）。本文件固化编排层 fake planner 解析规则：
- `重启 sshd` / `restart cron.service` → service.restart + 解析 service_name
- `压缩 /var/log/app.log` / `轮转 <path>` → log.compress_rotate + 解析 path
- `查 /etc/shadow` / `lsof <path>` → file.lsof_check + 解析 path
- `查看磁盘` / `磁盘占用` → disk.usage
- 其它 → system.info（fallback，兼容既有"看系统"测试）

**不引入 NLP**——纯 keyword matching + 正则提参；CI 友好。

每个用例走 `build_fake_llm()` → 调 adapter.plan() 跑真实 parse_intent 路径
（与生产一致，不绕过 schema 校验）。
"""

from __future__ import annotations

import asyncio

from backend.app.api._fakes import build_fake_llm


def _plan_sync(text: str) -> dict:
    """跑一次 fake LLM plan()，返回解析后的 Intent dict。"""
    llm = build_fake_llm()

    async def _go() -> dict:
        intent = await llm.plan([{"role": "user", "content": text}])
        return intent.model_dump()

    return asyncio.run(_go())


def test_parse_restart_extracts_service_name() -> None:
    """`重启 sshd` → service.restart + service_name=sshd.service（自动补 .service 后缀）。"""
    intent = _plan_sync("重启 sshd")
    tools = intent["candidate_tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "service.restart"
    assert tools[0]["args"]["service_name"] == "sshd.service"
    assert intent["risk_hint"] == "high"


def test_parse_restart_explicit_service_name_kept() -> None:
    """`重启 cron.service` → service.restart + service_name=cron.service（保留显式后缀）。"""
    intent = _plan_sync("重启 cron.service")
    tools = intent["candidate_tools"]
    assert tools[0]["name"] == "service.restart"
    assert tools[0]["args"]["service_name"] == "cron.service"


def test_parse_compress_extracts_path() -> None:
    """`压缩 /var/log/app.log` → log.compress_rotate + path=/var/log/app.log。"""
    intent = _plan_sync("压缩 /var/log/app.log")
    tools = intent["candidate_tools"]
    assert tools[0]["name"] == "log.compress_rotate"
    assert tools[0]["args"]["path"] == "/var/log/app.log"
    assert intent["risk_hint"] == "medium"


def test_parse_lsof_extracts_path() -> None:
    """`查 /etc/shadow` → file.lsof_check + path=/etc/shadow（FILE001 演示配套）。"""
    intent = _plan_sync("查 /etc/shadow")
    tools = intent["candidate_tools"]
    assert tools[0]["name"] == "file.lsof_check"
    assert tools[0]["args"]["path"] == "/etc/shadow"


def test_parse_disk_usage_no_args() -> None:
    """`查看磁盘` → disk.usage（无参；R0 allow）。"""
    intent = _plan_sync("查看磁盘")
    tools = intent["candidate_tools"]
    assert tools[0]["name"] == "disk.usage"
    assert tools[0]["args"] == {}
    assert intent["risk_hint"] == "low"


def test_parse_unknown_falls_back_to_system_info() -> None:
    """未知指令 → system.info（R0 allow；与既有"看系统"测试兼容）。"""
    intent = _plan_sync("看看系统")
    tools = intent["candidate_tools"]
    assert tools[0]["name"] == "system.info"
