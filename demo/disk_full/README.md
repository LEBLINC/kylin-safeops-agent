# 场景1：磁盘满

模拟日志分区使用率超过 95%，触发 RCA 诊断和 log.compress_rotate 审批。

## 文件

| 文件 | 用途 |
|------|------|
| `prepare.sh` | 在 /tmp/demo-disk 创建大数据文件模拟磁盘满 |
| `run.sh` | 提示用户在 ChatView 中输入故障查询 |
| `cleanup.sh` | 删除模拟数据文件 |
