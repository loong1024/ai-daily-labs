"""S4-M08 标准参考实现：强类型注解反射 JSON Schema 与 JSON-RPC 2.0 校验报文闭环。"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from typing import Annotated, Any, Callable, Literal, get_args, get_origin, get_type_hints


@dataclass(frozen=True)
class FieldSpec:
  """轻量字段约束元数据（对标 Pydantic Field）。"""

  description: str = ""
  ge: float | None = None
  le: float | None = None
  examples: tuple[Any, ...] = ()


def _python_type_to_schema(py_type: Any) -> dict[str, Any]:
  origin = get_origin(py_type)
  if origin is Literal:
    enum_vals = list(get_args(py_type))
    if enum_vals and all(isinstance(x, str) for x in enum_vals):
      return {"type": "string", "enum": enum_vals}
    if enum_vals and all(isinstance(x, int) and not isinstance(x, bool) for x in enum_vals):
      return {"type": "integer", "enum": enum_vals}
    return {"enum": enum_vals}

  if py_type is str:
    return {"type": "string"}
  if py_type is bool:
    return {"type": "boolean"}
  if py_type is int:
    return {"type": "integer"}
  if py_type is float:
    return {"type": "number"}
  return {}


def build_tool_schema(fn: Callable[..., Any]) -> dict[str, Any]:
  """内省 Python 函数注解、FieldSpec 元数据与 docstring，组装标准 MCP 工具 Schema。"""
  sig = inspect.signature(fn)
  hints = get_type_hints(fn, globalns=getattr(fn, "__globals__", None), include_extras=True)

  properties: dict[str, Any] = {}
  required: list[str] = []

  for name, param in sig.parameters.items():
    prop: dict[str, Any] = {}
    hint = hints.get(name)
    if hint is not None:
      base_type = hint
      extras: tuple[Any, ...] = ()
      if get_origin(hint) is Annotated:
        ann_args = get_args(hint)
        base_type = ann_args[0]
        extras = ann_args[1:]

      prop.update(_python_type_to_schema(base_type))
      for meta in extras:
        if isinstance(meta, FieldSpec):
          if meta.description:
            prop["description"] = meta.description
          if meta.ge is not None:
            prop["minimum"] = meta.ge
          if meta.le is not None:
            prop["maximum"] = meta.le
          if meta.examples:
            prop["examples"] = list(meta.examples)

    if param.default is not inspect.Parameter.empty:
      prop["default"] = param.default
    else:
      required.append(name)

    properties[name] = prop

  return {
      "name": fn.__name__,
      "description": inspect.getdoc(fn) or "",
      "inputSchema": {
          "type": "object",
          "properties": properties,
          "required": required,
          "additionalProperties": False,
      },
  }


def _matches_json_type(expected_type: str, value: Any) -> bool:
  if expected_type == "string":
    return isinstance(value, str)
  if expected_type == "boolean":
    return isinstance(value, bool)
  if expected_type == "integer":
    return isinstance(value, int) and not isinstance(value, bool)
  if expected_type == "number":
    return isinstance(value, (int, float)) and not isinstance(value, bool)
  return True


def validate_arguments(input_schema: dict[str, Any], arguments: Any) -> list[str]:
  """根据 inputSchema 严格校验工具调用参数，输出结构化诊断信息。"""
  if not isinstance(arguments, dict):
    return [f"arguments 必须为 JSON 对象（object），实际收到 {type(arguments).__name__}"]

  errors: list[str] = []
  properties: dict[str, dict[str, Any]] = input_schema.get("properties", {})
  required: list[str] = input_schema.get("required", [])

  for req_field in required:
    if req_field not in arguments:
      errors.append(f"缺少必填参数 '{req_field}'")

  if input_schema.get("additionalProperties") is False:
    for key in arguments:
      if key not in properties:
        errors.append(f"不允许的未知参数 '{key}'（允许字段：{list(properties.keys())}）")

  for key, val in arguments.items():
    if key not in properties:
      continue
    rule = properties[key]
    expected_type = rule.get("type")
    if expected_type and not _matches_json_type(expected_type, val):
      errors.append(
          f"参数 '{key}' 类型错误：期望 {expected_type}，实际收到 {val!r} ({type(val).__name__})"
      )
      continue

    if "enum" in rule and val not in rule["enum"]:
      errors.append(f"参数 '{key}' 取值非法：收到 {val!r}，允许枚举值为 {rule['enum']}")

    if isinstance(val, (int, float)) and not isinstance(val, bool):
      if "minimum" in rule and val < rule["minimum"]:
        errors.append(f"参数 '{key}' 小于下限 {rule['minimum']}（实际收到 {val}）")
      if "maximum" in rule and val > rule["maximum"]:
        errors.append(f"参数 '{key}' 超出上限 {rule['maximum']}（实际收到 {val}）")

  return errors


class MiniFastMCP:
  """最小可运行 MCP 协议分发器（支持 initialize、tools/list、tools/call）。"""

  def __init__(self, name: str, version: str = "1.0.0") -> None:
    self.name = name
    self.version = version
    self._tools: dict[str, Callable[..., Any]] = {}

  def tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
    self._tools[fn.__name__] = fn
    return fn

  def list_tools(self) -> list[dict[str, Any]]:
    return [build_tool_schema(fn) for fn in self._tools.values()]

  def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
      return {
          "jsonrpc": "2.0",
          "id": req_id,
          "result": {
              "protocolVersion": "2024-11-05",
              "capabilities": {"tools": {}},
              "serverInfo": {"name": self.name, "version": self.version},
          },
      }

    if method == "tools/list":
      return {
          "jsonrpc": "2.0",
          "id": req_id,
          "result": {"tools": self.list_tools()},
      }

    if method == "tools/call":
      tool_name = params.get("name", "")
      arguments = params.get("arguments", {})
      fn = self._tools.get(tool_name)
      if fn is None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": f"未知工具：{tool_name}"},
        }

      tool_meta = build_tool_schema(fn)
      errors = validate_arguments(tool_meta["inputSchema"], arguments)
      if errors:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32602,
                "message": "Invalid params: 工具参数未通过 JSON Schema 校验",
                "data": {"tool": tool_name, "errors": errors},
            },
        }

      try:
        value = fn(**arguments)
      except (ValueError, ZeroDivisionError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"工具执行失败：{exc}"}],
                "isError": True,
            },
        }

      return {
          "jsonrpc": "2.0",
          "id": req_id,
          "result": {
              "content": [{"type": "text", "text": json.dumps({"result": value}, ensure_ascii=False)}],
              "isError": False,
          },
      }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


mcp = MiniFastMCP("calc-schema-demo")


@mcp.tool
def bad_add(a, b):  # type: ignore[no-untyped-def]
  return a + b


@mcp.tool
def good_calc(
    op: Annotated[
        Literal["add", "sub", "mul", "div"],
        FieldSpec(description="四则运算操作符：add/sub/mul/div", examples=("add", "mul")),
    ],
    a: Annotated[
        float,
        FieldSpec(description="左操作数，取值范围 [-1000000, 1000000]", ge=-1_000_000, le=1_000_000),
    ],
    b: Annotated[
        float,
        FieldSpec(
            description="右操作数，默认 1.0，除法时不可为 0，取值范围 [-1000000, 1000000]",
            ge=-1_000_000,
            le=1_000_000,
        ),
    ] = 1.0,
) -> float:
  """执行受边界约束的精确四则运算（支持加减乘除，自动拦截越界与除零）。"""
  if op == "add":
    return float(a + b)
  if op == "sub":
    return float(a - b)
  if op == "mul":
    return float(a * b)
  if op == "div":
    if b == 0:
      raise ValueError("除数 b 不能为 0，请传入非零数值。")
    return float(a / b)
  raise ValueError(f"不支持的运算操作符: {op}")


def handle_jsonrpc(request: dict[str, Any]) -> dict[str, Any]:
  return mcp.handle_jsonrpc(request)
