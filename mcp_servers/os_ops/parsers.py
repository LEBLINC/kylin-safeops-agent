# adapted from rhel-lightspeed/linux-mcp-server (Apache-2.0), modified by team
"""命令输出解析器（纯函数，无 IO、无命令执行）。

采集/解析逻辑改造自 linux-mcp-server 的 parsers.py（Apache-2.0）：
平移 parse_os_release / parse_system_info 思路；df、find 大文件解析为本项目自写
（原仓 disk 用 JSON df、大文件用 du/find 列目录，此处适配为经典 df -PB1 与 find -printf）。

安全：纯解析，不跑命令、不拼 shell；输入是 Executor 返回的原始 stdout（不可信），
解析结果回喂 LLM 前仍须经契约4 ToolResult 包裹。
"""

from __future__ import annotations

from mcp_servers.os_ops.models import (
    ConfigDiff,
    ConfigSnapshot,
    CpuLoad,
    DiskUsage,
    FileEntry,
    FilesystemUsage,
    LargeFiles,
    LargeLogs,
    ListeningPort,
    ListeningPorts,
    LogEntries,
    LogFile,
    LsofEntry,
    LsofResult,
    MemUsage,
    ProcessInfo,
    ProcessList,
    ServiceStatus,
    SystemInfo,
)


def parse_os_release(stdout: str) -> dict[str, str]:
    """解析 /etc/os-release 为键值对（adapted from linux-mcp-server）。"""
    result: dict[str, str] = {}
    for raw in stdout.strip().split("\n"):
        line = raw.strip()
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value.strip('"')
    return result


def parse_system_info(results: dict[str, str]) -> SystemInfo:
    """把多条命令输出聚合为 SystemInfo（adapted from linux-mcp-server）。

    results 键：hostname / os_release / kernel / arch / uptime / boot_time。
    """
    os_name, os_version = "", ""
    if "os_release" in results:
        os_data = parse_os_release(results["os_release"])
        os_name = os_data.get("PRETTY_NAME", "Unknown")
        os_version = os_data.get("VERSION_ID", "")
    return SystemInfo(
        hostname=results.get("hostname", "").strip(),
        os_name=os_name,
        os_version=os_version,
        kernel=results.get("kernel", "").strip(),
        arch=results.get("arch", "").strip(),
        uptime=results.get("uptime", "").strip(),
        boot_time=results.get("boot_time", "").strip(),
    )


def parse_df_output(stdout: str) -> DiskUsage:
    """解析 `df -PB1`（POSIX、字节单位）输出为 DiskUsage（本项目自写）。

    期望列：Filesystem 1B-blocks Used Available Capacity Mounted-on
    跳过表头；Capacity 形如 "23%"。无法解析的行静默跳过。
    """
    filesystems: list[FilesystemUsage] = []
    lines = stdout.strip().split("\n")
    for line in lines[1:]:  # 跳过表头
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            filesystems.append(
                FilesystemUsage(
                    filesystem=parts[0],
                    size_bytes=int(parts[1]),
                    used_bytes=int(parts[2]),
                    available_bytes=int(parts[3]),
                    use_percent=int(parts[4].rstrip("%")),
                    # 挂载点可能含空格：取第 6 列起全部
                    mount_point=" ".join(parts[5:]),
                )
            )
        except ValueError:
            continue
    return DiskUsage(filesystems=filesystems)


def parse_find_size_output(
    stdout: str, *, min_size_bytes: int = 0, top_n: int | None = None
) -> LargeFiles:
    """解析 `find <path> -type f -printf '%s\\t%p\\n'` 输出为 LargeFiles（本项目自写）。

    每行格式：SIZE\\tPATH。按 size 过滤 min_size_bytes、降序排序、截断 top_n。
    无法解析的行静默跳过（find 偶发权限错误行）。
    """
    entries: list[FileEntry] = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        if size < min_size_bytes:
            continue
        entries.append(FileEntry(path=parts[1], size_bytes=size))
    entries.sort(key=lambda e: e.size_bytes, reverse=True)
    if top_n is not None:
        entries = entries[:top_n]
    return LargeFiles(files=entries)


