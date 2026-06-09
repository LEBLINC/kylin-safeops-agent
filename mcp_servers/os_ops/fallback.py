"""感知工具的命令 fallback 声明（D14：工具缺失有降级）。

声明每个工具依赖的外部命令**优先级顺序**：首选命令缺失时由执行器探测并回退到备选。

约定 / 占位：
- 本模块只做【声明】（哪个工具可用哪些命令、何顺序）+ 解析侧兼容（parsers 能解析
  各候选命令的输出，见 parse_listening_ports 自动检测 ss/netstat）。
- TODO(BLOCKED-ON-D): "探测命令是否存在并选择实际命令"属执行期行为，归 D 的 Executor
  （如 `command -v ss || command -v netstat`）。Executor 据本声明决定实际运行哪个命令。
- 解析器对各候选输出格式均兼容；命令全缺失/空输出时解析器返回空结构，不崩。
"""

from __future__ import annotations

#: 工具名 → 候选命令（按优先级降序）。执行器据此探测可用命令并回退。
FALLBACK_COMMANDS: dict[str, list[str]] = {
    "network.ports": ["ss", "netstat"],
    # 后续工具按需补充：如 process.list 可声明 ["ps"]，disk.usage ["df"] 等。
}


def candidate_commands(tool_name: str) -> list[str]:
    """返回某工具的候选命令优先级列表；未声明则空（执行器用其默认命令）。"""
    return list(FALLBACK_COMMANDS.get(tool_name, []))
