# S4-M08 用 Python 写 MCP 工具总报参数错？源码与报文对照

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **预计耗时**：45 分钟 | **实验类型**：协议与源码剖析 (`github`)

## 1. 场景痛点

把本地 Python 函数封装成 MCP 服务时，开发者最常踩中三个坑：

1. **手写 Schema 易脱节**：手写几十行 JSON Schema 既繁琐又容易拼错，改了函数签名却忘了改 Schema。
2. **缺少类型注解导致盲猜**：类似 `bad_add(a, b)` 不写类型注解、取值范围与文档字符串，大模型看不到枚举约束和字段说明，频频传错参数。
3. **排错方式绕弯路**：误以为本地 `stdio` 通道必须抓网络包，其实直接对照 JSON-RPC 2.0 往返报文（或 MCP Inspector 的 History 面板）就能一眼定位是 Schema 缺失、参数校验报错（`-32602`）还是业务异常（`isError: true`）。

本实验使用纯 Python 3.11 标准库（`inspect` + `typing.Annotated` + `typing.Literal`）复刻 `FastMCP` 装饰器的核心反射与 JSON-RPC 报文分发逻辑，带你彻底吃透从函数签名到协议报文的完整链路。

## 2. 目录文件说明

- `starter.py`：精简版 MCP 服务起点代码（已包含无注解对照组 `bad_add`，待补全强类型注解 `good_calc`、装饰器 Schema 反射、参数校验与除零容错）。
- `solution.py`：完整标准参考实现（零第三方依赖，支持命令行单行 JSON-RPC 交互与 Inspector 报文格式）。
- `fixtures/jsonrpc_packets.json`：标准 JSON-RPC 2.0 测试报文集（含 `initialize`、`tools/list`、合法 `tools/call`、5 类非法参数报文及除零业务异常报文）。
- `verify.py`：自动化红绿验收脚本。

## 3. Vibe Coding 一键开练口令

```text
请阅读 @labs/S4-M08-mcp-jsonrpc-schema/README.md 与 fixtures/，按 AGENTS.md 协议带我完善 starter.py，运行 python3 labs/S4-M08-mcp-jsonrpc-schema/verify.py 直至验收通过。
```

## 4. 动手步骤指引

1. **观察基线差异（5 分钟）**：运行 `python3 verify.py`，查看 `starter.py` 当前在 Schema 生成与非法参数校验上的红灯提示。
2. **补全强类型工具签名（10 分钟）**：保留无注解的 `bad_add(a, b)` 作为反面对照，为 `good_calc` 补齐 `Annotated[Literal["add", "sub", "mul", "div"], FieldSpec(...)]`、数值上下界 `ge=-1_000_000, le=1_000_000`、默认值 `b=1.0` 与清晰的中文 docstring。
3. **实现装饰器 Schema 反射（15 分钟）**：完善 `build_tool_schema(fn)`，利用 `inspect.signature`、`inspect.getdoc` 与 `typing.get_type_hints(fn, include_extras=True)` 自动拼装包含 `type`、`enum`、`minimum`、`maximum`、`default`、`required` 与 `additionalProperties: False` 的 JSON Schema。
4. **打通参数校验与 JSON-RPC 报错报文（15 分钟）**：完善 `validate_arguments`（注意在 Python 中 `isinstance(True, int)` 为 `True`，需显式排除布尔值冒充数字！）与 `handle_jsonrpc`：参数不合法时回传 JSON-RPC `code: -32602` 错误对象；除数为 0 等业务异常回传 `result.isError = True` 的工具提示文本。

> **扩展联调提示**：若本地已安装 Node.js 与官方 SDK（`pip install "mcp[cli]"`），也可运行 `npx @modelcontextprotocol/inspector` 在可视化 History 面板中观察同构 JSON-RPC 往返报文。  
> **免代码平替方案**：产品或测试同学可将自然语言接口需求整理为“字段名 / 类型 / 取值枚举 / 必填 / 示例”五列表格，直接对照 `tools/list` 返回的 `inputSchema` 验收研发交付的插件防呆质量。

## 5. 验收命令

```bash
# 检查当前 starter.py 进度（初始预期为 FAIL）
python3 labs/S4-M08-mcp-jsonrpc-schema/verify.py

# 验证标准参考答案 solution.py（预期 4/4 全绿 PASS）
python3 labs/S4-M08-mcp-jsonrpc-schema/verify.py --solution
```