def parse_ps_output(stdout: str, *, sort_by: str = "cpu", top_n: int | None = None) -> ProcessList:
    """解析 `ps aux` 输出为 ProcessList（adapted from linux-mcp-server）。

    列：USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND。
    sort_by: "cpu" / "mem"（降序），其余按原顺序；可截断 top_n。
    无法解析的行静默跳过。
    """
    processes: list[ProcessInfo] = []
    lines = stdout.strip().split("\n")
    for line in lines[1:]:  # 跳过表头
        parts = line.split(None, 10)  # 最多切 11 段，command 保留空格
        if len(parts) < 11:
            continue
        try:
            processes.append(
                ProcessInfo(
                    user=parts[0],
                    pid=int(parts[1]),
                    cpu_percent=float(parts[2]),
                    mem_percent=float(parts[3]),
                    rss_kb=int(parts[5]),
                    stat=parts[7],
                    start=parts[8],
                    time=parts[9],
                    command=parts[10],
                )
            )
        except ValueError:
            continue
    if sort_by == "cpu":
        processes.sort(key=lambda p: p.cpu_percent, reverse=True)
    elif sort_by == "mem":
        processes.sort(key=lambda p: p.mem_percent, reverse=True)
    if top_n is not None:
        processes = processes[:top_n]
    return ProcessList(processes=processes)


def parse_ss_listening(stdout: str) -> ListeningPorts:
    """解析 `ss -tulnp` 输出为 ListeningPorts（adapted from linux-mcp-server）。

    跳过表头；本地地址形如 0.0.0.0:22 / [::]:80，从右侧分割端口。
    无法解析的行静默跳过。
    """
    ports: list[ListeningPort] = []
    lines = stdout.strip().split("\n")
    for line in lines[1:]:  # 跳过表头
        parts = line.split()
        if len(parts) < 5:
            continue
        protocol = parts[0].upper()
        local = parts[4]
        if ":" in local:
            local_addr, local_port = local.rsplit(":", 1)
        else:
            local_addr, local_port = local, ""
        process = " ".join(parts[6:]) if len(parts) > 6 else ""
        ports.append(
            ListeningPort(
                protocol=protocol,
                local_address=local_addr,
                local_port=local_port,
                process=process,
            )
        )
    return ListeningPorts(ports=ports)


def parse_journal_lines(stdout: str, *, unit: str = "", path: str = "") -> LogEntries:
    """把 journalctl/日志文件 stdout 拆成行（adapted from linux-mcp-server）。

    跳过空行；不解析时间戳/优先级（保留原始文本，下游可二次处理）。
    """
    entries = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    return LogEntries(entries=entries, unit=unit, path=path)


def parse_log_size_scan(
    stdout: str, *, min_size_bytes: int = 0, top_n: int | None = None
) -> LargeLogs:
    """解析 `find <path> -name '*.log' -type f -printf '%s\\t%p\\n'` 输出（自写）。

    与 parse_find_size_output 同格式但语义更窄（仅日志大文件场景）。
    """
    files: list[LogFile] = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        if size < min_size_bytes:
            continue
        files.append(LogFile(path=parts[1], size_bytes=size))
    files.sort(key=lambda f: f.size_bytes, reverse=True)
    if top_n is not None:
        files = files[:top_n]
    return LargeLogs(files=files)


def parse_lsof_output(stdout: str) -> LsofResult:
    """解析 `lsof` 默认输出为 LsofResult（自写）。

    列：COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
    取 COMMAND/PID/USER/FD/TYPE/NAME；NAME 可能含空格（取从 NODE 之后到行尾）。
    无法解析的行静默跳过。
    """
    entries: list[LsofEntry] = []
    lines = stdout.strip().split("\n")
    for line in lines[1:]:  # 跳过表头
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        try:
            entries.append(
                LsofEntry(
                    command=parts[0],
                    pid=int(parts[1]),
                    user=parts[2],
                    fd=parts[3],
                    type=parts[4],
                    name=parts[8],
                )
            )
        except ValueError:
            continue
    return LsofResult(entries=entries)


def parse_systemctl_show(stdout: str, *, name: str) -> ServiceStatus:
    """解析 `systemctl show <unit>` 的 key=value 输出为 ServiceStatus（自写）。

    取 LoadState/ActiveState/SubState/UnitFileState/MainPID/Description。
    比解析 `systemctl status` 的自由文本更稳健。无法解析的字段留默认。
    """
    kv: dict[str, str] = {}
    for line in stdout.strip().split("\n"):
        if "=" in line:
            key, value = line.split("=", 1)
            kv[key.strip()] = value.strip()
    try:
        main_pid = int(kv.get("MainPID", "0"))
    except ValueError:
        main_pid = 0
    return ServiceStatus(
        name=name,
        load_state=kv.get("LoadState", ""),
        active_state=kv.get("ActiveState", ""),
        sub_state=kv.get("SubState", ""),
        unit_file_state=kv.get("UnitFileState", ""),
        main_pid=main_pid,
        description=kv.get("Description", ""),
    )


