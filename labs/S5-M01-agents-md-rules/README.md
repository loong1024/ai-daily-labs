# [S5-M01] 规则总不生效？45分钟配通多工具1页纸规则文件

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`github` ｜ **预计耗时**：45 分钟 ｜ **零代码友好**：否（附免代码平替方案）

---

## 1. 场景痛点与实验目标

用 AI 编程助手接手存量工程或多人协作时，几乎每个团队都踩过这三类“规则配置失效”的坑：

- **痛点 1（文件名对不上号，白写半天没载入）**：照着网上教程建了 `AGENTS.md`（甚至随手起了个 `AI_NOTES.txt`），结果团队成员用的 Claude Code 默认读 `CLAUDE.md`、Cursor 读 `.cursor/rules/*.mdc`、GitHub Copilot 读 `.github/copilot-instructions.md`，新开会话根本没自动载入。
- **痛点 2（命令全靠猜，年久失修误导助手）**：每次新开会话都要重新口述构建与单测命令，或者规则里还留着早已废弃的 `pip install -r requirements.txt`、`poetry`、`flake8`，导致助手反复报错或漏跑类型体检。
- **痛点 3（塞满几百行正确的废话，淹没真正红线）**：把“变量命名要有意义”“遵循 SOLID 原则”“注意代码可读性”等大模型早就滚瓜烂熟的通用常识塞成几百行长文，既浪费开局上下文，又稀释了“严禁手改 `src/generated/` 生成目录”等救命禁令。

### 实验目标
在本实验中，你将针对真实微服务仓库画像（`acme-invoice-api`），完成**“无规则/烂规则对照组”与“≤60 行自载入 1 页纸规则文件 + 多工具自动桥接”实验组对照**，确保 Codex / Claude Code / Cursor / Copilot 四端自动载入同一事实源，首轮即跑对 `uv` 测试链且零触碰禁改目录。

> 💡 **免代码平替方案（网页对话 / 项目知识库用户）**：  
> 不写代码时，可在 ChatGPT Projects / Claude Projects / Gemini Gem 的自定义指令中置顶一份 ≤20 行的**“入职 1 页纸公约”**（明确输出格式、严禁杜撰的数据禁区、交付前自检清单），新开干净对话发一个真实任务验证 AI 是否无需提醒主动遵守。

---

## 2. 本目录文件说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、步骤指引与验收命令（本文件） |
| `fixtures/project_manifest.json` | 目标工程 `acme-invoice-api` 真实清单（实测有效的 `uv` 命令、已废弃旧命令、禁改目录、错误处理约定与环境变量坑位） |
| `fixtures/baseline_control_log.json` | **裸奔对照组实录**：记录无有效规则时 AI 助手在 4 类典型任务中猜错命令、误改生成目录、漏设内存库环境变量的踩坑现场 |
| `starter.md` | **待完善起点（臃肿失效版 `AGENTS.md`）**：超长（>70 行）、塞满通用编程常识、残留过期命令与伪造测试密钥，且漏掉禁改目录 |
| `starter.py` | **待完善起点（多工具桥接与仿真器）**：文件名写错导致主流客户端均未自动载入，且规则审计函数未实现 |
| `solution.md` | **标准参考答案（≤60 行精炼版 `AGENTS.md`）**：四段式 1 页纸高信噪比规则（命令 / 约定 / 禁区 / 常见坑），零废话零密钥 |
| `solution.py` | **标准参考答案（多工具桥接与对照验证器）**：一键生成 `CLAUDE.md`（`@AGENTS.md`）、`.cursor/rules/project.mdc`（`alwaysApply: true`）与 Copilot 桥接文件，并完成对照会话验证 |
| `verify.py` | 自动化红绿闭环验收脚本（验证篇幅预算、命令对齐、禁区覆盖、四端自载入与对照实验闭环） |

---

## 3. Vibe Coding 一键启动口令

打开你的 Vibe Coding 工具，直接粘贴以下口令开始演练：

```text
请阅读 @labs/S5-M01-agents-md-rules/README.md 与 fixtures/，按 AGENTS.md 带我完善 starter 文件并运行 python3 labs/S5-M01-agents-md-rules/verify.py 直至全绿。
```

---

## 4. 动手步骤指引

1. **查看对照组踩坑现场并运行红灯基线**：阅读 `fixtures/baseline_control_log.json` 与 `fixtures/project_manifest.json`，执行 `python3 verify.py` 查看 `starter.md` 与 `starter.py` 的诊断提示。
2. **给 `starter.md` 做狠心减法，重写 ≤60 行核心 `AGENTS.md`**：
   - 严格控制在 **≤60 行**，保留清晰四段结构：`## 命令`、`## 约定`、`## 禁区`、`## 常见坑`。
   - **删光通用常识与密钥**：删掉所有 SOLID / PEP8 / 变量命名说教，移除任何测试密钥；长篇架构背景仅留文档路径 `docs/architecture.md`。
   - **对齐真实可跑通命令**：写明 `uv sync --frozen`、单测 `uv run pytest <path>`、提交前必跑 `uv run ruff check . && uv run mypy src && uv run pytest` 以及代码生成命令 `uv run python scripts/gen_schema.py`（切勿出现 `pip install -r`、`poetry`、`flake8` 等过期命令）。
   - **锁死禁区与常见坑**：在 `## 禁区` 明确禁止手改 `src/generated/`、`migrations/versions/`、`vendor/` 及未经说明新增依赖；在 `## 约定` 写明统一使用 `src/core/errors.py` 的 `AppError` 且改接口必补 `tests/` 单测；在 `## 常见坑` 写明集成测试环境变量 `TEST_DATABASE_URL=sqlite:///:memory:`。
3. **完善 `starter.py`（打通四端自动载入与对照验证）**：
   - 实现 `build_multitool_adapters`：以 `AGENTS.md` 为唯一事实源，生成 `CLAUDE.md`（首行 `@AGENTS.md` 引用）、`.cursor/rules/project.mdc`（含 `alwaysApply: true` YAML Frontmatter）与 `.github/copilot-instructions.md`，避免多份拷贝各自腐化。
   - 实现 `audit_rules_doc` 与 `evaluate_onboarding_tasks`，验证新开会话 4 个客户端 100% 自动载入，4 项任务首轮跑对单测且零触碰禁区。

---

## 5. 验收命令

```bash
# 检查你当前修改的 starter.md 与 starter.py 进度
python3 verify.py

# 验证官方参考答案 solution.md 与 solution.py（应 5/5 全绿通过）
python3 verify.py --solution
```
