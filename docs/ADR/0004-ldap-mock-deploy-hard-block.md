# ADR-0004：KYLIN_LDAP_MOCK 默认 false，部署硬阻断 mock

- 状态：**已接受（Accepted）** — L 拍板，2026-06-19
- 决策者：L（集成/架构/审阅）
- 关联：决策⑨（RBAC 反代签名）、[ADR-0003](0003-real-llm-demo-only-scope.md)（真 LLM 接入 demo-only 范围）、P1 SSO/LDAP 工单（`feat/x-sso-ldap` 25c66bf）

## 背景（Context）

P1 SSO/LDAP 工单 `feat/x-sso-ldap`（commit 25c66bf）合入后，`deploy/sso/ldap_client.py` 接入反代。`LdapClient` 双模式：

- `KYLIN_LDAP_MOCK=true`（默认 **false**）：4 个硬编码 mock 用户（admin/operator/auditor/viewer，密码 `kylin123`），仅 demo / 单测
- `KYLIN_LDAP_MOCK=false` + 真 ldap3 server：当前 raise `NotImplementedError`（占位，等真 LDAP server 就位后实现）

**风险**：生产环境若误设 `KYLIN_LDAP_MOCK=true` + 实际接入外网，等于把生产当 demo 跑——任意人用 `admin/kylin123` 都能拿到 admin 角色 + 完整 HMAC 签名身份，反代签名认证形同虚设。

## 决策（Decision）

**`KYLIN_LDAP_MOCK` 默认值 = `false`，且生产部署必须 false**：

1. **代码层**：`LdapClient.__init__` 默认读 `os.environ.get("KYLIN_LDAP_MOCK", "false")`（已正确，默认 false）
2. **部署层**：`deploy/install.sh` 部署 systemd 单元时**显式 set** `Environment=KYLIN_LDAP_MOCK=false`（待补，install.sh 阶段6 backlog）
3. **Lifespan 启动检查**：`backend/app/api/app.py` lifespan 启动时，若 `KYLIN_AUTH_MODE=="proxy"` 但 `KYLIN_LDAP_MOCK=="true"`，**fail-fast 启动拒**（待 L 域加，1 commit 即可）
4. **对外口径**：交付材料、ADR、客户验收口径必须明确"生产 KYLIN_LDAP_MOCK=false，mock 仅 demo/单测"
5. **真 LDAP 模式实现**：占位（`raise NotImplementedError`），等真 ldap3 server 就位 + 阶段6.5 单独工单再实现

## 后果（Consequences）

- 正面：防止"生产误开 mock"导致的认证全空场景；与决策⑨ 反代签名认证全链路一致
- 代价：阶段6 启动前需要补 2 处改动（install.sh Environment 显式 false + lifespan fail-fast 启动检查）
- 真 LDAP 模式 `NotImplementedError` 是已知占位，不是 TODO——需等真 ldap3 server 就位

## 不锁死

- 真 LDAP 模式实现（`ldap3.Server + Connection + bind`）走阶段6.5 单独工单
- 部署层 fail-fast 检查可走 ADR 替代方案（如部署文档硬性要求"deployer 必须设 false"）

## Revisit

满足任一即重启评估：

1. **真 LDAP server 就位**（OpenLDAP/AD 测试环境可用）
2. **生产误开 mock 事件**（需要在 fail-fast 检查前补）
3. **多租户**（每租户独立 LDAP server）

## 备选方案

- **完全移除 mock 模式**：被否。mock 模式对单测 / dev 联调 / 客户 demo 不可缺。
- **mock 模式禁止生产启动**：被否（不如 fail-fast 优雅，且 deployer 可能误绕过 env 检查）。
- **生产必须用真 LDAP**：被否。当前真模式 `NotImplementedError`，强逼真模式 = 阶段6 阻塞。
