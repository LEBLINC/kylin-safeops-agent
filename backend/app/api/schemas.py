"""API 层请求/响应模型（pydantic v2）。

仅 DTO，无业务逻辑。请求体 extra="forbid" 防字段偷渡；
响应体字段对齐 X 前端 types（ChatSession / SendMessageResponse 等）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---- auth ----------------------------------------------------------------


class WhoamiResponse(BaseModel):
    """GET /api/auth/whoami 响应体（当前已验证身份）。"""

    user: str = Field(..., description="已验证用户名（proxy：来自反代签名头；dev：固定 'dev'）")
    roles: list[str] = Field(default_factory=list, description="已验证角色列表（排序后小写）")
    mode: str = Field(
        ..., description="认证模式：proxy=生产反代签名身份 / dev=联调放行（角色可伪造）"
    )


# ---- chat ----------------------------------------------------------------


class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, description="所属对话会话 id（可选）")
    message: str = Field(..., description="用户自然语言运维需求")


class ChatResponse(BaseModel):
    """POST /api/chat 响应体（对齐前端 SendMessageResponse）。"""

    session_id: str | None = Field(default=None, description="后端确认的会话 id")
    trace_id: str = Field(..., description="本次请求全链路追踪 id")
    stream_url: str = Field(..., description="SSE 事件流地址")


# ---- approvals -----------------------------------------------------------


class ResumeRequest(BaseModel):
    """POST /api/approvals/resume 请求体。"""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(..., description="待续跑的 trace_id")
    approved: bool = Field(..., description="是否批准执行")


class ResumeResponse(BaseModel):
    """POST /api/approvals/resume 响应体。"""

    trace_id: str = Field(..., description="续跑的 trace_id")
    accepted: bool = Field(..., description="续跑请求是否被受理（事件经同一 SSE 推送）")


class ApprovalItem(BaseModel):
    """GET /api/approvals + /api/approvals/{trace_id} 单条审批记录。"""

    trace_id: str
    user_intent: str
    risk_level: str
    approval_role: str | None
    state: str
    created_at: str


class ApprovalListResponse(BaseModel):
    """GET /api/approvals 响应体。"""

    items: list[ApprovalItem]
    total: int


class ApprovalResolveResponse(BaseModel):
    """POST /api/approvals/{trace_id}/{approve|reject|escalate} 响应体。"""

    trace_id: str
    decision: str = Field(..., description="approved | rejected | escalated")
    by: str = Field(..., description="actor principal.user")
    new_trace_id: str | None = Field(default=None, description="escalate 时生成的新 trace_id")
    accepted: bool


class EscalateRequest(BaseModel):
    """POST /api/approvals/{trace_id}/escalate 请求体。"""

    model_config = ConfigDict(extra="forbid")

    to_user: str | None = Field(default=None, description="转交给具体 user（admin-only）")
    to_role: str | None = Field(default=None, description="转交给指定 role（admin-only）")


# ---- audit ---------------------------------------------------------------


class AuditTraceSummary(BaseModel):
    """GET /api/audit/traces 列表项。"""

    trace_id: str
    first_user_intent: str
    record_count: int
    state: str
    first_seen: str
    last_seen: str


class AuditTraceListResponse(BaseModel):
    """GET /api/audit/traces 响应体。"""

    items: list[AuditTraceSummary]
    total: int
    limit: int
    offset: int


class AuditRecord(BaseModel):
    """GET /api/audit/traces/{trace_id} 单条 record（S9 敏感字段已过滤）。"""

    seq: int
    phase: str
    payload: dict[str, object]
    prev_hash: str
    curr_hash: str
    created_at: str


class AuditTraceDetail(BaseModel):
    """GET /api/audit/traces/{trace_id} 响应体（含 verify_chain 状态）。"""

    trace_id: str
    records: list[AuditRecord]
    verify_chain_valid: bool
    record_count: int
    broken_seq: int | None
    reason: str


class AuditVerifyResponse(BaseModel):
    """POST /api/audit/verify 响应体（服务端 recompute，不暴露 hash 算法）。"""

    trace_id: str
    valid: bool
    record_count: int
    broken_seq: int | None
    reason: str


# ---- policy --------------------------------------------------------------


class PolicyRuleOut(BaseModel):
    """GET /api/policy/rules 单条规则（从 PolicyRule 序列化，Decision⑭ 端到端保契约原名）。"""

    id: str
    name: str
    description: str
    action: str
    severity: str
    reason: str
    approval_role: str | None
    safer_alternative: str | None = Field(
        default=None,
        description=(
            "更安全的替代建议（X 联调新增；规则未配置时为 None，与 PolicyVerdict 同口径）"
        ),
    )


class PolicyRulesResponse(BaseModel):
    """GET /api/policy/rules 响应体。"""

    rules: list[PolicyRuleOut]
    version: int


class PolicyEventOut(BaseModel):
    """GET /api/policy/events 单条策略事件（从 audit policy_verdict 派生）。"""

    trace_id: str
    rule_id: str
    decision: str
    risk_level: str
    user_intent: str
    created_at: str


class PolicyEventsResponse(BaseModel):
    """GET /api/policy/events 响应体。"""

    items: list[PolicyEventOut]
    total: int


class PolicyRiskLevel(BaseModel):
    """GET /api/policy/risk-levels 单条风险等级定义（决策⑬ RBAC fail-closed 同款口径）。"""

    level: str
    name: str
    description: str
    auto_approve: bool
    approval_role_required: str | None
    examples: list[str]


class PolicyRiskLevelsResponse(BaseModel):
    """GET /api/policy/risk-levels 响应体。"""

    items: list[PolicyRiskLevel]


# ---- demo ---------------------------------------------------------------


class DemoPrepareResponse(BaseModel):
    """POST /api/demo/{scenario}/prepare 响应体。"""

    scenario: str
    audit_db_path: str = Field(..., description="临时审计库路径（前端拿到可传给 run）")
    tmp_dir: str
    ready: bool
    by: str


class DemoRunResponse(BaseModel):
    """POST /api/demo/{scenario}/run 响应体。"""

    scenario: str
    label: str
    by: str
    state: str
    verified_summary: str
    record_count: int
    rejected_cause: str
    raw: dict[str, object] = Field(default_factory=dict, description="scenario 完整返回")


class DemoCleanupResponse(BaseModel):
    """POST /api/demo/{scenario}/cleanup 响应体。"""

    scenario: str
    by: str
    removed_dirs: list[str]


# ---- tools ---------------------------------------------------------------


class ToolRegistryItem(BaseModel):
    """GET /api/tools/registry 单项（字段适配：name → tool）。"""

    tool: str = Field(..., description="工具名（前端用 tool 而非 name）")
    description: str = Field(..., description="人类可读用途说明")
    risk: str = Field(..., description="静态风险等级 R0–R4")
    input_schema: dict = Field(..., description="JSON Schema")


class ToolCallRequest(BaseModel):
    """POST /api/tools/call 请求体（手动单工具调用，仍经三道闸）。"""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(..., description="工具名")
    args: dict = Field(default_factory=dict, description="结构化参数")


class ToolCallResponse(BaseModel):
    """POST /api/tools/call 响应体（映射 gateway CallOutcome）。"""

    executed: bool = Field(..., description="是否实际执行（被闸拦下则 False）")
    result: dict | None = Field(default=None, description="ToolResult（已密封不可信）")
    verdict: dict | None = Field(default=None, description="PolicyVerdict（拦下时携带）")
    reason: str = Field(default="", description="未执行原因")


class ToolCallDetail(BaseModel):
    """GET /api/tools/calls/{call_id} 响应体（X D6 新增）。

    call_id 在 MVP 阶段视为 trace_id：返回该 trace 最后一条 EXECUTING/EXECUTED
    记录的派生物（tool 名 + args + exit_code + timestamp）。
    返回 None 字段表示该 trace 没找到对应阶段记录。
    """

    call_id: str = Field(..., description="call_id（MVP=trace_id；后续可扩展 seq 定位）")
    trace_id: str = Field(..., description="所属 trace_id")
    seq: int = Field(..., description="该 call 在 trace 中的 seq")
    tool_name: str = Field(..., description="工具名（payload.tool）")
    args: dict = Field(default_factory=dict, description="工具参数（payload.args）")
    exit_code: int = Field(..., description="工具退出码（payload.exit_code）")
    timestamp: float = Field(..., description="epoch 秒（从 created_at 解析）")


class ToolCallSummary(BaseModel):
    """GET /api/tools/calls 单条工具调用摘要（X D7 新增）。

    派生自审计库 phase IN ('EXECUTING','EXECUTED') + payload.tool 精确匹配；
    按 trace_id 聚合：该 trace 全部 EXECUTING/EXECUTED 记录里取首条（最早）作为
    摘要——既体现"该工具首次被调用的那一条"，又便于前端按时间倒序展示历史调用。
    S9：duration_ms / risk_level / args 不在此 schema 暴露（避免泄密/扩张字段）；
    后续若需要可单独加 /api/tools/calls/{call_id} 详情（已存在 D6）。
    """

    call_id: str = Field(..., description="call_id（MVP=trace_id；与 ToolCallDetail 同口径）")
    trace_id: str = Field(..., description="所属 trace_id")
    tool: str = Field(..., description="工具名（payload.tool）")
    status: str = Field(
        ...,
        description="记录相位：EXECUTING（执行中）或 EXECUTED（已执行）",
    )
    duration_ms: int = Field(
        default=0,
        description="占位：MVP 不解析耗时（审计库无 duration 字段）；前端按 0 显示",
    )
    risk_level: str = Field(
        default="",
        description="占位：MVP 不从该 phase 派生（risk_level 在 INTENT_PARSED）；保留给后续增量",
    )
    created_at: str = Field(..., description="记录 created_at（ISO 字符串）")


class ToolCallListResponse(BaseModel):
    """GET /api/tools/calls 响应体（X D7 新增）。

    按工具名（query param tool）查询历史调用列表；limit 上限 100。
    total 与 items 数量一致（MVP 无分页）。
    """

    items: list[ToolCallSummary]
    total: int


# ---- sessions ------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    """POST /api/chat/sessions 请求体。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, description="会话标题（缺省自动命名）")


