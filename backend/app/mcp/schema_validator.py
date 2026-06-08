"""MCP 工具参数结构校验（手册 §3.3）。

这是**策略引擎之前的第一道结构校验**：对 LLM 提出的 candidate_tool.args
按工具 ToolSpec.input_schema 校验，不通过直接判定无效（gateway 据此 deny）。

实现：自写最小纯 Python JSON Schema 子集校验器。
理由（LoongArch 铁律6）：不引入 jsonschema —— 其 4.x 依赖 referencing→rpds-py(Rust)，
无 loongarch64 wheel 风险。我们的 input_schema 由本团队自定义，子集可控。

支持子集：
- type: object/string/integer/number/boolean/array/null（含类型数组）
- object: properties / required / additionalProperties(bool)
- string: enum / minLength / maxLength / pattern
- number/integer: enum / minimum / maximum
- array: items / minItems / maxItems
安全约束：字符串参数默认禁止包含 ".." 路径逃逸片段（除非 schema 显式 allow_dotdot=True）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# JSON 基本类型名 → Python 类型（isinstance 用）。
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


@dataclass
class ValidationResult:
    """校验结果：ok=False 时 errors 非空，供 gateway 组装 deny 理由。"""

    ok: bool
    errors: list[str] = field(default_factory=list)


def _check_type(value: object, type_spec: object, path: str, errors: list[str]) -> bool:
    """校验 value 的类型符合 type_spec（字符串或字符串数组）。"""
    types = type_spec if isinstance(type_spec, list) else [type_spec]
    py_types: list[type | tuple[type, ...]] = []
    for t in types:
        if t not in _TYPE_MAP:
            errors.append(f"{path}: unknown type '{t}' in schema")
            return False
        py_types.append(_TYPE_MAP[t])
    # bool 是 int 的子类：integer/number 不应接受 bool
    if "boolean" not in types and isinstance(value, bool):
        errors.append(f"{path}: expected {types}, got boolean")
        return False
    if not any(isinstance(value, pt) for pt in py_types):
        errors.append(f"{path}: expected {types}, got {type(value).__name__}")
        return False
    return True


def _validate(value: object, schema: dict, path: str, errors: list[str]) -> None:
    """按 schema 递归校验 value，错误累加进 errors。"""
    type_spec = schema.get("type")
    if type_spec is not None and not _check_type(value, type_spec, path, errors):
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value not in enum {schema['enum']}")

    if isinstance(value, str):
        _validate_string(value, schema, path, errors)
    elif isinstance(value, bool):
        pass  # bool 已在类型层处理，避免落入 number 分支
    elif isinstance(value, int | float):
        _validate_number(value, schema, path, errors)
    elif isinstance(value, list):
        _validate_array(value, schema, path, errors)
    elif isinstance(value, dict):
        _validate_object(value, schema, path, errors)


def _validate_string(value: str, schema: dict, path: str, errors: list[str]) -> None:
    if not schema.get("allow_dotdot", False) and ".." in value:
        errors.append(f"{path}: '..' path traversal is forbidden")
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path}: shorter than minLength {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
    pattern = schema.get("pattern")
    if pattern is not None and re.search(pattern, value) is None:
        errors.append(f"{path}: does not match pattern {pattern}")


def _validate_number(value: float, schema: dict, path: str, errors: list[str]) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path}: above maximum {schema['maximum']}")


def _validate_array(value: list, schema: dict, path: str, errors: list[str]) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path}: fewer than minItems {schema['minItems']}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path}: more than maxItems {schema['maxItems']}")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for i, item in enumerate(value):
            _validate(item, item_schema, f"{path}[{i}]", errors)


def _validate_object(value: dict, schema: dict, path: str, errors: list[str]) -> None:
    props: dict = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in value:
            errors.append(f"{path}: missing required property '{req}'")
    # 默认禁止未声明字段（抗参数偷渡）；仅 additionalProperties=True 才放行
    additional = schema.get("additionalProperties", False)
    for key, val in value.items():
        prefix = f"{path}.{key}" if path else key
        if key in props:
            _validate(val, props[key], prefix, errors)
        elif additional is False:
            errors.append(f"{prefix}: additional property not allowed")


def validate_args(args: dict, input_schema: dict) -> ValidationResult:
    """对工具 args 按 input_schema 校验。

    顶层强制按 object 处理（args 必为结构化对象）。返回 ValidationResult。
    """
    if not isinstance(args, dict):
        return ValidationResult(ok=False, errors=["args: must be an object"])
    errors: list[str] = []
    # 顶层 schema 若未标 type，默认按 object 校验 properties/required
    schema = dict(input_schema)
    schema.setdefault("type", "object")
    _validate(args, schema, "", errors)
    return ValidationResult(ok=not errors, errors=errors)
