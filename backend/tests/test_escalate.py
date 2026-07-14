"""B6 L-M1: escalate 修真守门测试。

修真后 escalate_approval 不再吞 audit.append IntegrityError — S8 fail-closed 透传。
"""

from __future__ import annotations

import sqlite3
from unittest import mock

import pytest


def test_t5_escalate_appends_audit_no_swallow() -> None:
    """T5: 修真后审计失败不吞 — audit.append raise IntegrityError 路径透传 (S8 fail-closed)."""
    from backend.app.api.auth import Principal
    from backend.app.api.routers import approvals as ap
    from backend.app.api.schemas import EscalateRequest

    # audit 装 append.side_effect = IntegrityError (修真后真 raise 透传)
    audit = mock.MagicMock()
    audit.append.side_effect = sqlite3.IntegrityError("audit chain broken")
    audit.last_hash.return_value = ""

    src_session = mock.MagicMock()
    src_session.to_role = "operator"
    src_session.to_user = "alice"
    src_session.user_intent = "restart cron.service"
    registry = mock.MagicMock()
    registry.get.return_value = src_session
    ...
    body = EscalateRequest(to_user="bob", to_role="operator")
    principal = Principal(user="alice", roles=frozenset({"operator", "admin"}))
    with pytest.raises(sqlite3.IntegrityError):
        import asyncio

        asyncio.run(
            ap.escalate_approval(
                trace_id="trace-x",
                body=body,
                principal=principal,
                audit=audit,
                registry=registry,
            )
        )
    # 修真后不吞 — IntegrityError 透传 ✓
    assert audit.append.called, "T5: audit.append 必须真被调 (修真前是 except:pass 跳过)"
