"""S4-M08 起点代码：极简 Python MCP 装饰器反射与 JSON-RPC 2.0 报文引擎。

请完成以下三处核心改造：
1. 为 good_calc 补齐 Annotated + Literal + FieldSpec 类型注解与 docstring（保留无注解 bad_add 作为对照）。
2. 完善 build_tool_schema(fn)：反射提取类型、Literal 枚举、FieldSpec 范围/描述与默认值生成标准 inputSchema。
3. 完善 validate_arguments 与 handle_jsonrpc：非法参数回传 -32602 JSON-RPC 错误，业务除零错误回传 isError=True。
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from typing import Annotated, Any, Callable, Literal, get_args, get_origin, get_type_hints

_ = (Annotated, Literal, get_args, get_origin, get_type_hints)


@dataclass(frozen=True)
class FieldSpec:
  """轻量字段约束元数据（对标 Pydantic Field）。"""

  description: str = ""
  ge: float | None = None
  le: float | None = None
  examples: tuple[Any, ...] = ()


def build_tool_schema(fn: Callable[..., Any]) -> dict[str, Any]:
  """根据 Python 函数签名、类型注解与文档字符串生成 MCP 工具描述与 JSON Schema。

  TODO(1)：当前仅输出了空属性字典 {}，未解析 typing.get_type_hints(..., include_extras=True)
  中的基础类型、Literal 枚举、FieldSpec(description/ge/le/examples) 以及默认参数！
  """
  sig = inspect.signature(fn)
  properties: dict[str, Any] = {}
  required: list[str] = []

  for name, param in sig.parameters.items():
    properties[name] = {}
    if param.default is inspect.Parameter.empty:
      required.append(name)

  return {
      "name": fn.__name__,
      "description": inspect.getdoc(fn) or "",
      "inputSchema": {
          "type": "object",
          "properties": properties,
          "required": required,
      },
  }


def validate_arguments(input_schema: dict[str, Any], arguments: Any) -> list[str]:
  """按生成的 JSON Schema 校验调用参数，返回人类与模型可读的错误列表（空列表表示合法）。

  TODO(2)：当前未做必填项、未知字段、数据类型（注意排除 bool 冒充 number！）、enum 枚举和 minimum/maximum 校验！
  """
  _ = (input_schema, arguments)
  return []


class MiniFastMCP:
  """最小可运行 MCP 协议分发器（零第三方依赖，复刻 FastMCP 核心机制）。"""

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

      # TODO(3)：当工具内部抛出除零或 ValueError 等业务异常时，应捕获并回传 result.isError = True，避免服务崩溃！
      value = fn(**arguments)
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
  # 反面对照组：请保持无注解、无文档字符串，用于对比 tools/list 生成结果
  return a + b


@mcp.tool
def good_calc(op, a, b=1.0):  # type: ignore[no-untyped-def]
  # TODO(1)：请补齐 Annotated[Literal[...], FieldSpec(...)] 强类型注解、数值范围约束、docstring 及除零检查
  if op == "add":
    return float(a + b)
  if op == "sub":
    return float(a - b)
  if op == "mul":
    return float(a * b)
  if op == "div":
    return float(a / b)
  raise ValueError(f"不支持的运算类型: {op}")


def handle_jsonrpc(request: dict[str, Any]) -> dict[str, Any]:
  return mcp.handle_jsonrpc(request)
