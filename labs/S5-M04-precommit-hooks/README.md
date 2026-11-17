# S5-M04 · 口头禁令总失灵？90分钟搭建两道硬护栏与绕过攻防

<!-- SCENARIO_HEADER_START -->
## 🎬 场景与能力拆解概览

| 💥 真实开发翻车现场 | 🔍 触发问题的工程时机 | 🛡️ 要练成的核心防线 |
| :--- | :--- | :--- |
| 开发者在提示词写满“禁读密钥与强推”，长会话压缩后 AI 仍用相对路径读了 .env，编辑后几百行排版告警还塞爆了窗口。 | 在订单服务目录挂载工具调用前后置钩子，输入 13 组读写命令事件、增量编辑批次与 4 类绕过攻击样本实测。 | 精准放行 .env.example 并硬阻断路径穿越读密与强推命令，改后仅回传 ≤5 行摘要，补齐沙箱权限纵深防线。 |

- **核心能力积木**：`B04 按需技能包 (SKILL.md) + Hooks 安检` · `B02 独立反方盲评 + 交叉核查脱敏`
- **推荐实现链路**：规范化路径拦截 .env 与私钥并放行模板 → 阻断强推硬重置等高危命令并以退出码 2 回传原因 → 改后仅扫变动文件限 5 行反馈 → 复盘软链拼接绕过并配沙箱
- **头号避坑红线**：一刀切拦死 .env.example 导致正常开发卡壳，或误以为简单字符串黑名单能防住软链接、动态拼接与 +HEAD 强推绕过。
<!-- SCENARIO_HEADER_END -->


> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`idea` ｜ **专题**：`vibe_coding` ｜ **预计耗时**：90 分钟

## 1. 场景痛点：为什么提示词里写满“禁止读密钥”还是会破防？

给 AI 编程助手开放读写文件与终端权限后，纯靠系统提示词里的口头禁令有三大软肋：
1. **长对话遗忘与顺手越界**：会话一长或经过上下文压缩，助手排查配置报错时依然会顺手执行 `Read(".env")` 或 `cat .env.production`。
2. **一刀切误伤或漏拦路径穿越**：朴素的子串匹配 `".env" in path` 会把合法公开模板 `.env.example` 也误杀拦死，却拦不住 `cat ./app/../.env.local` 或读取 `~/.ssh/id_rsa`。
3. **把黑名单误当成绝对沙箱**：以为正则拦住了 `rm -rf` 和 `--force` 就高枕无忧，不知道变量拼接、软链接或 `git push origin +HEAD:main` 就能绕过文本检查。

本实验带你用纯 Python 标准库搭建一套**可直接挂载到真实 Agent `PreToolUse` / Git `pre-commit` 的双重硬护栏脚本**，并通过绕过攻防演练划清“钩子护栏 vs 系统级沙箱权限”的工程边界。

---

## 2. 本目录资源清单

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、命令行单测用法、步骤指引与验收命令 |
| `fixtures/hook_events.json` | 13 组真实 Agent 工具调用事件（含 `.env.example` 放行、`../.env` 穿越、`git push -f`、`curl \| sh` 等） |
| `fixtures/post_edit_batch.json` | 编辑后收尾检查样本（检验“仅检查改动文件 + 假测试密钥拦截 + ≤5 行失败摘要”） |
| `fixtures/bypass_vectors.json` | 4 种纯文本关键词/正则黑名单无法彻底防住的真实绕过手法样本 |
| `starter.py` | **待完善**：支持 `stdin` JSON 管道调用的钩子脚手架（存在误杀 `.env.example`、漏拦高危 Shell、刷屏回传等缺陷） |
| `solution.py` | 标准参考钩子实现（可直接复制到项目 `.claude/hooks/` 或 `pre-commit` 脚本中使用） |
| `verify.py` | 红绿双重门禁验收脚本（含真实子进程 `stdin` 退出码 2 协议实测） |

> **安全声明**：本实验所有凭证检测样本均采用明显占位符（如 `FAKE_TEST_KEY_DO_NOT_USE_12345`），不含任何真实密钥前缀。

---

## 3. Vibe Coding 一键启动口令

将下面口令粘贴到你的 Vibe Coding 工具（Cursor / Claude Code / Windsurf）中启动实验：

```text
阅读 @labs/S5-M04-precommit-hooks/README.md 与 fixtures/，带我一步步补齐 starter.py 双重护栏与绕过防御，运行 python3 labs/S5-M04-precommit-hooks/verify.py 直到全部通过。
```

---

## 4. 建议实操步骤

1. **离机命令行初体验**：先跑一次 `python3 verify.py` 查看当前 4 项红灯，再用管道喂一条模拟事件体验终端离机单测：
   ```bash
   echo '{"tool_name":"Bash","tool_input":{"command":"git push origin main -f"}}' | python3 labs/S5-M04-precommit-hooks/starter.py
   echo "退出码: $?"
   ```
2. **补齐第一道护栏：`evaluate_pre_tool_use`（敏感文件保护 + 高危命令拦截）**：
   - **路径规范化与精确白名单**：先将相对路径（含 `../` 与 `~`）规范化，拦截 `.env`、`.env.*`、`*.pem`、`*.key`、`id_rsa`、`~/.ssh/*`、`~/.aws/credentials` 等，但**明确放行** `.env.example`、`.env.sample`、`.env.template`！
   - **Shell 绕行读取与高危命令拦截**：同时扫描 `Bash` 工具命令中的敏感文件读取（如 `cat ./app/../.env.local`），以及 `git push --force` / `-f`、`git reset --hard`、指向根目录或家目录的 `rm -rf`（注意放行工作区内局部构建目录清理如 `rm -rf ./dist/build_cache`）、`curl ... | sh` / `bash`。
   - **可行动反馈**：拦截时返回 `decision="block"`, `exit_code=2`，同时提供清晰的 `reason` 与替代方案 `remediation`（如引导改读 `.env.example` 或改用新分支 PR）。
3. **补齐第二道护栏：`run_post_edit_guard`（仅查改动文件 + ≤5 行精简摘要）**：
   - 只扫描 `changed_files` 列表内的文件（忽略未改动历史遗留文件），检测误写入的明文占位密钥；
   - 过滤格式化/Lint 告警，只提取与改动文件相关的条目，并将回传给模型的 `summary_lines` 严格控制在 **≤ 5 行**（超出时合并提示剩余条数）。
4. **绕过攻防复盘：`build_bypass_defense_plan`**：
   - 针对 `fixtures/bypass_vectors.json` 中的 4 种绕过手法（动态拼接读取、软链接别名、测试脚本间接读取、`git push +HEAD:main` 引用规格强推），逐条写清**为什么纯文本/正则拦不住**（`why_regex_fails`）以及对应的**目录权限隔离 / 容器不挂载 / 测试专用低额临时密钥 / 服务端分支保护补救措施**（`isolation_remediation`）。

> **免代码平替方案**：非程序员可直接新建专用的“AI工作沙箱文件夹”，绝不在其中存放任何含密码或私钥的文件，并在客户端设置中关闭“自动执行终端命令 / 自动删除文件”开关。

---

## 5. 验收命令

在仓库根目录执行：

```bash
# 检查当前 starter.py 护栏进度（初始预期为红灯 exit 1）
python3 labs/S5-M04-precommit-hooks/verify.py

# 验证标准参考答案 solution.py（预期 4/4 全绿 exit 0）
python3 labs/S5-M04-precommit-hooks/verify.py --solution
```
