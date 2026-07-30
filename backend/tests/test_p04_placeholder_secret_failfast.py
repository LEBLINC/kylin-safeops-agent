"""P0-4: 占位密钥必须视同未配置（否则认证等于没有）。

install.sh 写 env 骨架时把 `KYLIN_PROXY_AUTH_SECRET=CHANGE_ME_32BYTE_HEX` 落到
两侧 env 文件，等运维填真值。但 `_get_secret()` 原实现只判 `secret or None`——
占位串非空即 truthy → HMAC 全链路拿这个**仓库内公开常量**验签，任何拿到本仓库
的人都能伪造出合法签名身份。全仓此前无任何 CHANGE_ME 检查。

  P04-1 占位值 → _get_secret() 返 None（与未配置同）
  P04-2 空值/未设 → None（既有行为不回归）
  P04-3 真值 → 原样返回（不误伤）
  P04-4 proxy 模式 + 占位值 → 请求被拒（fail-closed 端到端）
  P04-5 反代侧 get_secret() 占位值 → 抛错（宁可起不来，不可裸奔签名）
  P04-6 LDAP 侧占位值 → 判为未配置（走既有软降级，不带占位串去 bind）
"""

from __future__ import annotations

import pytest

_PLACEHOLDER = "CHANGE_ME_32BYTE_HEX"


def test_p04_1_placeholder_treated_as_unset(monkeypatch) -> None:
    """P04-1: 占位值视同未配置。"""
    from backend.app.api import auth

    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _PLACEHOLDER)
    assert auth._get_secret() is None, "P04-1: 占位值被当成真密钥——认证形同虚设"


def test_p04_2_empty_still_none(monkeypatch) -> None:
    """P04-2: 空值/未设仍返 None（既有行为不回归）。"""
    from backend.app.api import auth

    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "")
    assert auth._get_secret() is None
    monkeypatch.delenv("KYLIN_PROXY_AUTH_SECRET", raising=False)
    assert auth._get_secret() is None


def test_p04_3_real_secret_not_damaged(monkeypatch) -> None:
    """P04-3: 真密钥原样返回（不得误伤含 CHANGE 字样但非占位的值）。"""
    from backend.app.api import auth

    real = "a" * 64
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", real)
    assert auth._get_secret() == real

    # 前缀判定：只拒 CHANGE_ME 开头，不拒中间含该串的真随机值
    tricky = "deadbeefCHANGE_MEdeadbeef"
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", tricky)
    assert auth._get_secret() == tricky


def test_p04_4_forged_identity_rejected_end_to_end(monkeypatch) -> None:
    """P04-4: 攻击者用仓库内公开占位串签出的身份，必须验不过（fail-closed 端到端）。

    这是本项真正要防的攻击：占位串写在 install.sh 里、人人可见，若服务端认它，
    攻击者照 auth.sign_identity 的口径自签一个 admin 身份即可直接过认证。
    """
    import time

    from backend.app.api import auth

    ts = str(int(time.time()))
    # 攻击者用公开占位串签一份"完全合法"的 admin 身份
    forged_sig = auth.sign_identity(
        user="attacker", roles_csv="admin", timestamp=ts, secret=_PLACEHOLDER
    )

    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _PLACEHOLDER)
    principal = auth.verify_proxy_identity(
        user="attacker", roles="admin", timestamp=ts, signature=forged_sig
    )
    assert principal is None, "P04-4: 用仓库内公开占位串签的身份竟然验签通过——任何人都能伪造 admin"

    # 对照：换成真密钥时同一套流程应当验得过（证明上面的 None 来自占位判定，
    # 而不是签名逻辑本身坏了——否则这条断言会恒真、等于没测）
    real = "c" * 64
    good_sig = auth.sign_identity(user="alice", roles_csv="operator", timestamp=ts, secret=real)
    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", real)
    ok = auth.verify_proxy_identity(
        user="alice", roles="operator", timestamp=ts, signature=good_sig
    )
    assert ok is not None and ok.user == "alice", "P04-4 对照组：真密钥应验签通过"


def test_p04_5_proxy_side_raises_on_placeholder(monkeypatch) -> None:
    """P04-5: 反代侧拿占位值签名 → 抛错（起不来是可见故障，裸奔签名是静默失效）。"""
    from deploy.proxy import _sign

    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", _PLACEHOLDER)
    with pytest.raises(RuntimeError, match="CHANGE_ME"):
        _sign.get_secret()

    monkeypatch.setenv("KYLIN_PROXY_AUTH_SECRET", "b" * 64)
    assert _sign.get_secret() == "b" * 64


def test_p04_6_ldap_placeholder_is_unconfigured(monkeypatch) -> None:
    """P04-6: LDAP 侧占位值判为未配置——不带 CHANGE_ME 去连不存在的主机。"""
    from deploy.sso.ldap_client import LdapClient

    monkeypatch.setenv("KYLIN_LDAP_MOCK", "false")
    monkeypatch.setenv("KYLIN_LDAP_URL", "ldap://CHANGE_ME:389")
    monkeypatch.setenv("KYLIN_LDAP_BIND_DN", "CHANGE_ME")
    monkeypatch.setenv("KYLIN_LDAP_BIND_PASSWORD", "CHANGE_ME")
    monkeypatch.setenv("KYLIN_LDAP_BASE_DN", "CHANGE_ME")

    client = LdapClient()
    assert client._real_cfg == {}, "P04-6: 占位配置应判为未配置，走既有软降级"
