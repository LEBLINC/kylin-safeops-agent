# deploy/app — app 侧部署（L 域）

本目录为 Kylin SafeOps Agent **后端 app** 的部署产物（L 侧）。
反代配置（Nginx / Apache）在 `deploy/proxy/`（X 域）；沙箱配置在 `deploy/sandbox/`（D 域）。

---

## 快速上手（麒麟 V11）

### 1. 创建运行用户

```bash
useradd -r -s /sbin/nologin -d /opt/kylin-safeops kylin-safeops
```

### 2. 安装 app

```bash
install -d -m 0755 /opt/kylin-safeops
# 把仓库内容部署到 /opt/kylin-safeops（git clone / rsync）
cd /opt/kylin-safeops
python3 -m venv .venv
.venv/bin/pip install -c backend/constraints.txt -r backend/requirements.txt
```

### 3. 生成共享密钥（★与反代共享同一密钥）

```bash
# 生成强随机 64 位 hex（32 字节熵）
python3 -c "import secrets; print(secrets.token_hex(32))"
```

- **将密钥同时填入**：
  - `/etc/kylin-safeops/agent.env`（本文件，`KYLIN_PROXY_AUTH_SECRET=`）
  - 反代侧的 HMAC 签名配置（Nginx `set_hmac_sha256` 或等价实现）

### 4. 创建 env 配置文件

```bash
install -d -m 0755 /etc/kylin-safeops
cp deploy/app/agent.env.example /etc/kylin-safeops/agent.env
# 编辑：填入真实密钥、按需调整 KYLIN_AUDIT_DB
vi /etc/kylin-safeops/agent.env
chmod 0600 /etc/kylin-safeops/agent.env
chown root:kylin-safeops /etc/kylin-safeops/agent.env
```

### 5. 安装 systemd 单元

```bash
cp deploy/app/kylin-safeops-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable kylin-safeops-agent
systemctl start  kylin-safeops-agent
systemctl status kylin-safeops-agent
```

### 6. 验证 app 侧（无反代，模拟签名头）

```bash
# 无签名头 → 全 401（proxy 模式 fail-closed）
curl -s http://127.0.0.1:8000/api/auth/whoami
curl -s http://127.0.0.1:8000/api/system/overview

# 生成合法签名头（sign_cli oracle）
SECRET=$(grep KYLIN_PROXY_AUTH_SECRET /etc/kylin-safeops/agent.env | cut -d= -f2)
eval "$(KYLIN_PROXY_AUTH_SECRET="$SECRET" \
    python3 -m backend.app.api.sign_cli \
    --user testuser --roles operator | \
    sed 's/^/export H_/;s/: /=/')"
# 使用签名头访问
curl -s \
  -H "X-Auth-User: $H_X_Auth_User" \
  -H "X-Auth-Roles: $H_X_Auth_Roles" \
  -H "X-Auth-Timestamp: $H_X_Auth_Timestamp" \
  -H "X-Auth-Signature: $H_X_Auth_Signature" \
  http://127.0.0.1:8000/api/auth/whoami
# 期望：{"user":"testuser","roles":["operator"],"mode":"proxy"}
```

---

## 安全要点

| 要求 | 说明 |
|------|------|
| **app 绑 127.0.0.1** | uvicorn `--host 127.0.0.1`；app 不直接对外，反代是唯一入口 |
| **密钥强随机** | ≥32 字节熵；生产用 `secrets.token_hex(32)` |
| **密钥不进库/不进前端** | 仅存 `/etc/kylin-safeops/agent.env`（0600）和反代侧环境变量 |
| **NTP 时钟同步** | 防重放窗口 ±300s；app 与反代机器须 NTP 同步 |
| **反代剥离客户端 X-Auth-\*** | 反代须在注入签名头**之前**剥离任何客户端传入的 X-Auth-User/Roles/Timestamp/Signature，防客户端伪造 |
| **dev 模式严禁生产** | `KYLIN_AUTH_MODE=proxy` 硬写入 agent.env；dev 模式角色可伪造 |

---

## 签名 CLI（测试/联调 oracle）

```bash
# 打印 4 个签名头（以 auth.sign_identity 为权威 oracle）
KYLIN_PROXY_AUTH_SECRET=<secret> \
    python3 -m backend.app.api.sign_cli \
    --user alice --roles "operator,admin"

# 或显式传密钥（密钥会进 shell history，仅联调用）
python3 -m backend.app.api.sign_cli \
    --user alice --roles operator --secret <secret>
```

---

## 反代侧衔接要求（给 X）

1. 反代 HMAC 签名参数与 app 侧 `auth.sign_identity` 完全对齐：
   - `canonical = "{user}\n{roles}\n{timestamp}"`（`\n` 是 LF，不是字面 `\n`）
   - `signature = hex(HMAC-SHA256(secret, canonical.encode("utf-8")))`
   - timestamp = Unix 秒整数字符串
2. 反代须在向 app 转发**之前**剥离客户端传入的 `X-Auth-User/Roles/Timestamp/Signature` 4 头，再注入自己计算的签名头。
3. SSE 端点 `/api/chat/{trace_id}/events` 须经反代注入（浏览器 EventSource 不便自设头）。
4. 参考签名 oracle：`python3 -m backend.app.api.sign_cli`（输出即 app 期望收到的头值）。
