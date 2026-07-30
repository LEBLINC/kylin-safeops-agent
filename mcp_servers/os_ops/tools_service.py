"""服务感知工具的 ToolSpec（D9）。

只读采集（systemctl show）；命令执行由特权执行器经命令模板白名单完成。
解析见 parsers.parse_systemctl_show。
"""

from __future__ import annotations

from backend.app.contracts.tool import ToolSpec

# service.status：systemctl show 只读 → R0。
# service_name 收紧字符集（字母数字 . _ @ -），拒注入字符。
SERVICE_STATUS = ToolSpec(
    name="service.status",
    description="查询某 systemd 服务的状态（load/active/sub/enabled、主 PID、描述）。",
    risk="R0",
    input_schema={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "pattern": r"^[A-Za-z0-9._@\-]+$",
            },
        },
        "required": ["service_name"],
        "additionalProperties": False,
    },
    requires_roles=["viewer", "operator", "admin"],
    reversible=True,
)

# ---- 变更工具（D10）：只声明契约，执行只经特权执行器 + 策略 + 审批 ----

# service.restart：重启 systemd 服务（变更类、造成中断）→ R3，需 admin。
# 可逆性：重启造成的服务中断不可撤销，标 reversible=False；R3 必经审批 + 特权代理。
SERVICE_RESTART = ToolSpec(
    name="service.restart",
    description="重启指定 systemd 服务（会造成短暂中断）。高危，需审批与最小权限执行。",
    risk="R3",
    input_schema={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "pattern": r"^[A-Za-z0-9._@\-]+$",
            },
        },
        "required": ["service_name"],
        "additionalProperties": False,
    },
    requires_roles=["admin"],
    reversible=False,
)

SPECS: list[ToolSpec] = [SERVICE_STATUS, SERVICE_RESTART]
