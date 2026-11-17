# [S0-M04] 怕误推密钥上仓库？提交前密钥安检 Skill 实战

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`skill` ｜ **预计耗时**：60 分钟 ｜ **零代码友好**：否（附免代码平替方案）

---

## 1. 场景痛点与实验目标

用编码 Agent 快速写完脚本准备 `git commit` / `git push` 或将私有仓库设为公开开源时，最致命的事故莫过于**把真实 API Key 或 `.env` 推上仓库历史**：

- **痛点 1（删文件不等于删历史）**：测试时图省事把 Key 写死在源码里，提交后虽然删掉了那行代码，但它依然永久躺在 Git Commit 历史记录中，公开仓库几秒钟就会被自动化爬虫扫走。
- **痛点 2（口头叮嘱靠不住）**：只靠对话里提醒 Agent“别提交密钥”，一忙起来照样把本地 `.env`、前端调试配置或日志一起打包提交。
- **痛点 3（应急顺序搞反）**：发现泄露后只顾着改代码重新提交，忘了**第一优先级是去服务商控制台吊销并轮换旧密钥**，结果额度被刷爆。

### 实验目标
在本实验中，你将构建一套即插即用的 **`secret-hygiene-check` 提交前密钥安检 Skill** 与 **本地 `pre-commit` 硬阻断检查脚本**，拿涵盖工作区硬编码、`.env` 误跟踪、Git 历史残留、前端配置暴露及 `.env.example` 占位模板的红蓝样本集完成拦截与脱敏演练。

> 💡 **免代码平替方案（日常办公 / 对话用户）**：  
> 如果你不写代码，可将本实验转化为**“对话脱敏安检”**：在把合同、财报或工单发给网页 AI 前，先用固定清单将真实姓名、手机号、银行卡号与精确金额替换为 `[客户A]`、`[手机号]`、`[金额X]` 等占位符，并在 AI 客户端设置中关闭“允许使用对话数据改进模型”开关。

---

## 2. 本目录文件说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验说明、步骤指引与验收命令（本文件） |
| `fixtures/repo_changes.json` | 红蓝对抗样本集（含 4 类高危伪造密钥泄露场景 + 3 类合规占位/环境变量读取场景 + `.gitignore` 对照样本） |
| `fixtures/gitleaks_allowlist_sample.toml` | 标准 `.gitleaks.toml` 忽略模板参考（放行 `.env.example` 与占位符，避免误报） |
| `starter.md` | **待完善起点（Skill 规约）**：残缺的 `SKILL.md`，缺历史扫描、缺脱敏遮盖规范且应急处置顺序错误 |
| `starter.py` | **待完善起点（钩子脚本）**：残缺的本地扫描与 `pre-commit` 守卫，漏扫 Git 历史与前端文件、未脱敏且未返回非零阻断码 |
| `solution.md` | **标准参考答案（Skill 规约）**：可直接放入 `.claude/skills/secret-hygiene-check/SKILL.md` 的生产级技能文件 |
| `solution.py` | **标准参考答案（钩子脚本）**：完整支持多范围扫描、占位模板免误报、前 4 位遮盖脱敏与非零退出码硬阻断 |
| `verify.py` | 自动化红绿闭环验收脚本（纯 Python 3.11 标准库，零外部依赖即可验证） |

> ⚠️ **安全说明**：本实验所有测试凭证均采用 `FAKE_TEST_KEY_DO_NOT_USE_*` 等明显假占位格式，严禁在练习中填入任何真实平台密钥。

---

## 3. Vibe Coding 一键启动口令

打开 Cursor / Claude Code / Windsurf / GitHub Codespaces，直接粘贴以下口令启动结对练习：

```text
请阅读 @labs/S0-M04-secret-scan-skill/README.md 与 fixtures/，按 AGENTS.md 带我完善 starter 文件并运行 python3 labs/S0-M04-secret-scan-skill/verify.py 直至全绿。
```

---

## 4. 动手步骤指引

1. **跑通基线红灯诊断**：先运行 `python3 verify.py`，观察未修改的 `starter.md` 与 `starter.py` 在哪 5 个安检环节失守。
2. **完善 `starter.md`（构建 `secret-hygiene-check` 技能文件）**：
   - 补齐 YAML Frontmatter：`name: secret-hygiene-check`，并在 `description` 写明触发时机（提交前、推送前、准备开源、怀疑密钥泄露）及核对 `.env` / `.gitignore`。
   - 补齐 5 步检查清单：确认 `gitleaks version` -> 扫描当前目录 `gitleaks dir -v .` -> **扫描提交历史 `gitleaks git -v .`** -> 核查 `.gitignore`（含 `.env`、`*.pem`）、`os.environ` 读取方式与 `.env.example` -> 检查前端/浏览器代码零密钥暴露。
   - 明确脱敏输出与应急红线：密钥片段**只显示前 4 位，其余用 `*` 遮盖**；发现泄露必须按**“1. 先去服务商控制台吊销并轮换密钥 -> 2. 新密钥只写本地 `.env`/密钥管理器 -> 3. 清理历史并查账单 -> 4. 开启推送保护与 pre-commit”**顺序处置；严禁打印完整密钥，未经用户明确确认严禁执行强制推送（`force push`）或改写历史。
3. **完善 `starter.py`（加装本地确定性拦截钩子）**：
   - 实现 `mask_secret`：仅保留前 4 位字符并拼接 `*` 号遮盖，严禁原样回显。
   - 升级 `scan_repo_changes`：同时覆盖 `worktree` 与 `git_history` 范围，识别源码、`.env` 与前端文件中的伪造密钥，同时对 `.env.example` 及安全占位符免误报。
   - 升级 `audit_gitignore` 与 `run_pre_commit_check`：校验 `.gitignore` 必含 `.env` 与 `*.pem`；一旦发现密钥泄露或 `.gitignore` 缺失，立即返回非零退出码 `1` 硬阻断提交！
4. **（选做）本地真仓联动 `gitleaks` 实测**：
   - 若本机已按官方文档安装 `gitleaks`，可在临时目录 `git init` 放入 `fixtures/gitleaks_allowlist_sample.toml`，实测 `gitleaks dir -v .` 与 `gitleaks git -v .` 的终端拦截输出。

---

## 5. 验收命令

```bash
# 检查你当前修改的 starter.md 与 starter.py 进度（默认模式）
python3 verify.py

# 验证官方参考答案 solution.md 与 solution.py（应 5/5 全绿通过）
python3 verify.py --solution
```
