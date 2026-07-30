# ADR-0001：审计库选用 SQLite，不引入 PostgreSQL

- 状态：**已接受（Accepted）** — L 拍板冻结，2026-06-16
- 决策者：L（集成/架构）、D（db/audit 负责人）
- 关联：决策⑪（审计库部署硬化）、`backend/app/db/session.py`、`backend/app/audit/audit_logger.py`、`deploy/audit/README.md`

## 背景（Context）

项目唯一的持久化是**哈希链审计库**（`audit_records` 单表）。会话状态是内存单例（SessionRegistry / lifespan），无 RAG / 向量 / 用户表（认证走反代签名头）。

评审中提出疑问：「Agent 一般用 PostgreSQL，为何此项目用 SQLite？」该疑问成立于**云端 SaaS / RAG Agent**（需多租户并发写、pgvector 检索、LangGraph checkpoint、分析查询）——但本项目这些需求**一个都没有**。需就此选型做正式决策并冻结。

## 决策（Decision）

**审计库采用 SQLite（CPython 内置 `sqlite3`，WAL 模式），不引入 PostgreSQL。**

四条硬约束全部成立：

1. **LoongArch / 麒麟靶机移植成本**：目标机为 LoongArch 架构麒麟 V11。`psycopg` 是 C 扩展，PG server 与驱动 wheel 均需在龙芯上移植。违背项目铁律「运行时唯一编译型依赖 = pydantic-core」。`sqlite3` 为 CPython 内置，零移植成本、零新依赖。
2. **单机 on-prem 部署形态**：本项目是装到客户麒麟服务器上的单节点运维 Agent，非云多租户 SaaS。单机应用不需独立 DB 守护进程；引入 PG 等于让客户多一个要安装 / 加固 / 备份 / 打补丁的服务，并新增监听端口的攻击面。
3. **完整性靠哈希链，不靠 DB 引擎**：审计防篡改由 prev_hash 链接 + `verify_chain` 复算保证，仅用到单行 INSERT。PG 的 MVCC / 复杂事务在此**非承重**，换 PG 不提升审计安全性。
4. **安全产品最小信任面**：核心叙事是「确定性兜底、最小信任面」。SQLite 文件零网络面，契合该叙事；DB server 进程与端口是反向的复杂度与攻击面。

**确认前提**：当前为**单节点 lifespan 单例**，无「多 Agent 实例共享同一审计库」的 HA 需求 ✅。这是唯一会推翻本决策的场景，当前不存在。

## 后果（Consequences）

- 正面：零外部 DB 依赖、零移植风险、零额外守护进程、零网络攻击面；部署即单文件。
- 代价：单机单写（lifespan 单例 + `threading.Lock` 串行，WAL 提供并发读）；不具备 PG 的水平扩展 / 多写并发 / SQL 分析能力——但当前 workload（低 QPS、追加为主的审计）不需要。
- 体积治理：单库文件增长由 **决策⑪ 3b（retention / rotation，按 trace 整迁归档至 `audit.archive.YYYYMM.db`）** 缓解，非靠 DB 引擎 TTL。

## 不锁死（迁移路径）

`SqliteAuditSink` 实现 `AuditSink` Protocol（`append` / `verify_chain` / `last_hash`）。若未来需 PG，只需新写 `PgAuditSink` 在 lifespan 接线点替换，**orchestrator 零改动**。本决策是「需求出现前不引入复杂度」，非技术锁定。

## Revisit 条件（何时重新评估）

满足任一即重启评估，**但默认不直接给单机塞 PG**：

1. **多节点 / HA**：多个 Agent 实例需共享同一审计库。
2. **集中审计聚合**：多台 Agent 审计需汇聚——正确做法是「Agent 推审计给中央收集器」，届时**单独立项**设计收集器，而非让每台单机依赖 PG。
3. **审计量爆炸**：持续每日百万级写入致 SQLite 单文件吃力（且 3b retention/rotation 已不足以缓解）。
4. 需要 SQL 分析 / pgvector RAG 等当前范围外能力。

## 备选方案（Alternatives considered）

- **PostgreSQL**：被否。理由见「决策」四约束；其优势（多写并发 / MVCC / pgvector / 分析）当前 workload 均不需要，而其代价（LoongArch 移植 / 守护进程 / 攻击面）在国产单机靶机上是实打实的负担。
- **中央审计收集器**：未来多节点场景的正确方向，非当前单机所需，列入 revisit 条件 #2。
