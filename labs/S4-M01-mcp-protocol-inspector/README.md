# S4-M01：换客户端就要重写工具接口？用 Inspector 拆解标准 MCP

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **实验类型**：`github` ｜ **专题**：`agent_mcp` ｜ **预计耗时**：75 分钟 ｜ **零代码友好**：否

---

## 一、场景需求与常见痛点

当你已经理解大模型工具调用循环（Tool Calling Loop），下一步往往是让本地 AI 助手安全读取指定工作目录，并在 Cursor、Claude Desktop、Windsurf、VS Code 等多个客户端之间复用同一套本地能力。如果缺乏统一协议与边界意识，极易踩中以下三大痛点：

1. **胶水代码重复造轮子**：每换一个宿主客户端就要重新封装本地工具函数、JSON Schema 与鉴权胶水逻辑，接口完全无法跨客户端复用。
2. **三类原语职责混淆**：分不清 `Tools`（工具）、`Resources`（只读资源）和 `Prompts`（提示词模板）的触发与控制主体，常把静态说明文档硬塞成无参 Tool，白白消耗模型推理轮次。
3. **文件系统裸奔越权**：直接把本地文件系统暴露给模型却未做严格的 `realpath` 目录白名单校验，极易被 `../` 路径穿越、同名前缀目录（如 `/tmp/mcp-demo-secrets`）或符号链接逃逸读取敏感配置。

**实验目标**：
1. 在本地可选配合 `npx @modelcontextprotocol/inspector` 直连官方 `Everything` 与 `Filesystem` 参考服务，观察 JSON-RPC 2.0 握手与原语交互报文；
2. 动手修复 `starter.py` 中的 **MCP 三类原语协议拆解器**、**目录白名单沙箱守卫** 与 **工具 Schema 防呆体检重构器**，通过 `verify.py` 全部量化断言并生成完整《MCP Inspector 拆解与安全体检报告》。

---

## 二、本目录资源说明

```text
labs/S4-M01-mcp-protocol-inspector/
├── README.md                         # 实验说明、Inspector 实操指南与验收命令
├── fixtures/
│   ├── inspector_traces.json         # 真实脱敏的 MCP Inspector JSON-RPC 2.0 抓包记录（含握手、三类原语、-32602 报错与反模式）
│   ├── sandbox_cases.json            # Filesystem 目录白名单边界测试用例（含目录穿越、前缀欺骗、软链逃逸、只读拦截）
│   └── messy_tool_schemas.json       # 待体检的工具 Schema 样本（3 个典型坏设计与 1 个小而专标杆工具）
├── starter.py                        # 起点半成品（含原语控制方误判、前缀字符串沙箱漏洞、未防呆的 Schema 透传）
├── solution.py                       # 标准参考实现（零第三方依赖，支持离线确定性 Mock 与在线大模型双模运行）
└── verify.py                         # 自动化红绿验收脚本（4 项量化门禁）
```

---

## 三、Vibe Coding 一键启动口令

将下面口令直接粘贴给你的 AI 编程助手（Cursor / Claude Code / Windsurf 等）：

```text
请阅读 @labs/S4-M01-mcp-protocol-inspector/README.md 与 fixtures/ 测试素材，按根目录 AGENTS.md 结对教练协议带我一步步改进 starter.py，运行 verify.py 直到全部验收通过。
```

---

## 四、实操步骤指引

### 步骤 1：本地 MCP Inspector 实测（推荐实操，无 Node 环境可直接用 `fixtures/` 抓包开练）
若本机已安装 Node.js 18+（运行 `node -v && npx -v` 确认），可在终端亲手体验官方参考服务：

```bash
# 1. 创建本地测试沙箱目录与示例文件
mkdir -p /tmp/mcp-demo && echo "MCP Sandbox OK" > /tmp/mcp-demo/hello.txt

# 2. 启动 Inspector 直连 Everything 参考服务（体验 Tools / Resources / Prompts 全原语）
npx @modelcontextprotocol/inspector npx -y @modelcontextprotocol/server-everything

# 3. 切换直连 Filesystem 参考服务（实测 /tmp/mcp-demo 白名单放行与沙箱外路径拒绝）
npx @modelcontextprotocol/inspector npx -y @modelcontextprotocol/server-filesystem /tmp/mcp-demo
```

> **免代码平替提示**：不跑命令行的同学，可在桌面 AI 助手中分别开启“只读目录连接器”与“内置斜杠提示词”，对比记录“模型自主调工具、应用挂载上下文文件、用户手动点选模板”三类触发差异。

### 步骤 2：先跑红灯基线，看清 3 类典型工程缺陷
在仓库根目录或本实验目录运行验收脚本，观察当前 `starter.py` 暴露的问题：

```bash
python3 labs/S4-M01-mcp-protocol-inspector/verify.py
```

你会看到 `starter.py` 存在三处典型缺陷：
1. 把 `Tools`、`Resources`、`Prompts` 全部错误标记为由 `model` 控制，且漏提取了 Resource 的 `uri` 与 `-32602` 参数错误报文；
2. 沙箱校验使用了脆弱的字符串前缀 `str(path).startswith(str(root))`，导致 `../` 路径穿越、同名前缀目录 `/tmp/mcp-demo-secrets` 以及符号链接逃逸全部漏检放行；
3. 工具 Schema 体检原样透传了含糊工具名（`do_data`、`manage_files`、`query_tickets`），未做职责拆分、参数 `enum` 下拉化与分页上限 `maximum` 约束。

### 步骤 3：改造 `starter.py` 完成三大核心模块
1. **`build_primitive_comparison_table`**：准确区分三类原语的控制主体——
   - `tools/call` → `Tools` → 控制方 `model`（模型自主决策触发计算或副作用操作）
   - `resources/read` → `Resources` → 控制方 `application`（客户端/宿主应用按需挂载只读上下文，以 `uri` 标识）
   - `prompts/get` → `Prompts` → 控制方 `user`（用户从斜杠菜单或模板列表显式点选）
   同时提取 `-32602` 等参数错误观测记录与“把静态文档硬塞成无参工具”的反模式诊断。
2. **`evaluate_filesystem_access`**：使用 `pathlib.Path.resolve()` 解析真实物理路径，配合 `is_relative_to()` 严格校验白名单根目录，识别符号链接逃逸（`SYMLINK_ESCAPE`）、越界路径（`OUTSIDE_ALLOWLIST`）以及只读模式写拦截（`READ_ONLY_VIOLATION`）。
3. **`build_schema_upgrade_plan` & `render_inspector_report`**：针对 3 个坏设计工具输出改进前后的具体名称、用途与禁用边界说明、带 `enum` 与 `maximum` 防呆约束的 JSON Schema 及合法调用示例，并汇总渲染 Markdown 体检报告。

---

## 五、验收命令

```bash
# 在当前实验目录下运行（检查你的 starter.py 当前修改进度）
python3 verify.py

# 在仓库根目录下运行
python3 labs/S4-M01-mcp-protocol-inspector/verify.py

# 验证标准参考答案 solution.py（应 100% 全绿通过）
python3 verify.py --solution
```
