"""审计库路径解析 + 权限加固测试（Phase 3a，决策⑪）。"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from backend.app.db.session import connect, resolve_audit_db_path


def test_resolve_default_when_empty() -> None:
    assert resolve_audit_db_path(None, require_absolute=False) == "./data/audit.db"
    assert resolve_audit_db_path("  ", require_absolute=True) == "./data/audit.db"


def test_resolve_memory_short_circuit() -> None:
    """:memory: 短路，不触发绝对路径校验（保护测试夹具）。"""
    assert resolve_audit_db_path(":memory:", require_absolute=True) == ":memory:"


def test_resolve_relative_rejected_in_prod() -> None:
    with pytest.raises(ValueError):
        resolve_audit_db_path("data/audit.db", require_absolute=True)


def test_resolve_relative_ok_in_dev() -> None:
    assert resolve_audit_db_path("data/audit.db", require_absolute=False).endswith("audit.db")


def test_resolve_absolute_ok_in_prod(tmp_path: Path) -> None:
    abs_path = str(tmp_path / "audit.db")
    assert os.path.isabs(resolve_audit_db_path(abs_path, require_absolute=True))


@pytest.mark.skipif(platform.system() == "Windows", reason="chmod 位语义在 Windows 不同")
def test_secure_perms_on_connect(tmp_path: Path) -> None:
    """connect 文件路径后：库 0600、父目录 0700（Linux）。"""
    db = tmp_path / "sub" / "audit.db"
    conn = connect(db)
    conn.close()
    assert (os.stat(db).st_mode & 0o777) == 0o600
    assert (os.stat(db.parent).st_mode & 0o777) == 0o700


def test_memory_connect_no_perms_no_crash() -> None:
    """:memory: connect 不触发 _secure_perms，不崩（夹具保护回归）。"""
    conn = connect(":memory:")
    conn.close()
