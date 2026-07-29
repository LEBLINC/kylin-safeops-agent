# Kylin SafeOps Agent — 部署指南

> 目标平台：麒麟 V11（Kylin Linux Advanced Server V11）+ LoongArch（龙芯）
> 部署范围：backend（Python + uvicorn）+ frontend（Vite 静态文件）+ systemd 守护

## 系统要求

- Python 3.11（对齐麒麟 V11 靶机实测版本）
- Node.js ≥20（前端构建用，运行时只需 Nginx 静态服务）
- systemd（进程守护）
- Nginx（前端静态文件 + 反向代理）

## 快速部署

```bash
# 1. 查看部署步骤（dry-run）
bash deploy/install.sh --dry-run

# 2. 执行安装（需 root）
sudo bash deploy/install.sh
```

## 文件说明

| 文件 | 用途 |
|------|------|
| `install.sh` | 一键部署脚本（支持 --dry-run / --help） |
| `app/kylin-safeops-agent.service` | app systemd unit（install.sh 安装此份） |
| `nginx.conf` | Nginx 反向代理配置示例 |
| `sudoers.example` | sudoers 配置示例（特权限定） |
| `verify.sh` | 部署后验证命令 |

## 安全红线

- `install.sh` 不执行 `rm -rf`、`chmod 777`、`curl | bash` 等危险操作
- 涉及 `sudo` / `root` 的步骤均标注 **[需人工复核]**
- Python 依赖仅从 `backend/requirements.txt` + `constraints.txt` 安装
- 前端构建产物不包含运行时可执行脚本
