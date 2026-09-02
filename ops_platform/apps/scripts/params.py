"""脚本参数 schema 定义与校验。

schema 元素:
{
    "name": "host",            # 必填,参数名
    "label": "目标主机",        # 可选,展示名
    "type": "string",          # string|integer|float|boolean
    "required": false,         # 默认 false
    "default": null,           # 默认值
    "description": "...",      # 可选,说明
    "min_length"/"max_length", # string 专用
    "min"/"max",               # integer/float 专用
}
"""
from __future__ import annotations

SUPPORTED_TYPES = ("string", "integer", "float", "boolean")

# 兼容中文键,便于误用时报错清晰
_TYPE_ALIASES = {
    "str": "string",
    "int": "integer",
    "float": "float",
    "bool": "boolean",
}


class ParamsValidationError(ValueError):
    """参数校验失败。"""


def normalize_type(ftype: str) -> str:
    return _TYPE_ALIASES.get(ftype, ftype)


def validate_schema(schema) -> list[str]:
    """校验参数 schema 本身是否合法,返回错误列表(空 = 合法)。"""
    if not isinstance(schema, list):
        return ["params_schema 必须是列表"]
    errors: list[str] = []
    seen: set[str] = set()
    for i, field in enumerate(schema):
        if not isinstance(field, dict) or not field.get("name"):
            errors.append(f"第 {i} 个参数定义缺少 name")
            continue
        name = field["name"]
        if name in seen:
            errors.append(f"参数名重复: {name}")
        seen.add(name)
        ftype = normalize_type(field.get("type", "string"))
        if ftype not in SUPPORTED_TYPES:
            errors.append(f"参数 {name} 类型不支持: {field.get('type')}")
    return errors


def validate_params(schema, params) -> tuple[dict, list[str]]:
    """按 schema 校验并归一化传入参数。

    返回 (normalized, errors):normalized 已做类型转换与默认值填充;
    errors 非空时表示校验失败,调用方应拒绝执行。
    """
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return {}, ["参数必须是对象"]

    normalized: dict = {}
    errors: list[str] = []

    for field in schema or []:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if not name:
            continue
        ftype = normalize_type(field.get("type", "string"))
        if ftype not in SUPPORTED_TYPES:
            errors.append(f"参数 {name} 类型不支持: {field.get('type')}")
            continue

        present = name in params
        value = params.get(name, field.get("default"))
        if value is None:
            if field.get("required") and not present:
                errors.append(f"缺少必填参数: {name}")
                continue
            normalized[name] = None
            continue
        try:
            normalized[name] = _coerce(ftype, value, field)
        except ValueError as exc:
            errors.append(str(exc))

    return normalized, errors


def _coerce(ftype: str, value, field: dict):
    name = field["name"]
    if ftype == "string":
        if not isinstance(value, str):
            raise ValueError(f"参数 {name} 应为字符串")
        value = value.strip()
        if not value:
            raise ValueError(f"参数 {name} 不能为空")
        if "min_length" in field and len(value) < int(field["min_length"]):
            raise ValueError(f"参数 {name} 长度不能小于 {field['min_length']}")
        if "max_length" in field and len(value) > int(field["max_length"]):
            raise ValueError(f"参数 {name} 长度不能大于 {field['max_length']}")
        return value
    if ftype == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"参数 {name} 应为整数")
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {name} 应为整数")
        if "min" in field and v < int(field["min"]):
            raise ValueError(f"参数 {name} 不能小于 {field['min']}")
        if "max" in field and v > int(field["max"]):
            raise ValueError(f"参数 {name} 不能大于 {field['max']}")
        return v
    if ftype == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"参数 {name} 应为数字")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {name} 应为数字")
        if "min" in field and v < float(field["min"]):
            raise ValueError(f"参数 {name} 不能小于 {field['min']}")
        if "max" in field and v > float(field["max"]):
            raise ValueError(f"参数 {name} 不能大于 {field['max']}")
        return v
    if ftype == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
        raise ValueError(f"参数 {name} 应为布尔值")
    raise ValueError(f"参数 {name} 类型不支持: {ftype}")
