# SSO / LDAP 反代替换部署文档 (A1)

## 1. 反代签名密钥 (KYLIN_PROXY_AUTH_SECRET)

**生产必设**(未设即 fail-closed 拒启动):

```bash
# 32 字节 hex (256 位)
openssl rand -hex 32
```

写入 app 侧 `/etc/kylin-safeops/agent.env` 与反代侧 `/etc/kylin/proxy.env`
（**同一密钥，两侧必须字节级一致**，否则签名校验必失败）:

```
KYLIN_PROXY_AUTH_SECRET=<生成的 hex>
```

## 2. KYLIN_LDAP_* 6 env 全表

> 字段名与 `deploy/sso/ldap_client.py::_REQUIRED_REAL_ENV` 字节级一致（本次随 A2 start.bat
> 校对：原表 `KYLIN_LDAP_BIND_PW`/`KYLIN_LDAP_USER_BASE` 是代码不存在的字段名，已改正）。

| env | 说明 | 示例 |
|---|---|---|
| `KYLIN_LDAP_URL` | LDAP server URL | `ldap://ldap.kylin.local:389` |
| `KYLIN_LDAP_BIND_DN` | 绑定 DN | `cn=svc,ou=system,dc=kylin,dc=local` |
| `KYLIN_LDAP_BIND_PASSWORD` | 绑定密码 | `<secret>` |
| `KYLIN_LDAP_BASE_DN` | 用户搜索 base | `ou=users,dc=kylin,dc=local` |
| `KYLIN_LDAP_USER_FILTER` | 用户搜索 filter | `(uid={username})` |
| `KYLIN_LDAP_GROUP_ATTR` | 用户 entry 的群组属性名 | `memberOf` |
| `KYLIN_LDAP_GROUP_ROLE_MAP` | group→role 映射 JSON | `{"kylin-admins":"admin","kylin-ops":"operator"}` |

## 3. systemd Environment= 硬编码

app 单元 `/etc/systemd/system/kylin-safeops-agent.service`（源文件
`deploy/app/kylin-safeops-agent.service`）段:

```ini
[Service]
EnvironmentFile=/etc/kylin-safeops/agent.env
Environment=KYLIN_LDAP_MOCK=false
```

反代 sidecar 单元 `kylin-proxy.service` 用的是另一个文件
`EnvironmentFile=/etc/kylin/proxy.env`——两个单元各自的 env 文件，不是配置漂移。

`install.sh` 已 `chmod 0600 /etc/kylin-safeops/agent.env`（仅 root 读写，
组 kylin-safeops 可读）。

## 4. 反代 Basic Auth → 真 SSO/LDAP 链路 (决策⑨)

部署架构:

```
client → reverse_proxy (Basic Auth + LDAP bind) → app (HMAC signed identity)
```

- `deploy/proxy/proxy.py` 接收 Basic Auth → `LdapClient.authenticate()` 真接 LDAP bind
- 通过后注入 4 个 X-Auth-* 头 (含 v2 字段 method/path/body_sha/nonce 防重放)
- 反代不接收客户端 X-Auth-* (STRIP_HEADERS 自动剥除, 防伪造)
- 决策⑨: **反代 Basic Auth 禁用 fallback** — 必须 LDAP 真接, 不能 mock
- ADR-0004 硬阻断: `KYLIN_LDAP_MOCK=true` + `KYLIN_AUTH_MODE=proxy` 启动期 raise RuntimeError (lifespan fail-closed)

## 5. start.bat 使用指引 (Windows 部署, A2)

`deploy/proxy/start.bat` 是 Windows 平台的反代启动脚本 (对应 Linux `deploy/proxy/README.md`
的 `uvicorn proxy:app` 启动方式)。

用法:

```bat
:: 先编辑 start.bat 顶部的 6 个占位值 (KYLIN_PROXY_AUTH_SECRET + KYLIN_LDAP_* 5 项)
deploy\proxy\start.bat
```

脚本必设:
- `KYLIN_PROXY_AUTH_SECRET`（HMAC 共享密钥，与 app 侧一致）
- `KYLIN_LDAP_MOCK=false`（生产强制真接 LDAP，决策⑨ 硬阻断，见上）
- `KYLIN_LDAP_URL` / `KYLIN_LDAP_BIND_DN` / `KYLIN_LDAP_BIND_PASSWORD` / `KYLIN_LDAP_BASE_DN` /
  `KYLIN_LDAP_USER_FILTER` / `KYLIN_LDAP_GROUP_ATTR`（对齐 `deploy/sso/ldap_client.py::_REQUIRED_REAL_ENV`
  字节级字段名，与本文档 §2 表格一致）

## 6. wsproxy.py vs proxy.py 区分

| | `proxy.py` | `wsproxy.py` |
|---|---|---|
| 协议 | HTTP/SSE（含 `/api/chat/{trace_id}/events`） | WebSocket 透传 |
| 鉴权入口 | `proxy_route` 每请求 Basic Auth → LDAP bind | 握手阶段 Basic Auth → LDAP bind（一次性，非逐帧） |
| 公共签名 | `deploy/proxy/_sign.py::sign()` + `STRIP_HEADERS` | 同一 `_sign.py`（`authenticate_and_build_headers` 内部调用），**签名口径字节级一致** |
| 适用场景 | 常规 REST + SSE 长连接 | 前端如启用 WebSocket 通道时的反代对等路径（当前 chat 走 SSE，wsproxy 为预留/未来 WS 场景） |

反代 Basic Auth → 真 LDAP 流程图（两者共用同一鉴权模式，仅传输层不同）：

```
client --Basic Auth--> [proxy.py 或 wsproxy.py]
                              |
                              v
                     LdapClient.authenticate(user, pw)
                       (mock=false 时真 ldap3 bind)
                              |
                    +---------+---------+
                    | pass              | fail
                    v                   v
          LdapClient.get_user()    401/403（不区分用户不存在 vs 密码错，防枚举）
                    |
                    v
        注入 X-Auth-User/Roles/Timestamp/Signature
        + X-Auth-Method/Path/Body-Sha/Nonce (v2)
                    |
                    v
              转发到 app（127.0.0.1:8000）
```
