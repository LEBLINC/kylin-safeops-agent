"""签名参考 CLI（供前端联调 / 运维测反代用）。

生成 4 个 proxy 签名头，以 auth.sign_identity 为权威 oracle。

用法：
    python -m backend.app.api.sign_cli --user alice --roles operator --secret mysecret
    python -m backend.app.api.sign_cli --user alice --roles "admin,operator" \\
        --secret "$(cat /etc/kylin-safeops/agent.env | grep SECRET | cut -d= -f2)"

注意事项：
- 密钥与 app 侧 KYLIN_PROXY_AUTH_SECRET **必须完全一致**（含大小写、无首尾空白）。
- X-Auth-Timestamp 已在本脚本自动取当前 Unix 秒；反代时须用相同时间戳（±300s 防重放）。
- X-Auth-Roles 格式：逗号分隔小写角色（如 "operator" 或 "operator,admin"）。
- **密钥勿出现在 shell history / 日志 / 前端 / 入库**；
  生产密钥仅存 /etc/kylin-safeops/agent.env（0600）。

输出格式（可直接粘贴到 curl -H 或 httpie）：
    X-Auth-User: <user>
    X-Auth-Roles: <roles>
    X-Auth-Timestamp: <ts>
    X-Auth-Signature: <hex>
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from backend.app.api.auth import sign_identity


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m backend.app.api.sign_cli",
        description="生成反代签名头（权威 oracle，与 auth.sign_identity 输出一致）",
    )
    p.add_argument("--user", required=True, help="用户名（X-Auth-User）")
    p.add_argument(
        "--roles",
        required=True,
        help='逗号分隔小写角色（X-Auth-Roles），如 "operator" 或 "operator,admin"',
    )
    p.add_argument(
        "--secret",
        default=None,
        help=(
            "共享密钥（KYLIN_PROXY_AUTH_SECRET）；"
            "不传则读 env KYLIN_PROXY_AUTH_SECRET（推荐，避免密钥进 shell history）"
        ),
    )
    p.add_argument(
        "--timestamp",
        type=int,
        default=None,
        help="Unix 秒时间戳（默认取当前时间）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    secret = args.secret or os.environ.get("KYLIN_PROXY_AUTH_SECRET", "")
    if not secret:
        print(
            "error: 密钥未指定 —— 请通过 --secret 或 env KYLIN_PROXY_AUTH_SECRET 提供",
            file=sys.stderr,
        )
        return 1

    user: str = args.user.strip()
    roles: str = args.roles.strip()
    ts: int = args.timestamp if args.timestamp is not None else int(time.time())

    sig = sign_identity(user, roles, str(ts), secret)

    print(f"X-Auth-User: {user}")
    print(f"X-Auth-Roles: {roles}")
    print(f"X-Auth-Timestamp: {ts}")
    print(f"X-Auth-Signature: {sig}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
