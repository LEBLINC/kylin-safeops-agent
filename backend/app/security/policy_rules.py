"""策略规则数据结构（Pydantic 模型，纯数据）。

形态借鉴 shield 的 shieldset.yaml + neurond 的 policy.toml（只借结构、不引源码=Rust）；
三态与 contracts.policy.Decision 对齐：allow / deny / confirm（shield 的 warn 归 allow，
approval 归 confirm）。

本模块只定义"规则长什么样"，不实现裁决逻辑（裁决由后续 PolicyEngine 实现消费本模型）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.contracts.policy import Decision
from backend.app.contracts.tool import RiskLevel

#: 规则动作：直接复用契约三态语义。
Action = Decision

#: 严重度：仅供前端/审计展示，不影响裁决（裁决由 action 决定）。
Severity = Literal["low", "medium", "high", "critical"]


class RuleMatch(BaseModel):
    """规则匹配条件（多条件取 AND；同字段内的列表取 OR）。

    - tool_in:        命中工具名白名单（按 CandidateTool.name 精确匹配）
    - risk_in:        命中工具的 ToolSpec.risk（如 ["R3","R4"]）
    - any_arg_matches:任一参数值（递归）re.search 命中任一正则
    路径保护通过 ProtectedPaths（顶层）独立处理，本字段不重复表达。
    """

    model_config = ConfigDict(extra="forbid")

    tool_in: list[str] | None = Field(default=None, description="工具名白名单")
    risk_in: list[RiskLevel] | None = Field(default=None, description="风险等级白名单")
    any_arg_matches: list[str] | None = Field(
        default=None, description="任一参数值匹配任一正则即命中（大小写敏感）"
    )

    @field_validator("any_arg_matches")
    @classmethod
    def _patterns_compilable(cls, v: list[str] | None) -> list[str] | None:
        """加载期就把正则编译一遍，避免运行时炸 evaluate（确定性要求）。"""
        if v is None:
            return v
        import re

        for pat in v:
            try:
                re.compile(pat)
            except re.error as exc:
                raise ValueError(f"invalid regex {pat!r}: {exc}") from exc
        return v


class PolicyRule(BaseModel):
    """单条策略规则。

    确定性要求：本模型不持有任何状态；裁决器读规则做匹配，禁止在规则里塞回调/IO。
    deny 不可配置 approval_role；confirm 必须配 approval_role（前端/审批 UI 依赖）。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, description="规则唯一 ID，如 'CMD001'")
    name: str = Field(..., min_length=1, description="人类可读名")
    description: str = Field(default="", description="规则说明")
    match: RuleMatch = Field(..., description="匹配条件")
    action: Action = Field(..., description="命中后动作：allow/deny/confirm")
    severity: Severity = Field(default="medium", description="严重度（仅展示用）")
    reason: str = Field(default="", description="命中时给前端/审计的理由")
    safer_alternative: str | None = Field(default=None, description="更安全的替代建议")
    approval_role: str | None = Field(
        default=None, description="confirm 时谁能批，如 'admin'/'operator'"
    )

    @model_validator(mode="after")
    def _validate_action_consistency(self) -> PolicyRule:
        """裁决态一致性：deny 不能带 approval_role；confirm 必须有 approval_role。"""
        if self.action == "deny" and self.approval_role is not None:
            raise ValueError(f"rule {self.id}: deny rule must not set approval_role")
        if self.action == "confirm" and not self.approval_role:
            raise ValueError(f"rule {self.id}: confirm rule must set approval_role")
        return self


class ProtectedPaths(BaseModel):
    """路径保护清单（手册 §6.4 / Build-Guide §3.3）。

    路径参数经 normalize_path（posixpath.normpath，纯词法）+ 禁 .. 后大小写敏感比对；
    真实 realpath/symlink 兜底在 Executor（evaluate 无 IO，不调 realpath，确定性铁律）。
    按以下层级取最严：
    - forbid_modify:       禁修改（变更类工具命中即 deny）
    - forbid_delete:       禁删除（变更类工具命中即 deny）
    - db_critical_dirs:    关键库数据目录（变更类工具命中 → confirm + admin）
    - db_critical_names:   关键库文件名模式（WAL/binlog/redo/数据文件），
                           按 basename 匹配、**不依赖父目录前缀**——库日志常被
                           部署到 /var/log/mysql/ 等目录，只按目录前缀判会漏
    - confirm_required:    需要确认（命中即 confirm）
    - rotate_only:         可轮转/压缩，禁直接删（删除工具命中 → deny；轮转工具 → allow/confirm）
    """

    model_config = ConfigDict(extra="forbid")

    forbid_modify: list[str] = Field(default_factory=list)
    forbid_delete: list[str] = Field(default_factory=list)
    db_critical_dirs: list[str] = Field(default_factory=list)
    db_critical_names: list[str] = Field(default_factory=list)
    confirm_required: list[str] = Field(default_factory=list)
    rotate_only: list[str] = Field(default_factory=list)


class PolicySet(BaseModel):
    """完整策略集：版本 + 路径保护清单 + 规则列表。"""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(..., ge=1, description="规则集版本号")
    protected_paths: ProtectedPaths = Field(default_factory=ProtectedPaths)
    rules: list[PolicyRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> PolicySet:
        """规则 ID 必须全集唯一（matched_rules 回溯依赖此）。"""
        seen: set[str] = set()
        for r in self.rules:
            if r.id in seen:
                raise ValueError(f"duplicate rule id: {r.id}")
            seen.add(r.id)
        return self
