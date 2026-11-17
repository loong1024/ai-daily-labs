# S4-M07 让 Agent 夜间无人值守怕删库泄密？四道物理边界安全压测

<!-- SCENARIO_HEADER_START -->
## 🎬 场景与能力拆解概览

| 💥 真实开发翻车现场 | 🔍 触发问题的工程时机 | 🛡️ 要练成的核心防线 |
| :--- | :--- | :--- |
| 准备把巡检 Agent 挂到夜间定时任务无人值守的工程师，常因直接透传宿主机全量环境变量、未锁目录边界且允许预览页加载外链图片，险些被恶意文本窃走凭证。 | 用在无人值守巡检智能体上线前红蓝攻防演练环节：输入 `sandbox_cases.json` 中的越界路径、模拟密钥环境、外链探针 Markdown 与异常死循环序列。 | 筑牢四道物理防线：工作区外路径 100% 抛错拦截、子进程敏感环境变量 0 残留、CSP 阻断外链图片静默泄密，以及连续相同报错超 2 次立即硬熔断留痕。 |

- **核心能力积木**：`B11 防呆聚合工具 (dry_run) + MCP 标准接入` · `B04 按需技能包 (SKILL.md) + Hooks 安检` · `B10 幂等防重账本 + 退避死信 + 人工审批门`
- **推荐实现链路**：基线靶机复现四类失守现场 → `Path.resolve()` 锁死工作区物理根目录 → 子进程显式传入最小白名单 `env` 清零凭证 → 预览页注入严格 CSP 并剥离外链图 → 代码级连续报错计数器触发硬熔断写审计日志
- **头号避坑红线**：哪怕沙箱里没配发信或联网工具，只要前端预览页无限制渲染模型吐出的 Markdown 外链图片，浏览器就会自动发请求把机密带出去，必须配齐严格 CSP 白名单！
<!-- SCENARIO_HEADER_END -->


> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **预计耗时**：60 分钟 | **实验类型**：安全边界加固与压测 (`checklist`)

## 1. 场景痛点

把本地或服务器 Agent 交给夜间定时任务无人值守运行前，最典型的三大隐患是：

1. **目录无隔离**：图省事直接用高权限工作目录裸跑，路径拼接未做边界校验，`../` 或外部绝对路径即可越界读写宿主机文件。
2. **环境变量全透传**：子进程默认继承宿主机全量 `os.environ`，残留的云凭证或数据库口令一旦被工具读取即刻失守。
3. **外链渲染与死循环失控**：只靠提示词叮嘱“别泄密、别死循环”，遇到 Markdown 外链图片或工具连续报错重试，依然会触发外发请求与无限空转。

本实验通过“基线缺陷复现 → 四道物理边界加固 → 自动化回归验收”闭环，让你亲手把脆弱沙箱改造为可无人值守运行的安全底座。

## 2. 目录文件说明

- `starter.py`：待加固的极简沙箱基线实现（含目录越界、全量环境变量透传、无 CSP 外链渲染、无死循环熔断四处典型缺陷）。
- `solution.py`：四道物理边界完整加固参考实现（纯 Python 3.11 标准库）。
- `fixtures/sandbox_cases.json`：脱敏压测样本集（含越界路径、模拟测试凭证 `FAKE_TEST_KEY_DO_NOT_USE_12345`、外链 Markdown 与异常重试序列）。
- `fixtures/prelaunch_checklist.md`：免代码团队通用的《四道物理边界上线前自检表》。
- `verify.py`：红绿闭环验收脚本（默认检测 `starter.py`，传入 `--solution` 验证标准实现）。

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴到 Cursor / Claude Code / Windsurf 对话框即可启动结对闯关：

```text
请阅读 @labs/S4-M07-agent-sandbox-redteam/README.md 与 fixtures/，按 AGENTS.md 协议带我加固 starter.py，运行 python3 labs/S4-M07-agent-sandbox-redteam/verify.py 直至验收通过。
```

## 4. 动手步骤指引

1. **复现基线红灯（5 分钟）**：运行 `python3 verify.py`，观察未加固版本在四道边界上的失败项与改进提示。
2. **第一道边界 · 工作区路径隔离（15 分钟）**：完善 `starter.py` 中的 `read_workspace_file`，使用 `Path.resolve()` 与 `is_relative_to()` 确保任何跳出 `workspace_root` 的相对或绝对路径均抛出 `PermissionError`。
3. **第二道边界 · 子进程凭证脱敏（10 分钟）**：完善 `build_isolated_env` 与 `probe_subprocess_env`，改用严格白名单（仅保留 `PATH`、`LANG` 等基础运行变量），显式清空无关敏感变量并将工作目录锁定在工作区内。
4. **第三道边界 · CSP 与外链图片阻断（15 分钟）**：完善 `render_safe_preview_html`，在 `<head>` 注入 `Content-Security-Policy: default-src 'self'; img-src 'self';`，转义正文 HTML，并将 `http://` / `https://` 等外部图片地址替换为本地拦截占位符。
5. **第四道边界 · 连续报错硬熔断与审计日志（15 分钟）**：完善 `run_guarded_tool_loop`，跟踪连续相同错误签名；当连续报错超过 `max_repeats=2`（即第 3 次相同报错）时立即停机（`halted=True`）并写入结构化审计日志。

> **免代码平替方案**：安全审计员或业务负责人可直接打开 `fixtures/prelaunch_checklist.md`，按表向研发团队核验四项上线截屏与日志实证。

## 5. 验收命令

在当前实验目录或仓库根目录下执行：

```bash
# 检查当前 starter.py 加固进度（初始预期为 FAIL 并输出修复指引）
python3 labs/S4-M07-agent-sandbox-redteam/verify.py

# 验证标准参考答案 solution.py（预期 4/4 全绿 PASS）
python3 labs/S4-M07-agent-sandbox-redteam/verify.py --solution
```
