"""P1-12: 关键数据库日志与审计日志在裁决层漏判。

赛题原文举的"误删数据库日志"例子，当前恰好是漏判的正面案例：

    log.compress_rotate{path: "/var/log/mysql/mysql-bin.000001"}

forbid_delete 只有 /var/lib/mysql、/var/lib/pgsql；DBLOG001 正则限
/var/lib/mysql/ 前缀。故上面这条只命中 rotate_only=["/var/log"]
→ R2 / operator 即可批准，一次点击就以 root 压掉 binlog。

三类漏判：
  ① 库日志落在 /var/log/ 下（mysql/pgsql 的常见部署）——父目录前缀判不到
  ② /var/lib/postgresql（Debian 系默认）、国产库数据目录不在清单里
  ③ /var/log/audit/audit.log 同样只算普通日志 → operator 可压审计日志

修法是新增 db_critical 层级：数据目录清单 + WAL/binlog/redo 命名模式
（后者不依赖父目录前缀，这是①的关键），命中即强制 approval_role=admin。

  D-1 三条工单点名的漏判路径均须 admin
  D-2 数据目录清单逐条命中（含国产库）
  D-3 命名模式不依赖父目录——同一文件名放在任意目录都须命中
  D-4 零误伤：普通业务日志仍按原档位，不被提权成 admin
"""

from __future__ import annotations

import pytest

from backend.app.contracts.intent import CandidateTool
from backend.app.security.guard import RuleBasedPolicyEngine
from mcp_servers.os_ops import all_specs


def _verdict(path: str):  # noqa: ANN202
    """按 log.compress_rotate 走真策略引擎——这是能触达这些路径的变更工具。"""
    from backend.app.mcp.registry import ToolRegistry

    engine = RuleBasedPolicyEngine(registry=ToolRegistry(list(all_specs())))
    return engine.evaluate(CandidateTool(name="log.compress_rotate", args={"path": path}))


#: 工单点名的三条漏判（回归锚点，不得再退化）
_REPORTED_GAPS = [
    "/var/log/mysql/mysql-bin.000001",
    "/var/log/audit/audit.log",
    "/var/lib/postgresql/13/main/base/1",
]


@pytest.mark.parametrize("path", _REPORTED_GAPS)
def test_d1_reported_gaps_require_admin(path: str) -> None:
    """D-1: 三条漏判路径必须升到 admin 审批，operator 不得独批。"""
    v = _verdict(path)
    assert v.approval_role == "admin", (
        f"D-1: {path} 的 approval_role={v.approval_role!r}——"
        f"operator 即可批准压掉关键数据/审计日志（decision={v.decision}）"
    )


#: 数据目录清单。国产库默认目录依据见 policy_loader 内注释（各产品官方部署文档）。
_DATA_DIRS = [
    "/var/lib/mysql/ibdata1",
    "/var/lib/pgsql/data/base/1",
    "/var/lib/postgresql/13/main/base/1",
    "/var/lib/mongodb/collection-0.wt",
    "/var/lib/redis/dump.rdb",
    "/opt/dmdbms/data/DAMENG/DAMENG01.log",
    "/opt/kingbase/data/base/1",
    "/var/lib/opengauss/data/base/1",
]


@pytest.mark.parametrize("path", _DATA_DIRS)
def test_d2_data_dirs_require_admin(path: str) -> None:
    """D-2: 主流库 + 国产库数据目录一律 admin。"""
    v = _verdict(path)
    assert v.approval_role == "admin", f"D-2: 数据目录 {path} 未升 admin（{v.approval_role!r}）"


#: WAL / binlog / redo / 数据文件的命名模式——放在任意目录都算关键。
_CRITICAL_NAMES = [
    "/srv/backup/mysql-bin.000042",
    "/data/custom/ib_logfile0",
    "/mnt/vol1/users.ibd",
    "/opt/pg/pg_wal/000000010000000000000001",
    "/tmp/anywhere/redo01.redo",
]


@pytest.mark.parametrize("path", _CRITICAL_NAMES)
def test_d3_name_patterns_independent_of_parent_dir(path: str) -> None:
    """D-3: 命名模式不依赖父目录前缀——这正是 ① 类漏判的成因。"""
    v = _verdict(path)
    assert v.approval_role == "admin", (
        f"D-3: {path} 未命中命名模式（{v.approval_role!r}）——"
        f"仍在按父目录前缀判定，换个目录即绕过"
    )


#: 普通业务日志：不得被新规则误伤提权。
_BENIGN = [
    "/var/log/nginx/access.log",
    "/var/log/myapp/app.log",
    "/var/log/syslog",
]


@pytest.mark.parametrize("path", _BENIGN)
def test_d4_benign_logs_not_escalated(path: str) -> None:
    """D-4: 零误伤——普通业务日志仍按原档位，不因新规则升成 admin。

    没有这条，把所有路径一律判 admin 也能让 D-1..D-3 全绿，
    那等于用"全都拦死"冒充"精确识别"。
    """
    v = _verdict(path)
    assert v.approval_role != "admin", (
        f"D-4: 普通日志 {path} 被误升到 admin——新规则过宽，" f"日常轮转都要惊动管理员"
    )
