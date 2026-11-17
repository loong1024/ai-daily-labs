#!/usr/bin/env python3
"""S4-M08 自动化红绿验收脚本：MCP 装饰器 Schema 反射与 JSON-RPC 报文对照。"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution

_ = (chat_complete, use_solution)


def _load_target_module() -> Any:
  mod_path = target_file(LAB_DIR, "starter.py", "solution.py")
  mod_name = f"s4_m08_{mod_path.stem}"
  spec = importlib.util.spec_from_file_location(mod_name, mod_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"无法加载模块：{mod_path}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[mod_name] = module
  spec.loader.exec_module(module)
  return module


def main() -> int:
  v = LabVerifier("S4-M08", "用 Python 写 MCP 工具总报参数错？源码与报文对照")
  packets = json.loads((LAB_DIR / "fixtures" / "jsonrpc_packets.json").read_text(encoding="utf-8"))

  try:
    mod = _load_target_module()
  except Exception as exc:
    v.check("模块语法与导入检查", False, f"导入目标文件失败：{exc}")
    return v.finish()

  # 1. 检查 tools/list 中 bad_add 与 good_calc 的 JSON Schema 差异
  try:
    list_resp = mod.handle_jsonrpc(packets["tools_list_request"])
    tools_list = list_resp.get("result", {}).get("tools", [])
    by_name = {t["name"]: t for t in tools_list if isinstance(t, dict) and "name" in t}

    bad_t = by_name.get("bad_add", {})
    good_t = by_name.get("good_calc", {})
    good_schema = good_t.get("inputSchema", {})
    good_props = good_schema.get("properties", {})
    op_prop = good_props.get("op", {})
    a_prop = good_props.get("a", {})
    b_prop = good_props.get("b", {})

    bad_is_untyped = bad_t.get("inputSchema", {}).get("properties", {}).get("a") == {}
    good_is_rich = (
        len(str(good_t.get("description", "")).strip()) >= 10
        and good_schema.get("required") == ["op", "a"]
        and op_prop.get("type") == "string"
        and op_prop.get("enum") == ["add", "sub", "mul", "div"]
        and a_prop.get("type") == "number"
        and a_prop.get("minimum") == -1_000_000
        and a_prop.get("maximum") == 1_000_000
        and b_prop.get("type") == "number"
        and b_prop.get("default") == 1.0
        and len(str(a_prop.get("description", "")).strip()) > 0
    )
    v.check(
        "检查 1 · 装饰器 Schema 反射（保留无注解 bad_add 对照，good_calc 含完整枚举/上下界/默认值）",
        bad_is_untyped and good_is_rich,
        "请为 good_calc 添加 Annotated[Literal['add','sub','mul','div'], FieldSpec(...)] 与数值上下界注解，并在 build_tool_schema 中用 get_type_hints(..., include_extras=True) 提取 enum/minimum/maximum/default/description。",
    )
  except Exception as exc:
    v.check(
        "检查 1 · 装饰器 Schema 反射（保留无注解 bad_add 对照，good_calc 含完整枚举/上下界/默认值）",
        False,
        f"调用 tools/list 解析 Schema 时报错：{exc}",
    )

  # 2. 检查 initialize 握手与合法参数调用
  try:
    init_resp = mod.handle_jsonrpc(packets["initialize_request"])
    init_ok = (
        init_resp.get("jsonrpc") == "2.0"
        and init_resp.get("id") == packets["initialize_request"]["id"]
        and "protocolVersion" in init_resp.get("result", {})
        and "tools" in init_resp.get("result", {}).get("capabilities", {})
    )

    calls_ok = True
    for item in packets["valid_call_requests"]:
      resp = mod.handle_jsonrpc(item["request"])
      res_obj = resp.get("result", {})
      content_arr = res_obj.get("content", [])
      if res_obj.get("isError") is not False or not content_arr:
        calls_ok = False
        break
      parsed = json.loads(content_arr[0]["text"])
      if abs(float(parsed["result"]) - float(item["expected_value"])) > 1e-6:
        calls_ok = False
        break

    v.check(
        "检查 2 · JSON-RPC 握手与合法调用报文（initialize 与默认参数/乘法计算准确返回）",
        init_ok and calls_ok,
        "请确保 initialize 与合法 tools/call 均返回标准 JSON-RPC 2.0 响应且支持默认参数 b=1.0。",
    )
  except Exception as exc:
    v.check(
        "检查 2 · JSON-RPC 握手与合法调用报文（initialize 与默认参数/乘法计算准确返回）",
        False,
        f"执行合法 JSON-RPC 报文调用时报错：{exc}",
    )

  # 3. 检查 5 类非法参数触发 -32602 校验报错
  try:
    all_rejected = True
    failed_cases: list[str] = []
    for item in packets["invalid_call_requests"]:
      resp = mod.handle_jsonrpc(item["request"])
      err_obj = resp.get("error")
      err_list = (err_obj or {}).get("data", {}).get("errors", [])
      if (
          not isinstance(err_obj, dict)
          or err_obj.get("code") != -32602
          or not isinstance(err_list, list)
          or len(err_list) == 0
      ):
        all_rejected = False
        failed_cases.append(item["case_id"])

    v.check(
        "检查 3 · 非法参数拦截与 -32602 报错报文（覆盖枚举外、类型错、Bool 冒充数字、越界与缺参）",
        all_rejected,
        f"以下非法请求未被 validate_arguments 拦截并返回 -32602 错误明细：{failed_cases}（注意 Python 中 isinstance(True, int) 为 True，需显式排除 bool！）。",
    )
  except Exception as exc:
    v.check(
        "检查 3 · 非法参数拦截与 -32602 报错报文（覆盖枚举外、类型错、Bool 冒充数字、越界与缺参）",
        False,
        f"执行非法参数校验测试时抛出未捕获异常：{exc}",
    )

  # 4. 检查业务域除零异常优雅回传 isError: True
  try:
    div_req = packets["domain_error_request"]["request"]
    div_resp = mod.handle_jsonrpc(div_req)
    res_obj = div_resp.get("result", {})
    content_arr = res_obj.get("content", [])
    domain_err_ok = (
        div_resp.get("jsonrpc") == "2.0"
        and "error" not in div_resp
        and res_obj.get("isError") is True
        and len(content_arr) > 0
        and len(str(content_arr[0].get("text", "")).strip()) >= 5
    )
    v.check(
        "检查 4 · 业务异常防崩降级（除数为 0 时回传 result.isError=True 文本提示而非抛未捕获异常）",
        domain_err_ok,
        "请在 good_calc / handle_jsonrpc 中捕获除零或 ValueError，返回 {'result': {'content': [{'type': 'text', 'text': '...'}], 'isError': True}}。",
    )
  except Exception as exc:
    v.check(
        "检查 4 · 业务异常防崩降级（除数为 0 时回传 result.isError=True 文本提示而非抛未捕获异常）",
        False,
        f"调用除零测试报文时服务直接崩溃：{exc}",
    )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
