# 审计库部署与加固（Phase 3a / 3b）

审计库为 hash-chain 防篡改记录（`audit_records` 表），生产部署须保证**路径绝对**、
**权限受限**、**属主正确**。本目录说明 3a 落地的配置位与部署口径。

## 1. 路径配置：`KYLIN_AUDIT_DB`

| 模式 | `KYLIN_AUTH_MODE` | `require_absolute` | 行为 |
| --- | --- | --- | --- |
| 生产 | `proxy`（默认） | `True` | `KYLIN_AUDIT_DB` **必须为绝对路径**，否则启动期 `ValueError`（fail-closed，绝不静默落 cwd） |
| 开发 | 非 `proxy` | `False` | 允许相对路径；未设时回退默认 `./data/audit.db`（并 log WARN） |

- 路径解析由 `backend/app/db/session.py::resolve_audit_db_path(raw, *, require_absolute)` 纯函数完成。
- `require_absolute` 绑定 `KYLIN_AUTH_MODE=="proxy"`，由 `app.py` 计算后传入（D 侧函数不读环境变量）。
- `:memory:` 为测试夹具专用，经短路原样返回，不触发绝对路径校验，也不做权限加固。

生产建议把审计库放在归 agent 运行用户所有、且在 systemd `ReadWritePaths` 内的目录，例如：

```
KYLIN_AUDIT_DB=/var/lib/kylin-safeops/audit.db
# 或与现有 WorkingDirectory 一致：
KYLIN_AUDIT_DB=/opt/kylin-safeops/data/audit.db
```

## 2. 权限加固（0600 / 0700）

`connect()` 在建表后调用 `_secure_perms()`，对**文件路径库**（非 `:memory:`）施加：

- 审计库文件：`0600`（仅属主读写）
- 父目录：`0700`（仅属主进入）
- WAL 边车 `audit.db-wal`、`audit.db-shm`：`0600`

`chmod` 仅对**文件属主**有效。若 app 以非属主身份运行（如曾用 root 起过、目录属主漂移、多用户），
`chmod` 会失败——此时只 **log ERROR 不抛异常**（落库已成功，权限是加固层）。
属主问题的真正解法在**部署层**（见下）。

## 3. systemd 部署口径（属主 + UMask）

属主漂移是 VM 上 “readonly database / 属主不符” 部署阻塞的根因。务必：

1. **以专用用户运行**（已在 `deploy/kylin-safeops.service`）：`User=kylin-safeops`、`Group=kylin-safeops`。
2. **审计目录归该用户所有**，且首次创建前不要用 root 起 app：

   ```bash
   sudo install -d -o kylin-safeops -g kylin-safeops -m 0700 /var/lib/kylin-safeops
   ```

3. **设置 `UMask=0077`**，保证进程新建文件默认即受限（与 `_secure_perms` 双保险）。
   在 `deploy/kylin-safeops.service` 的 `[Service]` 段补：

   ```ini
   UMask=0077
   Environment=KYLIN_AUDIT_DB=/var/lib/kylin-safeops/audit.db
   ReadWritePaths=/var/lib/kylin-safeops
   ```

   （若审计库置于 `/opt/kylin-safeops/data` 则沿用现有 `ReadWritePaths=/opt/kylin-safeops`。）

4. 若曾用 root 起过导致属主漂移，部署时纠正：

   ```bash
   sudo chown -R kylin-safeops:kylin-safeops /var/lib/kylin-safeops
   sudo chmod 0700 /var/lib/kylin-safeops && sudo chmod 0600 /var/lib/kylin-safeops/audit.db*
   ```

## 4. retention / rotation（Phase 3b，决策⑪）

3b 给审计库加**保留与轮转**：按 trace 整批把已闭合（终态）的旧记录从主库搬到归档库，
回收主库体积。**带外 CLI**，不进 app lifespan、不做 app 内定时器（别拖启动、别和 `append`
抢并发），供 cron / systemd timer / 手动调用。

### 4.1 触发方式（带外 CLI）

```bash
# 主库路径必须经环境变量给定（拒 :memory: / 拒空）
KYLIN_AUDIT_DB=/var/lib/kylin-safeops/audit.db \
KYLIN_AUDIT_RETENTION_DAYS=90 \
KYLIN_AUDIT_MAX_BYTES=104857600 \
python -m backend.app.audit.maintenance
```

退出码：`0` 成功（打印归档报告）；`1` 失败（参数非法/异常，错误打到 stderr）。

systemd timer 示例（与主服务同用户、同 `ReadWritePaths`）：

```ini
# /etc/systemd/system/kylin-audit-retention.service
[Service]
Type=oneshot
User=kylin-safeops
Group=kylin-safeops
UMask=0077
Environment=KYLIN_AUDIT_DB=/var/lib/kylin-safeops/audit.db
Environment=KYLIN_AUDIT_RETENTION_DAYS=90
WorkingDirectory=/opt/kylin-safeops
ExecStart=/opt/kylin-safeops/.venv/bin/python -m backend.app.audit.maintenance
```

```ini
# /etc/systemd/system/kylin-audit-retention.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

### 4.2 配置位

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `KYLIN_AUDIT_DB` | 主库路径（**必须**；拒 `:memory:` / 空） | 无 |
| `KYLIN_AUDIT_RETENTION_DAYS` | 时间缓冲天数 | `90` |
| `KYLIN_AUDIT_MAX_BYTES` | 主库体积阈值（触发 rotation） | `104857600`（100MB） |
| `KYLIN_AUDIT_ARCHIVE_DIR` | 归档库目录 | 主库同目录（同 0700） |

### 4.3 归档口径（铁律）

- **终态闸（核心）**：只归档已达终态的 trace——其 `audit_records` 含 `phase ∈ {FINISHED, REJECTED}`。
  任何无终态记录的 trace（in-flight / WAIT_APPROVAL / 中途崩）一律不归档，无论多老，从根上杜绝误归 in-flight。
- **时间缓冲**：在终态闸之上叠加——trace 须**既达终态、且最新记录 `created_at` 早于 N 天前**才归档（两条件 AND）。
- **不破链**：按 trace **整批**搬迁，绝不按 record 删（删一条即破该 trace 哈希链）。
  **先验后删**：拷进归档库 → 归档库 `verify_chain` 通过 → 才从主库 `DELETE`；verify 失败保守不删并 log error。
- 归档库命名 `audit.archive.YYYYMM.db`（按执行月分桶），经 3a `connect()` 自动建表 + 0600 加固。
- 有归档后主库 `VACUUM` + `wal_checkpoint(TRUNCATE)` 回收空间。
- `append` 的 hash 语义（S7）与 `verify_chain` 复算逻辑、schema 均不变；归档原样复制 7 列，绝不重算 hash。

### 4.4 报告字段（stdout）

`archived_traces` / `archived_records`（搬迁 trace 与记录数）、`skipped_in_flight`（因未达终态而跳过的 trace 数）、
`freed_bytes` / `main_db_bytes_after`（回收前后主库在盘字节）、`archive_db_path`（归档库；无归档为空）。
