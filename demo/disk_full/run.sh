#!/usr/bin/env bash
# 场景1 运行提示
echo "=== 场景1 [磁盘满] 运行 ==="
echo "1. 打开 ChatView"
echo "2. 输入: 磁盘满了，帮我查原因"
echo "3. 观察 Agent 执行序列: disk.usage(R0) → log.compress_rotate(R2, 需审批)"
echo "4. 审批通过后观察压缩轮转工具执行"
echo ""
echo "Python 剧本可独立运行: python -m scripts.demo_disk_full_playbook"
