# AI 日课 · 66 动手实验配套实战总仓 (`ai-daily-labs`)

[![Verify All 66 Labs](https://github.com/loong1024/ai-daily-labs/actions/workflows/verify-labs.yml/badge.svg)](https://github.com/loong1024/ai-daily-labs/actions/workflows/verify-labs.yml)
[![Open in GitHub Codespaces](https://img.shields.io/badge/GitHub_Codespaces-一键云端免装开练-181717?logo=github)](https://codespaces.new/loong1024/ai-daily-labs)
[![AI 日课在线教程](https://img.shields.io/badge/AI_日课-在线闯关与分类实验中心-0f766e)](https://ai-daily-dot-leonxingexp-sandbox-396955.uc.r.appspot.com/#/materials)

本仓库是 **[AI 日课 · 通用 AI 学习教程](https://ai-daily-dot-leonxingexp-sandbox-396955.uc.r.appspot.com/)** 的官方一站式动手实验单仓（Monorepo），完整收录 **`Ch.0 → Ch.7` 全部 66 个场景驱动实战实验**。

每个实验子目录均内置**真实脱敏靶场样本（`fixtures/`）**、**待改造起点文件（`starter.*`）**、**标准参考实现（`solution.*`）** 与 **红绿自动验收裁判脚本（`verify.py`）**——专为 **Cursor、Claude Code、Windsurf、VS Code Copilot、Gemini CLI、Trae 与 GitHub Codespaces** 等 Vibe Coding 工具打造，导入即练、当场验真。

---

## ⚡ 3 种方式 30 秒快速开始

### 方式一：本地 Vibe Coding 工具克隆总仓（最推荐，一次配置 66 实验通用）
```bash
git clone https://github.com/loong1024/ai-daily-labs.git
cd ai-daily-labs
```
用 Cursor / Claude Code / Windsurf 打开本仓库，直接在对话框输入（或从 [AI 日课分类实验中心](https://ai-daily-dot-leonxingexp-sandbox-396955.uc.r.appspot.com/#/materials) 一键复制口令）：
> `请阅读 @labs/S5-M09-expense-dashboard/README.md 与 fixtures/ 素材，按根目录 AGENTS.md 结对教练协议，带我一步步改造 starter 文件并运行 python3 labs/S5-M09-expense-dashboard/verify.py 直到全部验收通过！`

### 方式二：浏览器零安装开跑（GitHub Codespaces）
直接点击 **[👉 在 GitHub Codespaces 打开本仓库](https://codespaces.new/loong1024/ai-daily-labs)**，云端容器已预装 Python 3.11 环境，无需本机配置任何依赖。

### 方式三：只拉取某一个感兴趣的实验子目录
```bash
npx degit loong1024/ai-daily-labs/labs/S5-M09-expense-dashboard my-vibe-lab
cd my-vibe-lab
```

---

## 🎯 核心设计亮点：为什么适合 Vibe Coding 边做边学？

1. **Red → Green 红绿闯关闭环（拒绝“光看文档不动手”）**：
   - 刚进入任意实验跑 `python3 labs/<目录>/verify.py`，裁判脚本会检查未完成的 `starter.*`，输出清晰的 **❌ 待改进诊断提示**；
   - 你用自然语言指挥 Vibe Coding 工具改进 `starter.*` 后重跑 `verify.py`，全部指标达标即输出 **🎉 PASS**！
   - 若卡壳想对照标准答案，随时运行 `python3 labs/<目录>/verify.py --solution` 或查看同目录下的 `solution.*`。
2. **零 API Key 离线回放 + 真模型无缝切换**：
   - **默认免 Key 即可验收**：`shared/aid_lab.py` 内置确定性离线 Mock 回放，哪怕还没申请 API Key 也能 100% 跑通分块、JSON Schema 校验、BM25+向量混合重排、ReAct 循环、幂等重试与防注入拦截逻辑；
   - **一键接入真模型**：复制 `.env.example` 为 `.env`，填入任意 OpenAI 兼容接口（`OPENAI_API_KEY`）或本地 `OLLAMA_MODEL`，立即切换真实大模型实测！
3. **内置 `AGENTS.md` AI 结对助教协议**：
   - 根目录 [AGENTS.md](./AGENTS.md) 已配置好防剧透结对带学规范，编码 Agent 会主动先跑基线诊断、引导你小步迭代，而不是一把梭直接拿 `solution` 覆盖。

---

## 🌟 14 个精选必做代表实验（高 ROI 快速通道）

| 实验 ID | 章节 | 专题分类 | 门槛 | 实验目录直达 | 本地验收命令 |
|---|---|---|---|---|---|
| `P0-M01` | Ch.0 | 💬 提问与核查 | 🌱 零代码 | [看懂开源 AI 全家桶：文档转 Markdown 与工作台](./labs/P0-M01-doc-to-markdown/) | `python3 labs/P0-M01-doc-to-markdown/verify.py` |
| `P0-M02` | Ch.0 | 💬 提问与核查 | 🌱 零代码 | [任务拆解四象限：揪出个人前 3 个高收益 AI 提效点](./labs/P0-M02-task-quadrant/) | `python3 labs/P0-M02-task-quadrant/verify.py` |
| `S0-M03` | Ch.1 | 💬 提问与核查 | 🌱 零代码 | [AI 写稿怕夹带假数据？原子主张拆解与交叉核查](./labs/S0-M03-fact-claim-verify/) | `python3 labs/S0-M03-fact-claim-verify/verify.py` |
| `S0-M09` | Ch.1 | 💬 提问与核查 | 🌱 零代码 | [随口提问总拿套话？六要素+样板改写对照实验](./labs/S0-M09-six-element-prompt/) | `python3 labs/S0-M09-six-element-prompt/verify.py` |
| `S5-M01` | Ch.2 | 🎨 Vibe Coding 造物 | 💻 工程 | [规则总不生效？45分钟配通多工具1页纸规则文件](./labs/S5-M01-agents-md-rules/) | `python3 labs/S5-M01-agents-md-rules/verify.py` |
| `S5-M09` | Ch.2 | 🎨 Vibe Coding 造物 | 🌱 零代码 | [零代码造网页：15分钟生成个人习惯与开支交互看板](./labs/S5-M09-expense-dashboard/) | `python3 labs/S5-M09-expense-dashboard/verify.py` |
| `S5-M10` | Ch.2 | 🎨 Vibe Coding 造物 | 🌱 零代码 | [告别手工贴表：定制 CSV 与 Excel 合并清洗小工具](./labs/S5-M10-csv-batch-cleaner/) | `python3 labs/S5-M10-csv-batch-cleaner/verify.py` |
| `S1-M02` | Ch.3 | 📊 长文与抽表格 | 💻 工程 | [JSON 总报错还瞎猜？用 Instructor 锁死结构化抽取](./labs/S1-M02-json-schema-extract/) | `python3 labs/S1-M02-json-schema-extract/verify.py` |
| `S1-M05` | Ch.3 | 📊 长文与抽表格 | 🌱 零代码 | [长稿总结总漏后半段？分块贴便利贴与覆盖率核对实战](./labs/S1-M05-mapreduce-coverage/) | `python3 labs/S1-M05-mapreduce-coverage/verify.py` |
| `S3-M01` | Ch.4 | 🗂️ 私域知识库 RAG | 💻 工程 | [本地笔记增量索引：哈希同步防旧块残留](./labs/S3-M01-incremental-hash-index/) | `python3 labs/S3-M01-incremental-hash-index/verify.py` |
| `S3-M02` | Ch.4 | 🗂️ 私域知识库 RAG | 🌱 零代码 | [防常识混入与假引用：逐句标号与拒答闸门](./labs/S3-M02-citation-and-abstain/) | `python3 labs/S3-M02-citation-and-abstain/verify.py` |
| `S2-M01` | Ch.5 | ⚡ 自动工作流 | 💻 工程 | [定时摘要总重推或错点？轻量 n8n 立即去重与告警实验](./labs/S2-M01-n8n-dedup-alert/) | `python3 labs/S2-M01-n8n-dedup-alert/verify.py` |
| `S4-M02` | Ch.6 | 🤖 智能体与 MCP | 💻 工程 | [Agent 死循环烧钱还假装成功？手写最小安全闭环对照测](./labs/S4-M02-safe-react-loop/) | `python3 labs/S4-M02-safe-react-loop/verify.py` |
| `S6-M01` | Ch.7 | 🛡️ 评测与安全上线 | 💻 工程 | [改提示词崩老功能？用 promptfoo 搭自动回归闸门](./labs/S6-M01-ci-eval-gate/) | `python3 labs/S6-M01-ci-eval-gate/verify.py` |

---

## 📚 全量 66 个动手实验总目录（`Ch.0 → Ch.7`）

### Ch.0 通识与行业全景：AI 核心术语导学与各行业应用全景（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `P0-M01` 🌟 | 🌱 零代码 | 💬 提问与核查 | [看懂开源 AI 全家桶：文档转 Markdown 与工作台](./labs/P0-M01-doc-to-markdown/) | `python3 labs/P0-M01-doc-to-markdown/verify.py` |
| `P0-M02` 🌟 | 🌱 零代码 | 💬 提问与核查 | [任务拆解四象限：揪出个人前 3 个高收益 AI 提效点](./labs/P0-M02-task-quadrant/) | `python3 labs/P0-M02-task-quadrant/verify.py` |
| `P0-M03` | 🌱 零代码 | 💬 提问与核查 | [同一问题跑三遍：裸聊记忆、贴原文开卷与思考模式对比](./labs/P0-M03-three-modes-compare/) | `python3 labs/P0-M03-three-modes-compare/verify.py` |
| `P0-M04` | 🌱 零代码 | 🛡️ 评测与安全上线 | [严谨场景防翻车：AI 初稿外发前 5 项人工签字核查单](./labs/P0-M04-signoff-checklist/) | `python3 labs/P0-M04-signoff-checklist/verify.py` |
| `P0-M05` | 🌱 零代码 | 🎨 Vibe Coding 造物 | [零代码破冰 Vibe Coding：生成可交互个人专注番茄钟](./labs/P0-M05-vibe-pomodoro/) | `python3 labs/P0-M05-vibe-pomodoro/verify.py` |
| `P0-M06` | 🌱 零代码 | 🤖 智能体与 MCP | [选型决策演练：Prompt、知识库、工作流与 Agent](./labs/P0-M06-paradigm-selector/) | `python3 labs/P0-M06-paradigm-selector/verify.py` |
### Ch.1 提问与日常提效：结构化提问、写作润色与信息核实（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S0-M03` 🌟 | 🌱 零代码 | 💬 提问与核查 | [AI 写稿怕夹带假数据？原子主张拆解与交叉核查](./labs/S0-M03-fact-claim-verify/) | `python3 labs/S0-M03-fact-claim-verify/verify.py` |
| `S0-M06` | 🌱 零代码 | 💬 提问与核查 | [AI 图文准备对外发或商用？20 分钟发布前避坑自查](./labs/S0-M06-publish-compliance/) | `python3 labs/S0-M06-publish-compliance/verify.py` |
| `S0-M09` 🌟 | 🌱 零代码 | 💬 提问与核查 | [随口提问总拿套话？六要素+样板改写对照实验](./labs/S0-M09-six-element-prompt/) | `python3 labs/S0-M09-six-element-prompt/verify.py` |
| `S0-M10` | 🌱 零代码 | 💬 提问与核查 | [发截图读表总串行、怕泄密？看图纠错与脱敏实测](./labs/S0-M10-vision-table-redact/) | `python3 labs/S0-M10-vision-table-redact/verify.py` |
| `S1-M03` | 🌱 零代码 | 💬 提问与核查 | [AI 总顺着你吹彩虹屁？单方案中立决策与挑刺对照](./labs/S1-M03-anti-sycophancy/) | `python3 labs/S1-M03-anti-sycophancy/verify.py` |
| `S1-M08` | 🌱 零代码 | 💬 提问与核查 | [二选一怕模型偏心端水？双盲互换 + 事前验尸盲测](./labs/S1-M08-double-blind-ab/) | `python3 labs/S1-M08-double-blind-ab/verify.py` |
### Ch.2 Vibe Coding 造物：Vibe Coding 自然语言造物与 AI 协同开发（11 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S0-M04` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [怕误推密钥上仓库？提交前密钥安检 Skill 实战](./labs/S0-M04-secret-scan-skill/) | `python3 labs/S0-M04-secret-scan-skill/verify.py` |
| `S1-M04` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [仓库 Prompt 越改越乱？自制自动体检 Skill 拦截缺陷](./labs/S1-M04-prompt-lint-skill/) | `python3 labs/S1-M04-prompt-lint-skill/verify.py` |
| `S5-M01` 🌟 | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [规则总不生效？45分钟配通多工具1页纸规则文件](./labs/S5-M01-agents-md-rules/) | `python3 labs/S5-M01-agents-md-rules/verify.py` |
| `S5-M02` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [AI修Bug总盲改？复现优先Skill与降噪脚本实战](./labs/S5-M02-repro-first-skill/) | `python3 labs/S5-M02-repro-first-skill/verify.py` |
| `S5-M03` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [拒绝AI一把梭改乱千行：Spec先行与小步TDD实验](./labs/S5-M03-spec-driven-tdd/) | `python3 labs/S5-M03-spec-driven-tdd/verify.py` |
| `S5-M04` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [口头禁令总失灵？90分钟搭建两道硬护栏与绕过攻防](./labs/S5-M04-precommit-hooks/) | `python3 labs/S5-M04-precommit-hooks/verify.py` |
| `S5-M06` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [AI代码看似工整却暗藏坑？55分钟合并前排雷实操](./labs/S5-M06-diff-review-audit/) | `python3 labs/S5-M06-diff-review-audit/verify.py` |
| `S5-M07` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [主窗口被源码搜爆变笨？只读侦察子会话降噪对照实验](./labs/S5-M07-subagent-context/) | `python3 labs/S5-M07-subagent-context/verify.py` |
| `S5-M08` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [双开AI改同目录互相覆盖？git worktree隔离并行实验](./labs/S5-M08-worktree-parallel/) | `python3 labs/S5-M08-worktree-parallel/verify.py` |
| `S5-M09` 🌟 | 🌱 零代码 | 🎨 Vibe Coding 造物 | [零代码造网页：15分钟生成个人习惯与开支交互看板](./labs/S5-M09-expense-dashboard/) | `python3 labs/S5-M09-expense-dashboard/verify.py` |
| `S5-M10` 🌟 | 🌱 零代码 | 🎨 Vibe Coding 造物 | [告别手工贴表：定制 CSV 与 Excel 合并清洗小工具](./labs/S5-M10-csv-batch-cleaner/) | `python3 labs/S5-M10-csv-batch-cleaner/verify.py` |
### Ch.3 长文档与结构化 API：长报告精读、模型 API 调用与批量表格抽取（9 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S0-M01` | 💻 轻量脚本 | 📊 长文与抽表格 | [长文总被截断或超支？tiktoken 实测中英与代码账单](./labs/S0-M01-token-budget-calc/) | `python3 labs/S0-M01-token-budget-calc/verify.py` |
| `S0-M02` | 💻 轻量脚本 | 📊 长文与抽表格 | [批量抽数老漂移？本地小模型采样与窗口对照实测](./labs/S0-M02-sampling-stability/) | `python3 labs/S0-M02-sampling-stability/verify.py` |
| `S0-M05` | 💻 轻量脚本 | 📊 长文与抽表格 | [手工复制粘贴太慢？60 分钟写个批量抽表小脚本](./labs/S0-M05-batch-table-extractor/) | `python3 labs/S0-M05-batch-table-extractor/verify.py` |
| `S0-M07` | 💻 轻量脚本 | 📊 长文与抽表格 | [千条反馈和长文怎么跑最省？80 行 Python 成本模拟器](./labs/S0-M07-cost-simulator/) | `python3 labs/S0-M07-cost-simulator/verify.py` |
| `S1-M01` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [改提示词崩掉旧场景？用 promptfoo 跑批处理回归对照](./labs/S1-M01-promptfoo-regression/) | `python3 labs/S1-M01-promptfoo-regression/verify.py` |
| `S1-M02` 🌟 | 💻 轻量脚本 | 📊 长文与抽表格 | [JSON 总报错还瞎猜？用 Instructor 锁死结构化抽取](./labs/S1-M02-json-schema-extract/) | `python3 labs/S1-M02-json-schema-extract/verify.py` |
| `S1-M05` 🌟 | 🌱 零代码 | 📊 长文与抽表格 | [长稿总结总漏后半段？分块贴便利贴与覆盖率核对实战](./labs/S1-M05-mapreduce-coverage/) | `python3 labs/S1-M05-mapreduce-coverage/verify.py` |
| `S1-M06` | 💻 轻量脚本 | 📊 长文与抽表格 | [资料塞满却总答偏？大篇幅“中间遗忘”与前缀缓存实测](./labs/S1-M06-lost-in-middle/) | `python3 labs/S1-M06-lost-in-middle/verify.py` |
| `S1-M07` | 💻 轻量脚本 | 📊 长文与抽表格 | [上线怕缓存击穿又怕字段被劫持？前缀与隔离双线体检](./labs/S1-M07-cache-and-delimiter/) | `python3 labs/S1-M07-cache-and-delimiter/verify.py` |
### Ch.4 私域知识库 RAG：搭建高可信私域知识库与检索增强（RAG）（8 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S3-M01` 🌟 | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [本地笔记增量索引：哈希同步防旧块残留](./labs/S3-M01-incremental-hash-index/) | `python3 labs/S3-M01-incremental-hash-index/verify.py` |
| `S3-M02` 🌟 | 🌱 零代码 | 🗂️ 私域知识库 RAG | [防常识混入与假引用：逐句标号与拒答闸门](./labs/S3-M02-citation-and-abstain/) | `python3 labs/S3-M02-citation-and-abstain/verify.py` |
| `S3-M03` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [RAG 五层取证排障：Trace 归因与单变量修复](./labs/S3-M03-rag-trace-diagnose/) | `python3 labs/S3-M03-rag-trace-diagnose/verify.py` |
| `S3-M04` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [报错码总漏召回？混合检索与中文重排实测](./labs/S3-M04-hybrid-bm25-rerank/) | `python3 labs/S3-M04-hybrid-bm25-rerank/verify.py` |
| `S3-M05` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [拒绝凭感觉调参：建 30 题双层回归评测基线](./labs/S3-M05-rag-eval-baseline/) | `python3 labs/S3-M05-rag-eval-baseline/verify.py` |
| `S3-M06` | 🌱 零代码 | 🗂️ 私域知识库 RAG | [脏文档别直接入库！5 份硬骨头样本入库前体检](./labs/S3-M06-dirty-doc-clean/) | `python3 labs/S3-M06-dirty-doc-clean/verify.py` |
| `S3-M07` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [不装 ES 补齐关键词检索：单文件 SQLite FTS5](./labs/S3-M07-sqlite-fts5-search/) | `python3 labs/S3-M07-sqlite-fts5-search/verify.py` |
| `S3-M08` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [多轮追问总是搜偏？查询路由与结构化规划](./labs/S3-M08-multihop-query-plan/) | `python3 labs/S3-M08-multihop-query-plan/verify.py` |
### Ch.5 自动化 AI 工作流：确定性 AI 工作流编排与无人值守自动化（8 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S2-M01` 🌟 | 💻 轻量脚本 | ⚡ 自动工作流 | [定时摘要总重推或错点？轻量 n8n 立即去重与告警实验](./labs/S2-M01-n8n-dedup-alert/) | `python3 labs/S2-M01-n8n-dedup-alert/verify.py` |
| `S2-M02` | 💻 轻量脚本 | ⚡ 自动工作流 | [单一提示硬跑又慢又贵？四种工作流模式同题 10 样本基准测](./labs/S2-M02-workflow-patterns-bench/) | `python3 labs/S2-M02-workflow-patterns-bench/verify.py` |
| `S2-M03` | 💻 轻量脚本 | ⚡ 自动工作流 | [AI 抽取总乱编格式还怕提示注入？20 样本批量校验与防注入实验](./labs/S2-M03-batch-schema-anti-inject/) | `python3 labs/S2-M03-batch-schema-anti-inject/verify.py` |
| `S2-M04` | 🌱 零代码 | ⚡ 自动工作流 | [自动化脚本带病上线？给 AI 装上六维只读审查提示与靶子排雷](./labs/S2-M04-workflow-audit-skill/) | `python3 labs/S2-M04-workflow-audit-skill/verify.py` |
| `S2-M05` | 💻 轻量脚本 | ⚡ 自动工作流 | [群发周报怕重发、503 卡死或超支？幂等退避、审批与熔断演练](./labs/S2-M05-idempotent-backoff-hitl/) | `python3 labs/S2-M05-idempotent-backoff-hitl/verify.py` |
| `S2-M06` | 🌱 零代码 | ⚡ 自动工作流 | [零代码自动化一上线就翻车？通用上线体检表与三招无代码排雷](./labs/S2-M06-nocode-launch-check/) | `python3 labs/S2-M06-nocode-launch-check/verify.py` |
| `S2-M07` | 💻 轻量脚本 | ⚡ 自动工作流 | [Actions 跑 AI 怕命令注入盗密钥？私有靶场权限与隔离加固实测](./labs/S2-M07-ci-actions-hardening/) | `python3 labs/S2-M07-ci-actions-hardening/verify.py` |
| `S2-M08` | 💻 轻量脚本 | ⚡ 自动工作流 | [百条批处理断电就从头烧钱？手写断点续跑、限速与容错尾行骨架](./labs/S2-M08-checkpoint-batch-runner/) | `python3 labs/S2-M08-checkpoint-batch-runner/verify.py` |
### Ch.6 自主智能体 Agent：Agentic AI 四大设计模式、MCP 生态与安全沙箱（9 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S4-M01` | 💻 轻量脚本 | 🤖 智能体与 MCP | [换客户端就要重写工具接口？用 Inspector 拆解标准 MCP](./labs/S4-M01-mcp-protocol-inspector/) | `python3 labs/S4-M01-mcp-protocol-inspector/verify.py` |
| `S4-M02` 🌟 | 💻 轻量脚本 | 🤖 智能体与 MCP | [Agent 死循环烧钱还假装成功？手写最小安全闭环对照测](./labs/S4-M02-safe-react-loop/) | `python3 labs/S4-M02-safe-react-loop/verify.py` |
| `S4-M03` | 🌱 零代码 | 🤖 智能体与 MCP | [给 Agent 接高危工具总怕捅娄子？六维权限审查 Skill 实战](./labs/S4-M03-tool-permission-skill/) | `python3 labs/S4-M03-tool-permission-skill/verify.py` |
| `S4-M04` | 🌱 零代码 | 🤖 智能体与 MCP | [长任务 Agent 计划全废还瞎改？探针重规划提示词实测](./labs/S4-M04-probe-replan-agent/) | `python3 labs/S4-M04-probe-replan-agent/verify.py` |
| `S4-M05` | 💻 轻量脚本 | 🤖 智能体与 MCP | [个人助理记混旧信息还被网页投毒？造可过期防污染记忆层](./labs/S4-M05-anti-poison-memory/) | `python3 labs/S4-M05-anti-poison-memory/verify.py` |
| `S4-M06` | 🌱 零代码 | 🤖 智能体与 MCP | [盲目上多 Agent 越拆越慢？单双架构对比与 A2A 取舍实验](./labs/S4-M06-single-vs-multi-agent/) | `python3 labs/S4-M06-single-vs-multi-agent/verify.py` |
| `S4-M07` | 💻 轻量脚本 | 🤖 智能体与 MCP | [让 Agent 夜间无人值守怕删库泄密？四道物理边界安全压测](./labs/S4-M07-agent-sandbox-redteam/) | `python3 labs/S4-M07-agent-sandbox-redteam/verify.py` |
| `S4-M08` | 💻 轻量脚本 | 🤖 智能体与 MCP | [用 Python 写 MCP 工具总报参数错？源码与报文对照](./labs/S4-M08-mcp-jsonrpc-schema/) | `python3 labs/S4-M08-mcp-jsonrpc-schema/verify.py` |
| `S5-M05` | 💻 轻量脚本 | 🤖 智能体与 MCP | [进阶选修：基于模板补全只读本地笔记MCP并排坑](./labs/S5-M05-readonly-notes-mcp/) | `python3 labs/S5-M05-readonly-notes-mcp/verify.py` |
### Ch.7 评测优化与上线：评测驱动迭代（Evals）、性能优化与生产安全上线（9 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与标题 | 一键验收命令 |
|---|---|---|---|---|
| `S0-M08` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [怕被提示注入套话或刷爆额度？上线前硬兜底安全排查](./labs/S0-M08-prelaunch-safety-gate/) | `python3 labs/S0-M08-prelaunch-safety-gate/verify.py` |
| `S6-M01` 🌟 | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [改提示词崩老功能？用 promptfoo 搭自动回归闸门](./labs/S6-M01-ci-eval-gate/) | `python3 labs/S6-M01-ci-eval-gate/verify.py` |
| `S6-M02` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [AI 偶发卡顿答错难排查？用 Langfuse 串联链路 Trace](./labs/S6-M02-trace-span-analyzer/) | `python3 labs/S6-M02-trace-span-analyzer/verify.py` |
| `S6-M03` | 🌱 零代码 | 🛡️ 评测与安全上线 | [AI 裁判总偏心长答案？用二元核对单校准](./labs/S6-M03-binary-judge-calib/) | `python3 labs/S6-M03-binary-judge-calib/verify.py` |
| `S6-M04` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [Agent 改提示词就乱提交？装 Skill 搭防退化闸门](./labs/S6-M04-prompt-pr-guard-skill/) | `python3 labs/S6-M04-prompt-pr-guard-skill/verify.py` |
| `S6-M05` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [模型报错账单飙？基于 LiteLLM 封装网关](./labs/S6-M05-fallback-llm-gateway/) | `python3 labs/S6-M05-fallback-llm-gateway/verify.py` |
| `S6-M06` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [上线怕漏 Key 或刷爆账单？攻防自检堵漏洞](./labs/S6-M06-key-leak-and-ratelimit/) | `python3 labs/S6-M06-key-leak-and-ratelimit/verify.py` |
| `S6-M07` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [AI 质检爱瞎挑刺或漏坑？测出真实检出与误报率](./labs/S6-M07-precision-recall-eval/) | `python3 labs/S6-M07-precision-recall-eval/verify.py` |
| `S6-M08` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [模型日志算不清账？套 OTel 拆解延迟与缓存](./labs/S6-M08-otel-latency-cost/) | `python3 labs/S6-M08-otel-latency-cost/verify.py` |

---

## 🛠️ 全仓批量自检命令

```bash
# 验证全部 66 个实验的标准参考实现 (solution.*) 100% 通过验收
python3 scripts/verify_all_labs.py --solution

# 完整双重审计（确认全部 starter 处于红灯挑战态 + 全部 solution 绿灯通关）
python3 scripts/verify_all_labs.py --audit-both
```
