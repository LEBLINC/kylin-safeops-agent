# adapted from rhel-lightspeed/linux-mcp-server (Apache-2.0), modified by team
"""os_ops 采集结果的结构化模型（按需增长）。

字段结构借鉴 linux-mcp-server 的 models.py（Apache-2.0），裁剪为本项目所需子集。
这些是**解析输出**模型，非冻结契约（与 backend/app/contracts 分层）；
最终回喂 LLM 仍经契约4 ToolResult(is_untrusted=True) 包裹。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SystemInfo(BaseModel):
    """基本系统信息。"""

    model_config = ConfigDict(extra="forbid")

    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    kernel: str = ""
    arch: str = ""
    uptime: str = ""
    boot_time: str = ""


class FilesystemUsage(BaseModel):
    """单个文件系统挂载点的占用。"""

    model_config = ConfigDict(extra="forbid")

    filesystem: str
    size_bytes: int
    used_bytes: int
    available_bytes: int
    use_percent: int
    mount_point: str


class DiskUsage(BaseModel):
    """全部挂载点占用集合。"""

    model_config = ConfigDict(extra="forbid")

    filesystems: list[FilesystemUsage] = Field(default_factory=list)


class FileEntry(BaseModel):
    """大文件扫描的单条结果。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int


class LargeFiles(BaseModel):
    """大文件扫描结果（已按大小降序、可截断 top_n）。"""

    model_config = ConfigDict(extra="forbid")

    files: list[FileEntry] = Field(default_factory=list)


class ProcessInfo(BaseModel):
    """单个进程信息（ps aux 一行）。"""

    model_config = ConfigDict(extra="forbid")

    user: str
    pid: int
    cpu_percent: float
    mem_percent: float
    rss_kb: int
    stat: str
    start: str
    time: str
    command: str


class ProcessList(BaseModel):
    """进程列表（可按 cpu/mem 降序、截断 top_n）。"""

    model_config = ConfigDict(extra="forbid")

    processes: list[ProcessInfo] = Field(default_factory=list)


class ListeningPort(BaseModel):
    """单个监听端口（ss -tulnp 一行）。"""

    model_config = ConfigDict(extra="forbid")

    protocol: str
    local_address: str
    local_port: str
    process: str = ""


class ListeningPorts(BaseModel):
    """监听端口集合。"""

    model_config = ConfigDict(extra="forbid")

    ports: list[ListeningPort] = Field(default_factory=list)


class LogEntries(BaseModel):
    """journalctl / 日志文件 截取的若干行。"""

    model_config = ConfigDict(extra="forbid")

    entries: list[str] = Field(default_factory=list)
    unit: str = ""
    path: str = ""


class LogFile(BaseModel):
    """单个日志文件大小快照。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int


class LargeLogs(BaseModel):
    """日志大文件扫描结果。"""

    model_config = ConfigDict(extra="forbid")

    files: list[LogFile] = Field(default_factory=list)


class LsofEntry(BaseModel):
    """lsof 一行（已结构化）。"""

    model_config = ConfigDict(extra="forbid")

    command: str
    pid: int
    user: str
    fd: str
    type: str
    name: str


class LsofResult(BaseModel):
    """lsof 结构化结果集。"""

    model_config = ConfigDict(extra="forbid")

    entries: list[LsofEntry] = Field(default_factory=list)


class ServiceStatus(BaseModel):
    """systemd 服务状态（systemctl show 关键属性）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    load_state: str = ""
    active_state: str = ""
    sub_state: str = ""
    unit_file_state: str = ""
    main_pid: int = 0
    description: str = ""


class ConfigSnapshot(BaseModel):
    """配置文件哈希快照：path → sha256。"""

    model_config = ConfigDict(extra="forbid")

    hashes: dict[str, str] = Field(default_factory=dict)


class ConfigDiff(BaseModel):
    """两份快照的漂移结果。"""

    model_config = ConfigDict(extra="forbid")

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)


class CpuLoad(BaseModel):
    """CPU 使用率（vmstat 1 秒采样：usage = 100 - idle）。"""

    model_config = ConfigDict(extra="forbid")

    usage_percent: float


class MemUsage(BaseModel):
    """内存使用率（free -b：used_percent = (total-available)/total*100，available 权威口径）。"""

    model_config = ConfigDict(extra="forbid")

    total_bytes: int
    available_bytes: int
    used_percent: float
