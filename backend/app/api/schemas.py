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
    tool_calls_today: int = Field(..., description="今日工具调用次数")
    denied_today: int = Field(..., description="今日被策略拒绝次数")
    services: list[ServiceStatus] = Field(default_factory=list, description="关键服务状态列表")
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


# ---- rca -----------------------------------------------------------------


class RCAAnalyzeRequest(BaseModel):
    """POST /api/rca/analyze 请求体。"""

    model_config = ConfigDict(extra="forbid")

    problem_type: str = Field(..., description="问题类型，如 disk_full")
    description: str = Field(..., description="问题描述")


class RCAAnalyzeResponse(BaseModel):
    """POST /api/rca/analyze 响应体。"""

    trace_id: str = Field(..., description="本次 RCA 分析的 trace_id")


class RCAReportResponse(BaseModel):
    """GET /api/rca/{trace_id} 响应体。"""

    trace_id: str = Field(..., description="RCA 分析 trace_id")
    report: dict = Field(default_factory=dict, description="RCA 报告（结构待 X 定）")


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
