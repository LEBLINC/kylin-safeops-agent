"""API 层请求/响应模型（pydantic v2）。

仅 DTO，无业务逻辑。请求体 extra="forbid" 防字段偷渡；
响应体字段对齐 X 前端 types（ChatSession / SendMessageResponse 等）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

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

    cpu_usage: float = Field(..., description="CPU 使用率（百分比）")
    memory_usage: float = Field(..., description="内存使用率（百分比）")
    root_disk_usage: float = Field(..., description="根分区使用率（百分比）")
    zombie_processes: int = Field(..., description="僵尸进程数")
    tool_calls_today: int = Field(..., description="今日工具调用次数")
    denied_today: int = Field(..., description="今日被策略拒绝次数")
    services: list[ServiceStatus] = Field(default_factory=list, description="关键服务状态列表")


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