class SessionUpdateRequest(BaseModel):
    """PATCH /api/chat/sessions/{session_id} 请求体。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, description="新会话标题")


class SessionDeleteResponse(BaseModel):
    """DELETE /api/chat/sessions/{session_id} 响应体。"""

    session_id: str = Field(..., description="被删除的会话 id")
    deleted: bool = Field(..., description="是否删除成功")


class ChatSessionDTO(BaseModel):
    """对话会话（对齐前端 ChatSession，session_id 主键）。"""

    session_id: str = Field(..., description="会话 id（主键）")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(..., description="创建时间 ISO 字符串")
    updated_at: str = Field(..., description="最近更新时间 ISO 字符串")
    owner: str = Field(default="", description="会话所有者 user（L-H1 IDOR 修复）")


# ---- system --------------------------------------------------------------


class ServiceStatus(BaseModel):
    """系统概览中的单个服务状态。"""

    name: str = Field(..., description="服务名")
    status: str = Field(..., description="运行状态，如 running/stopped")


class SystemOverview(BaseModel):
    """GET /api/system/overview 响应体（扁平指标，Dashboard 渲染）。"""

    cpu_usage: float = Field(
        ..., description="CPU 使用率（百分比）；暂无只读源，未采集时为 0.0（见 data_source）"
    )
    memory_usage: float = Field(
        ..., description="内存使用率（百分比）；暂无只读源，未采集时为 0.0（见 data_source）"
    )
    root_disk_usage: float = Field(
        ..., description="根分区使用率（百分比）；任务戊由 df 真实解析（未采集时 0.0）"
    )
    zombie_processes: int = Field(..., description="僵尸进程数；任务戊由 ps 真实统计（未采集时 0）")
    tool_calls_today: int = Field(
        default=0,
        description="今日工具调用次数（X D3 真填）：审计 EXECUTING/EXECUTED + 今天 00:00 起 COUNT",
    )
    denied_today: int = Field(
        default=0,
        description="今日被拒绝次数（X D3 真填）：审计 phase=REJECTED + 今天 00:00 起 COUNT",
    )
    services: list[ServiceStatus] = Field(
        default_factory=list,
        description="关键服务状态列表（X D3 真填）：从审计 phase=EXECUTED 派生，"
        "按 tool_name LIKE 'service.%' 前缀过滤 + 去重",
    )
    # 任务D/戊：数据来源态显式标注（防桩数据冒充真数据，审计/诚实红线）。
    # "stub_executor"=无任何字段从真实 stdout 还原；"partial"=部分字段（disk/zombie）已真、
    # 其余仍缺真实源；"real"=全部上报数值均从真实 stdout 还原（cpu/memory 缺源前不可达）。
    data_source: str = Field(
        default="stub_executor",
        description=(
            "数据来源态：stub_executor=无真实采集；partial=部分字段真实采集（disk/zombie）、"
            "其余缺源；real=全部数值真实采集"
        ),
    )
    probed_tools: list[str] = Field(
        default_factory=list,
        description="本次经 MCPGateway 真实 dispatch 的只读工具名，证明采集管道连通",
    )


# ---- /api/system/overview/history -------------------------------------------


class OverviewHistoryPoint(BaseModel):
    """/api/system/overview/history 单个时间点。"""

    ts: float = Field(..., description="epoch 秒（小时桶起点）")
    cpu: float = Field(..., description="CPU 使用率（百分比）；缺源时 0.0")
    mem: float = Field(..., description="内存使用率（百分比）；缺源时 0.0")
    disk: float = Field(..., description="根分区使用率（百分比）；缺源时 0.0")


class OverviewHistoryResponse(BaseModel):
    """GET /api/system/overview/history 响应体（X D1 新增）。

    按小时聚合最近 N 小时（默认 24 / max 168）的 cpu/mem/disk 指标；
    当前审计库未落 overview 探针 → series 通常为空（前端 sparkline 显示"暂无数据"）。
    """

    hours: int = Field(..., description="回看窗口小时数（已 clamp 到 1..168）")
    series: list[OverviewHistoryPoint] = Field(
        default_factory=list, description="按时间升序的指标序列；缺数据时为 []"
    )


# ---- /api/system/stats -----------------------------------------------------


class SystemStats(BaseModel):
    """GET /api/system/stats 响应体（X D5 新增）。

    来自审计库聚合：by_tool / by_risk / by_status 三个维度。
    """

    hours: int = Field(..., description="回看窗口小时数（已 clamp 到 1..168）")
    by_tool: dict[str, int] = Field(
        default_factory=dict,
        description="工具调用次数按 tool_name 聚合（来自 EXECUTING/EXECUTED records）",
    )
    by_risk: dict[str, int] = Field(
        default_factory=dict,
        description="按 risk_level（R0/R1/R2/R3）分布（来自 INTENT_PARSED records）",
    )
    by_status: dict[str, int] = Field(
        default_factory=dict,
        description="按终态 status（FINISHED/REJECTED/WAIT_APPROVAL）分布",
    )


# ---- rca -----------------------------------------------------------------


class RCAAnalyzeRequest(BaseModel):
    """POST /api/rca/analyze 请求体。"""

    model_config = ConfigDict(extra="forbid")

    problem_type: str = Field(..., description="问题类型，如 disk_full")
    description: str = Field(..., description="问题描述")
    evidence: list[dict[str, object]] = Field(
        default_factory=list,
        description=(
            "可选证据列表（X 联调新增）。每条 dict 含 tool_name / stdout / exit_code / "
            "tool_result 键；传非空 → 真接 DefaultRCAEngine.analyze 走完整 playbook；"
            "空/不传 → 兜底只按 problem_type/description 产 '采集建议' 模板壳子"
            "（evidence_count=0）。防御纵深：evidence 仅供 RCA 分析，不触发执行。"
        ),
    )


class RCAAnalyzeResponse(BaseModel):
    """POST /api/rca/analyze 响应体。"""

    trace_id: str = Field(..., description="本次 RCA 分析的 trace_id")
    evidence_count: int = Field(
        default=0,
        description=(
            "本次喂给 RCA 引擎的证据条数（X 联调新增）。>0 表示真接 LLM/真分析；"
            "=0 表示走 problem_type/description 模板壳子（前端可在不传 evidence 时拿空模板）"
        ),
    )


class RCAReportResponse(BaseModel):
    """GET /api/rca/{trace_id} 响应体。"""

    trace_id: str = Field(..., description="RCA 分析 trace_id")
    report: dict = Field(default_factory=dict, description="RCA 报告（结构待 X 定）")
    # 之六十八 Task 3: LLM 化自然语言摘要（独立 RCA 端点）。LLM 不可用/失败 → None,
    # 前端零感知兼容（旧 client 不读此字段；新 client 可选订阅）
    llm_summary: str | None = Field(
        default=None,
        description="LLM 化的自然语言根因摘要（≤200 字）；None 表示 LLM 不可用/超时/拒答",
    )


class LLMHealth(BaseModel):
    """GET /api/llm/health 响应体。

    字段口径：
    - provider / model / base_url / rate_limit_per_minute / token_cap：来自
      `RealLLMConfig`（`backend.app.llm.real_client.load_real_llm_config_from_env`），
      便于运维一眼看到当前进程实际用的 LLM 配置。
    - api_key_configured：bool（`bool(cfg.api_key)`），**绝不回显 key 本身 / 前缀 / 后缀**
      ——S9 铁律。客户端若需轮换密钥，走环境变量替换。
    - status：恒为 `"ok"`，表示"配置可读"，**不**表示真端点可达——真连通性探测
      需额外 `?probe=true` 开关（不发请求实现；本端点守住"配置态健康"边界）。
    """

    provider: str = Field(..., description='LLM provider："fixture" / "real"')
    model: str = Field(..., description="模型名（来自 RealLLMConfig.model）")
    base_url: str = Field(..., description="OpenAI 兼容端点 base_url（非密钥，可回显）")
    api_key_configured: bool = Field(
        ..., description="是否已通过 KYLIN_LLM_API_KEY env 注入；**绝不**回显 key 明文"
    )
    rate_limit_per_minute: int = Field(..., description="每分钟最大 LLM 调用次数")
    token_cap: int = Field(..., description="单会话累计 token 上限")
    status: str = Field(default="ok", description='恒 "ok"——本端点不证明端点可达')


class LLMHealthProbe(LLMHealth):
    """GET /api/llm/health?probe=true 响应体（LLMHealth 扩展）。

    probe_status 语义：
    - "skipped"  fixture 模式，无真端点，跳过探测
    - "ok"       真探成功（HTTP 2xx）
    - "failed"   真探失败（非 2xx 状态码）
    - "timeout"  连接或读取超时
    S9：probe_error 只报 status_code / error class，**不**暴露 httpx 异常原文。
    """

    probe_enabled: bool = Field(..., description="本次是否真探（?probe=true 且 real 模式）")
    probe_status: str = Field(..., description='"ok"/"skipped"/"failed"/"timeout"')
    probe_latency_ms: int | None = Field(default=None, description="探测延迟（毫秒）")
    probe_error: str | None = Field(default=None, description="失败原因（仅状态码/错误类型）")


class ReadinessResponse(BaseModel):
    """K8s readiness 探针响应。"""

    ready: bool = Field(..., description="整体 readiness（db AND bus AND registry）")
    db: bool = Field(..., description="AuditSink.ping() 是否成功")
    bus: bool = Field(..., description="EventBus 是否存活")
    registry: bool = Field(..., description="SessionRegistry.active_count 是否在阈值内")
    active_sessions: int = Field(default=0, description="当前活跃会话数")


class MetricsResponse(BaseModel):
    """GET /api/system/metrics 响应体（C1 自研轻量指标系统）。

    counters：只增计数（如 orchestrator.state.* / llm.calls / llm.failures）。
    gauges：瞬时值（如 audit.append_latency_ms / sse.active_count）。
    """

    counters: dict[str, int] = Field(default_factory=dict, description="累加计数器快照")
    gauges: dict[str, float] = Field(default_factory=dict, description="瞬时值快照")
