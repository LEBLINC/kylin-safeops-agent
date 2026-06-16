# 审计库部署与加固（Phase 3a）

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

## 4. 3b 前向衔接：retention / rotation（本次未实现，预留配置位）

Phase 3b 将加审计库的保留与轮转，拆为后续 commit。**3a 不实现**，此处先占位约定环境变量名，
便于部署侧提前规划，避免后续改 key：

| 变量（3b 规划，暂未生效） | 含义 | 备注 |
| --- | --- | --- |
| `KYLIN_AUDIT_RETENTION_DAYS` | 审计记录保留天数（默认 90） | 额外叠加缓冲；归档以**终态闸**为准（仅归档含 FINISHED/REJECTED 终态记录的 trace），非纯时间窗 |
| `KYLIN_AUDIT_MAX_BYTES` | 单库体积上限（默认 100MB） | 触发 rotation 阈值 |
| `KYLIN_AUDIT_ARCHIVE_DIR` | 归档库目录 | 默认与主库同目录（同 0700）；可覆盖 |

> 注：以上 3b 变量目前**不被读取**；设置无副作用，仅作部署规划参考。3a 仅交付路径硬化 + 权限加固。
