# Kylin SafeOps Agent — 演示场景

> 四个演示场景，与 `mcp_servers/rca/` 的 5 个 RCA 场景对齐（不含 service_failure）。
> 所有脚本支持 `--help` / `--dry-run`，不默认执行危险操作。

## 安全原则

1. **不执行危险操作** — 脚本仅做轻量准备（创建临时文件、启动睡眠进程等），不做 `rm -rf`、`fdisk`、`systemctl stop` 等
2. **dry-run 优先** — 每个脚本首次运行时建议加 `--dry-run` 预览操作
3. **cleanup 必执行** — 演示结束后运行 `cleanup.sh` 恢复环境
4. **隔离环境** — 建议在 VM 或容器中运行，不在生产主机

## 四个场景

| 场景 | 目录 | 对应 RCA Playbook | 说明 |
|------|------|------------------|------|
| 磁盘满 | `disk_full/` | `mcp_servers/rca/scenarios.py:disk_full` | 模拟日志分区占用率过高 |
| 僵尸进程 | `zombie_process/` | `mcp_servers/rca/scenarios.py:zombie_process` | 创建 defunct 进程 |
| I/O 异常 | `io_high/` | `mcp_servers/rca/scenarios.py:io_high` | 模拟高磁盘 I/O 负载 |
| 配置漂移 | `config_drift/` | `mcp_servers/rca/scenarios.py:config_drift` | 模拟配置文件意外变更 |

## 使用方式

```bash
# 单个场景
cd demo/disk_full
bash prepare.sh             # 准备
# ... 在 ChatView 中提问："磁盘满了，帮我查原因" ...
bash cleanup.sh             # 清理

# 或直接用 Python playbook
python -m scripts.demo_disk_full_playbook
```

## 与 Python Playbook 的关系

`demo/` 提供 **环境准备/清理** 脚本（创建故障数据），`scripts/` 提供 **Python 演示剧本**（驱动 Agent 链路）。二者配合使用：

1. `demo/disk_full/prepare.sh` 创建大数据文件模拟磁盘满
2. `python -m scripts.demo_disk_full_playbook` 驱动 Agent 执行 RCA+审批 全链路
3. `demo/disk_full/cleanup.sh` 恢复环境