def parse_sha256sum_output(stdout: str) -> ConfigSnapshot:
    """解析 `sha256sum <files...>` 输出为 ConfigSnapshot（自写）。

    每行格式：<64hex>  <path>（两空格）。无法解析的行静默跳过。
    """
    hashes: dict[str, str] = {}
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, path = parts[0], parts[1].strip()
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest.lower()):
            hashes[path] = digest.lower()
    return ConfigSnapshot(hashes=hashes)


def diff_config_snapshots(old: ConfigSnapshot, new: ConfigSnapshot) -> ConfigDiff:
    """对比两份配置快照，返回新增/删除/变更的路径（自写，纯函数）。

    added: 仅在 new；removed: 仅在 old；changed: 两者都有但 hash 不同。
    输出列表均按路径排序，结果稳定。
    """
    old_keys = set(old.hashes)
    new_keys = set(new.hashes)
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed = sorted(k for k in old_keys & new_keys if old.hashes[k] != new.hashes[k])
    return ConfigDiff(added=added, removed=removed, changed=changed)


def parse_netstat_listening(stdout: str) -> ListeningPorts:
    """解析 `netstat -tulnp` 输出为 ListeningPorts（自写，ss 缺失时的降级格式）。

    列：Proto Recv-Q Send-Q LocalAddress ForeignAddress [State] PID/Program。
    仅取以 tcp/udp 开头的数据行；本地地址从右侧分割端口；进程取含 '/' 的 PID/Program。
    非数据行（表头/标题）静默跳过；空输入返回空集（命令缺失/无输出优雅降级）。
    """
    ports: list[ListeningPort] = []
    for line in stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) < 4 or not (parts[0].startswith(("tcp", "udp"))):
            continue
        proto = "TCP" if parts[0].startswith("tcp") else "UDP"
        local = parts[3]
        if ":" in local:
            local_addr, local_port = local.rsplit(":", 1)
        else:
            local_addr, local_port = local, ""
        process = next((p for p in parts[4:] if "/" in p), "")
        ports.append(
            ListeningPort(
                protocol=proto,
                local_address=local_addr,
                local_port=local_port,
                process=process,
            )
        )
    return ListeningPorts(ports=ports)


def parse_listening_ports(stdout: str) -> ListeningPorts:
    """监听端口自动解析：检测 ss vs netstat 输出格式后分派（D14 降级兼容）。

    netstat 输出含 "Foreign Address" 表头或以 tcp/udp 行起；否则按 ss 解析。
    命令缺失/空输出 → 两解析器均返回空集，不崩。
    """
    if "Foreign Address" in stdout:
        return parse_netstat_listening(stdout)
    return parse_ss_listening(stdout)


def parse_free_output(stdout: str) -> MemUsage | None:
    """解析 `free -b` 输出为 MemUsage（本项目自写，按麒麟 VM 实测协议）。

    取以 ``Mem:`` 开头的行，split 后 col[1]=total、col[6]=available；
    **used_percent = (total-available)/total*100**（用 available 权威可用内存口径，
    非 used/total）。无 Mem 行 / 列缺失 / total<=0 → 返回 None（缺真，绝不填假值）。
    """
    for line in stdout.splitlines():
        parts = line.split()
        if not parts or parts[0] != "Mem:":
            continue
        try:
            total = int(parts[1])
            available = int(parts[6])
        except (IndexError, ValueError):
            return None
        if total <= 0:
            return None
        used_percent = round((total - available) / total * 100, 1)
        return MemUsage(total_bytes=total, available_bytes=available, used_percent=used_percent)
    return None


def parse_vmstat_output(stdout: str) -> CpuLoad | None:
    """解析 `vmstat 1 2` 输出为 CpuLoad（本项目自写，按麒麟 VM 实测协议）。

    **按 header 行定位 ``id`` 列索引**（不硬编码列号——id 列位置随内核/有无 gu 列变）；
    取**最后一个数据行**（第 2 行=1 秒采样；第 1 行是开机累计，丢弃）；
    **usage_percent = 100 - id**。无 id 列 / 无数据行 / 取值非法 → 返回 None（缺真）。
    """
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    id_idx: int | None = None
    header_idx: int | None = None
    for i, ln in enumerate(lines):
        cols = ln.split()
        if "id" in cols:
            id_idx = cols.index("id")
            header_idx = i
            break
    if id_idx is None or header_idx is None:
        return None
    data_lines = lines[header_idx + 1 :]
    if not data_lines:
        return None
    last = data_lines[-1].split()  # 最后一行 = 1 秒采样（丢弃首行开机累计）
    try:
        idle = float(last[id_idx])
    except (IndexError, ValueError):
        return None
    return CpuLoad(usage_percent=round(100.0 - idle, 1))
