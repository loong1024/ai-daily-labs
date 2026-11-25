# AI 日课 · 48 个精选高代入感真实场景实验总仓 (`ai-daily-labs`)

> 本仓内容来自 AI 日课 App——完整课程与讲解在 App Store 搜索 AI日课。

[![Verify All 48 Labs](https://github.com/loong1024/ai-daily-labs/actions/workflows/verify-labs.yml/badge.svg)](https://github.com/loong1024/ai-daily-labs/actions/workflows/verify-labs.yml)
[![Open in GitHub Codespaces](https://img.shields.io/badge/GitHub_Codespaces-一键云端免装开练-181717?logo=github)](https://codespaces.new/loong1024/ai-daily-labs)
[![AI 日课在线教程](https://img.shields.io/badge/AI_日课_v3.0-五步场景假设驱动实战平台-0f766e)](https://ai-daily-dot-leonxingexp-sandbox-396955.uc.r.appspot.com/#/materials)

本仓库是 **[AI 日课 · 通用 AI 场景与假设驱动实战教程（v3.0）](https://ai-daily-dot-leonxingexp-sandbox-396955.uc.r.appspot.com/)** 的官方一站式动手实验单仓（Monorepo），完整收录 **`Ch.0 → Ch.7` 八大章节 × 每章 6 个 = 48 个精选高代入感真实场景实验**。

经过 v3.0 去水提纯与去玩具化重构，全部 **48 个实验** 100% 锚定真实职场、企业业务与工程防线痛点（涵盖**八大行业立项红线沙盘、采购合同对照红线自动初审、销售会议转写稿商机提纯、海量用户差评 VoC 批次预警、Vibe Coding 经营交互看板、工业跨页参数表混合检索、`n8n` 竞品情报去重告警、安全 ReAct 智能体与 `promptfoo` 电商客服黄金回归闸门**等）。

每个实验子目录 `labs/<ID>-<slug>/` 均内置：
- **`fixtures/`**：真实脱敏业务/工程脏数据靶场样本（残缺合同、口水话纪要、跨页表格、注入报文等）；
- **`starter.*`**：故意留有典型新手缺陷的待改造起点文件（默认运行 `verify.py` 呈红灯诊断态）；
- **`solution.*`**：遵循 `B00–B12` 核心能力积木构建的标准参考实现（运行 `verify.py --solution` 100% 绿灯通关）；
- **`verify.py`**：仅依赖 Python 标准库与 `shared/aid_lab.py` 的确定性红绿自动验收裁判脚本。

---

## ⚡ 快速上手指南（离线零 API Key 即开即跑 + Vibe Coding 一键导入）

### 方式一：`git clone` 克隆总仓 + 离线零 API Key 默认运行（最推荐）

本仓库内置确定性离线回放层（`shared/aid_lab.py`，自动启用 `AID_FORCE_MOCK=1`），**无需申请或配置任何大模型 API Key、无需安装臃肿第三方包**，仅凭 Python 3.10+ 标准库即可在本地 5 秒跑通全部 48 个实验的验收逻辑：

```bash
# 1. 克隆实验总仓
git clone https://github.com/loong1024/ai-daily-labs.git
cd ai-daily-labs

# 2. 离线零 API Key 一键验证全部 48 个实验的标准参考实现 (solution.*) 100% 绿灯通过
python3 scripts/verify_all_labs.py --solution

# 3. 运行双向红绿闯关完整性审计（同时确认 48 个 starter 呈红灯待改诊断态 + 48 个 solution 绿灯通关）
python3 scripts/verify_all_labs.py --audit-both

# 4. 单独进入任意实验体验「先红灯诊断 → 动手改造 starter → 绿灯通关」
python3 labs/S1-M09-contract-redline-audit/verify.py             # 查看未改造前的红灯缺陷诊断
python3 labs/S1-M09-contract-redline-audit/verify.py --solution  # 对照验证标准参考答案
```

### 方式二：在 Cursor / Claude Code / Windsurf 中一键导入结对闯关

用 **Cursor、Claude Code、Windsurf、VS Code Copilot、Gemini CLI 或 Trae** 打开克隆后的 `ai-daily-labs` 根目录。仓库根目录已内置 **[AGENTS.md](./AGENTS.md) 结对教练协议**（自动遵循先跑基线诊断、引导小步修改 `starter.*`、不剧透直接拿 `solution.*` 覆盖）。

直接在 AI 编程工具对话框粘贴以下口令（或从 [AI 日课分类实验中心 `#/materials`](https://ai-daily-dot-leonxingexp-sandbox-396955.uc.r.appspot.com/#/materials) 任意实验卡片一键复制专属口令）：

```text
请阅读 @labs/S1-M09-contract-redline-audit/README.md 与 fixtures/ 合同样本，按根目录 AGENTS.md 结对教练协议，先运行 verify.py 查看当前 starter 漏掉了哪些合同暗坑与空白项，再带我一步步改造 starter 文件，直到运行 python3 labs/S1-M09-contract-redline-audit/verify.py 全部绿灯通过！
```

### 方式三：GitHub Codespaces 云端零安装开练 / 单实验拉取 / 切换真实模型

1. **浏览器免装直跑（Codespaces）**：点击 **[👉 在 GitHub Codespaces 打开本仓库](https://codespaces.new/loong1024/ai-daily-labs)**，云端容器已预装 Python 环境，打开终端即可直接运行 `verify.py` 或配合 Copilot 练习。
2. **只拉取单个实验子目录**：
   ```bash
   npx degit loong1024/ai-daily-labs/labs/S5-M09-expense-dashboard my-vibe-lab
   cd my-vibe-lab
   ```
3. **无缝切换真实云端 / 本地大模型实测（可选）**：复制根目录 `.env.example` 为 `.env`（已被 `.gitignore` 保护），按注释填入任意 OpenAI 兼容接口环境变量（`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`）或本地 Ollama 模型名（`OLLAMA_MODEL`），即可从离线回放无缝切换至真实模型调用。

---

## 🎯 v3.0 实验设计亮点：与线上「五步场景假设驱动闭环」无缝咬合

1. **三栏鲜活现场 + `B00–B12` 能力积木拆解**：每个实验 `README.md` 顶部均同步展示「真实角色与痛点现场 ｜ 适用业务场景与原始样本 ｜ 要实现的核心能力」、关联能力积木编号、标准推荐实现链路与头号避坑红线。
2. **前两章（`Ch.0–Ch.1`）100% 纯零代码友好**：共 **18+ 个零代码（🌱）实验**分布在各章关键决策点，非技术背景同学只需修改自然语言提示词、核查清单或单页指令即可跑通 `verify.py` 验收。
3. **Red → Green 确定性自动裁判**：告别“改完不知道好没好”，每次修改都有客观脚本即时反馈漏判项、格式错误或越权漏洞。

---

## 🌟 高共鸣王牌与精选必做代表实验（快速体验通道）

| 实验 ID | 章节 | 门槛 | 核心场景亮点 | 实验目录直达 | 本地验收命令 |
|---|---|---|---|---|---|
| `P0-M07` 🌟 | `Ch.0` | 🌱 零代码 | **【v3.0 新增】** 10 条跨部门 AI 提议：速赢、人工兜底与高危禁区分拣沙盘 | [P0-M07-industry-redline-sandbox](./labs/P0-M07-industry-redline-sandbox/) | `python3 labs/P0-M07-industry-redline-sandbox/verify.py` |
| `S0-M09` 🌟 | `Ch.1` | 🌱 零代码 | 告别空洞套话：六要素结构化提问 + 少样本样板改写对照 | [S0-M09-six-element-prompt](./labs/S0-M09-six-element-prompt/) | `python3 labs/S0-M09-six-element-prompt/verify.py` |
| `S5-M09` 🌟 | `Ch.2` | 🌱 零代码 | **【v3.0 重塑】** 零代码 15 分钟生成经营收支与目标追踪交互看板 | [S5-M09-expense-dashboard](./labs/S5-M09-expense-dashboard/) | `python3 labs/S5-M09-expense-dashboard/verify.py` |
| `S1-M09` 🌟 | `Ch.3` | 🌱 零代码 | **【v3.0 新增】** 采购合同对照法务红线初审：XML 隔离与缺据标 `UNKNOWN` | [S1-M09-contract-redline-audit](./labs/S1-M09-contract-redline-audit/) | `python3 labs/S1-M09-contract-redline-audit/verify.py` |
| `S1-M10` | `Ch.3` | 💻 脚本 | **【v3.0 新增】** 45 分钟销售会议转写稿提纯：商机五要素与客户原话时间戳核验 | [S1-M10-meeting-crm-extractor](./labs/S1-M10-meeting-crm-extractor/) | `python3 labs/S1-M10-meeting-crm-extractor/verify.py` |
| `S0-M11` 🌟 | `Ch.3` | 💻 脚本 | **【v3.0 新增】** 多渠道海量用户差评（VoC）逐条低温打标与批次质量暴雷预警 | [S0-M11-voc-batch-cluster](./labs/S0-M11-voc-batch-cluster/) | `python3 labs/S0-M11-voc-batch-cluster/verify.py` |
| `S3-M04` | `Ch.4` | 💻 脚本 | **【v3.0 重塑】** 工业近似型号（`GX-904B`）与报错码：`BM25 + 向量`混合重排 | [S3-M04-hybrid-bm25-rerank](./labs/S3-M04-hybrid-bm25-rerank/) | `python3 labs/S3-M04-hybrid-bm25-rerank/verify.py` |
| `S2-M01` 🌟 | `Ch.5` | 💻 脚本 | **【v3.0 重塑】** 竞品动态与行业异动情报流：轻量 `n8n` 定时去重与即时告警 | [S2-M01-n8n-dedup-alert](./labs/S2-M01-n8n-dedup-alert/) | `python3 labs/S2-M01-n8n-dedup-alert/verify.py` |
| `S4-M02` 🌟 | `Ch.6` | 💻 脚本 | 根治 Agent 死循环烧钱与假装成功：手写最小安全 ReAct 闭环与熔断 | [S4-M02-safe-react-loop](./labs/S4-M02-safe-react-loop/) | `python3 labs/S4-M02-safe-react-loop/verify.py` |
| `S6-M01` 🌟 | `Ch.7` | 💻 脚本 | **【v3.0 重塑】** 电商客服改提示词就崩？用 `promptfoo` 搭退赔分级黄金回归闸门 | [S6-M01-ci-eval-gate](./labs/S6-M01-ci-eval-gate/) | `python3 labs/S6-M01-ci-eval-gate/verify.py` |

---

## 📚 8 大章节 × 每章 6 个 = 48 个精选场景实验全景导览（`Ch.0 → Ch.7`）

### Ch.0 通识与行业全景：AI 核心术语导学与各行业应用全景（6 个实验 · 全零代码）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `P0-M01` 🌟 | 🌱 零代码 | 💬 提问与核查 | [看懂开源 AI 全家桶：文档转 Markdown 与工作台](./labs/P0-M01-doc-to-markdown/) | `python3 labs/P0-M01-doc-to-markdown/verify.py` |
| `P0-M02` 🌟 | 🌱 零代码 | 💬 提问与核查 | [任务拆解四象限：揪出个人前 3 个高收益 AI 提效点](./labs/P0-M02-task-quadrant/) | `python3 labs/P0-M02-task-quadrant/verify.py` |
| `P0-M03` | 🌱 零代码 | 💬 提问与核查 | [同一问题跑三遍：裸聊记忆、贴原文开卷与思考模式对比](./labs/P0-M03-three-modes-compare/) | `python3 labs/P0-M03-three-modes-compare/verify.py` |
| `P0-M04` | 🌱 零代码 | 🛡️ 评测与安全上线 | [严谨场景防翻车：AI 初稿外发前 5 项人工签字核查单](./labs/P0-M04-signoff-checklist/) | `python3 labs/P0-M04-signoff-checklist/verify.py` |
| `P0-M06` | 🌱 零代码 | 🤖 智能体与 MCP | [选型决策演练：Prompt、知识库、工作流与 Agent](./labs/P0-M06-paradigm-selector/) | `python3 labs/P0-M06-paradigm-selector/verify.py` |
| `P0-M07` 🌟 | 🌱 零代码 | 💬 提问与核查 | [八大行业 AI 提效立项沙盘：高收益切入点与高危红线分拣实战](./labs/P0-M07-industry-redline-sandbox/) | `python3 labs/P0-M07-industry-redline-sandbox/verify.py` |

### Ch.1 提问与日常提效：结构化提问、写作润色与信息核实（6 个实验 · 全零代码）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S0-M03` 🌟 | 🌱 零代码 | 💬 提问与核查 | [AI 写稿怕夹带假数据？原子主张拆解与交叉核查](./labs/S0-M03-fact-claim-verify/) | `python3 labs/S0-M03-fact-claim-verify/verify.py` |
| `S0-M06` | 🌱 零代码 | 💬 提问与核查 | [AI 图文准备对外发或商用？20 分钟发布前避坑自查](./labs/S0-M06-publish-compliance/) | `python3 labs/S0-M06-publish-compliance/verify.py` |
| `S0-M09` 🌟 | 🌱 零代码 | 💬 提问与核查 | [随口提问总拿套话？六要素 + 样板改写对照实验](./labs/S0-M09-six-element-prompt/) | `python3 labs/S0-M09-six-element-prompt/verify.py` |
| `S0-M10` | 🌱 零代码 | 💬 提问与核查 | [发截图读表总串行、怕泄密？看图纠错与脱敏实测](./labs/S0-M10-vision-table-redact/) | `python3 labs/S0-M10-vision-table-redact/verify.py` |
| `S1-M03` | 🌱 零代码 | 💬 提问与核查 | [重大业务立项防顺从吹捧：多立场独立盲写与红蓝挑刺压力测试](./labs/S1-M03-anti-sycophancy/) | `python3 labs/S1-M03-anti-sycophancy/verify.py` |
| `S1-M08` | 🌱 零代码 | 💬 提问与核查 | [B2B 供应商与技术方案二选一：双盲位置互换 + 事前验尸评审](./labs/S1-M08-double-blind-ab/) | `python3 labs/S1-M08-double-blind-ab/verify.py` |

### Ch.2 Vibe Coding 造物：自然语言造工具与 AI 协同开发（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S5-M09` 🌟 | 🌱 零代码 | 🎨 Vibe Coding 造物 | [零代码 15 分钟造交互网页：经营收支与目标追踪看板](./labs/S5-M09-expense-dashboard/) | `python3 labs/S5-M09-expense-dashboard/verify.py` |
| `S5-M10` 🌟 | 🌱 零代码 | 🎨 Vibe Coding 造物 | [告别手工贴表：定制 CSV 与 Excel 合并清洗小工具](./labs/S5-M10-csv-batch-cleaner/) | `python3 labs/S5-M10-csv-batch-cleaner/verify.py` |
| `S5-M01` 🌟 | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [规则总不生效？45 分钟配通多工具 1 页纸 `AGENTS.md` 规则文件](./labs/S5-M01-agents-md-rules/) | `python3 labs/S5-M01-agents-md-rules/verify.py` |
| `S5-M02` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [AI 修 Bug 总盲改？复现优先 `SKILL.md` 与降噪脚本实战](./labs/S5-M02-repro-first-skill/) | `python3 labs/S5-M02-repro-first-skill/verify.py` |
| `S5-M03` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [拒绝 AI 一把梭改乱千行：Spec 先行与小步 TDD 实验](./labs/S5-M03-spec-driven-tdd/) | `python3 labs/S5-M03-spec-driven-tdd/verify.py` |
| `S5-M04` | 💻 轻量脚本 | 🎨 Vibe Coding 造物 | [口头禁令总失灵？90 分钟搭建两道硬护栏与绕过攻防](./labs/S5-M04-precommit-hooks/) | `python3 labs/S5-M04-precommit-hooks/verify.py` |

### Ch.3 长文档与结构化 API：长报告精读、合同初审与批量数据抽取（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S1-M09` 🌟 | 🌱 零代码 | 📊 长文与抽表格 | [采购与商业合同初审排雷：XML 隔离、缺据标 `UNKNOWN` 与审批表直写](./labs/S1-M09-contract-redline-audit/) | `python3 labs/S1-M09-contract-redline-audit/verify.py` |
| `S1-M05` 🌟 | 🌱 零代码 | 📊 长文与抽表格 | [长稿总结总漏后半段？Map-Reduce 分块提炼与覆盖率核对实战](./labs/S1-M05-mapreduce-coverage/) | `python3 labs/S1-M05-mapreduce-coverage/verify.py` |
| `S1-M02` 🌟 | 💻 轻量脚本 | 📊 长文与抽表格 | [JSON 总报错还瞎猜？用 Instructor / `JSON Schema` 锁死结构化抽取](./labs/S1-M02-json-schema-extract/) | `python3 labs/S1-M02-json-schema-extract/verify.py` |
| `S1-M10` | 💻 轻量脚本 | 📊 长文与抽表格 | [销售与项目会议转写稿提纯：商机五要素抽取与客户原话时间戳硬核验](./labs/S1-M10-meeting-crm-extractor/) | `python3 labs/S1-M10-meeting-crm-extractor/verify.py` |
| `S0-M11` 🌟 | 💻 轻量脚本 | 📊 长文与抽表格 | [多渠道海量用户差评吐槽（VoC）归因：逐条低温打标与批次质量暴雷预警](./labs/S0-M11-voc-batch-cluster/) | `python3 labs/S0-M11-voc-batch-cluster/verify.py` |
| `S0-M07` | 💻 轻量脚本 | 📊 长文与抽表格 | [千条反馈和长文怎么跑最省？80 行 Python 成本模拟器](./labs/S0-M07-cost-simulator/) | `python3 labs/S0-M07-cost-simulator/verify.py` |

### Ch.4 私域知识库 RAG：搭建高可信私域知识库与检索增强（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S3-M02` 🌟 | 🌱 零代码 | 🗂️ 私域知识库 RAG | [防常识混入与假引用：逐句标号与拒答闸门](./labs/S3-M02-citation-and-abstain/) | `python3 labs/S3-M02-citation-and-abstain/verify.py` |
| `S3-M06` | 🌱 零代码 | 🗂️ 私域知识库 RAG | [脏文档别直接入库！5 份硬骨头样本入库前体检](./labs/S3-M06-dirty-doc-clean/) | `python3 labs/S3-M06-dirty-doc-clean/verify.py` |
| `S3-M01` 🌟 | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [本地笔记增量索引：哈希同步防旧块残留](./labs/S3-M01-incremental-hash-index/) | `python3 labs/S3-M01-incremental-hash-index/verify.py` |
| `S3-M04` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [近似型号与报错码漏召回？混合检索与重排实测](./labs/S3-M04-hybrid-bm25-rerank/) | `python3 labs/S3-M04-hybrid-bm25-rerank/verify.py` |
| `S3-M05` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [拒绝凭感觉调参：建 30 题双层回归评测基线](./labs/S3-M05-rag-eval-baseline/) | `python3 labs/S3-M05-rag-eval-baseline/verify.py` |
| `S3-M08` | 💻 轻量脚本 | 🗂️ 私域知识库 RAG | [多轮追问总是搜偏？查询路由与结构化规划](./labs/S3-M08-multihop-query-plan/) | `python3 labs/S3-M08-multihop-query-plan/verify.py` |

### Ch.5 自动化 AI 工作流：确定性工作流编排与无人值守自动化（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S2-M06` | 🌱 零代码 | ⚡ 自动工作流 | [零代码自动化一上线就翻车？通用上线体检表与三招无代码排雷](./labs/S2-M06-nocode-launch-check/) | `python3 labs/S2-M06-nocode-launch-check/verify.py` |
| `S2-M01` 🌟 | 💻 轻量脚本 | ⚡ 自动工作流 | [竞品动态与行业异动情报流：轻量 `n8n` 定时去重与告警](./labs/S2-M01-n8n-dedup-alert/) | `python3 labs/S2-M01-n8n-dedup-alert/verify.py` |
| `S2-M02` | 💻 轻量脚本 | ⚡ 自动工作流 | [单一提示硬跑又慢又贵？四种工作流模式同题 10 样本基准测](./labs/S2-M02-workflow-patterns-bench/) | `python3 labs/S2-M02-workflow-patterns-bench/verify.py` |
| `S2-M03` | 💻 轻量脚本 | ⚡ 自动工作流 | [AI 抽取总乱编格式还怕提示注入？20 样本批量校验与防注入实验](./labs/S2-M03-batch-schema-anti-inject/) | `python3 labs/S2-M03-batch-schema-anti-inject/verify.py` |
| `S2-M05` | 💻 轻量脚本 | ⚡ 自动工作流 | [群发周报怕重发、503 卡死或超支？幂等退避、审批与熔断演练](./labs/S2-M05-idempotent-backoff-hitl/) | `python3 labs/S2-M05-idempotent-backoff-hitl/verify.py` |
| `S2-M08` | 💻 轻量脚本 | ⚡ 自动工作流 | [百条批处理断电就从头烧钱？手写断点续跑、限速与容错尾行骨架](./labs/S2-M08-checkpoint-batch-runner/) | `python3 labs/S2-M08-checkpoint-batch-runner/verify.py` |

### Ch.6 自主智能体 Agent：四大设计模式、MCP 生态与安全沙箱（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S4-M04` | 🌱 零代码 | 🤖 智能体与 MCP | [长任务 Agent 计划全废还瞎改？探针重规划提示词实测](./labs/S4-M04-probe-replan-agent/) | `python3 labs/S4-M04-probe-replan-agent/verify.py` |
| `S4-M06` | 🌱 零代码 | 🤖 智能体与 MCP | [盲目上多 Agent 越拆越慢？单双架构对比与 A2A 取舍实验](./labs/S4-M06-single-vs-multi-agent/) | `python3 labs/S4-M06-single-vs-multi-agent/verify.py` |
| `S4-M02` 🌟 | 💻 轻量脚本 | 🤖 智能体与 MCP | [Agent 死循环烧钱还假装成功？手写最小安全闭环对照测](./labs/S4-M02-safe-react-loop/) | `python3 labs/S4-M02-safe-react-loop/verify.py` |
| `S4-M01` | 💻 轻量脚本 | 🤖 智能体与 MCP | [换客户端就要重写工具接口？用 Inspector 拆解标准 MCP](./labs/S4-M01-mcp-protocol-inspector/) | `python3 labs/S4-M01-mcp-protocol-inspector/verify.py` |
| `S4-M05` | 💻 轻量脚本 | 🤖 智能体与 MCP | [个人助理记混旧信息还被网页投毒？造可过期防污染记忆层](./labs/S4-M05-anti-poison-memory/) | `python3 labs/S4-M05-anti-poison-memory/verify.py` |
| `S4-M07` | 💻 轻量脚本 | 🤖 智能体与 MCP | [让 Agent 夜间无人值守怕删库泄密？四道物理边界安全压测](./labs/S4-M07-agent-sandbox-redteam/) | `python3 labs/S4-M07-agent-sandbox-redteam/verify.py` |

### Ch.7 评测优化与上线：评测驱动迭代（Evals）、网关容灾与生产安全上线（6 个实验）

| 实验 ID | 门槛 | 专题分类 | 实验目录与真实场景标题 | 本地一键验收命令 |
|---|---|---|---|---|
| `S6-M03` | 🌱 零代码 | 🛡️ 评测与安全上线 | [AI 裁判总偏心长答案？用二元核对单校准](./labs/S6-M03-binary-judge-calib/) | `python3 labs/S6-M03-binary-judge-calib/verify.py` |
| `S6-M01` 🌟 | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [电商客服改提示词就崩？搭退赔分级黄金回归闸门](./labs/S6-M01-ci-eval-gate/) | `python3 labs/S6-M01-ci-eval-gate/verify.py` |
| `S6-M02` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [AI 偶发卡顿答错难排查？用 `Langfuse` 串联链路 Trace](./labs/S6-M02-trace-span-analyzer/) | `python3 labs/S6-M02-trace-span-analyzer/verify.py` |
| `S6-M05` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [模型报错账单飙？基于 `LiteLLM` 封装网关](./labs/S6-M05-fallback-llm-gateway/) | `python3 labs/S6-M05-fallback-llm-gateway/verify.py` |
| `S6-M06` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [上线怕漏 Key 或刷爆账单？攻防自检堵漏洞](./labs/S6-M06-key-leak-and-ratelimit/) | `python3 labs/S6-M06-key-leak-and-ratelimit/verify.py` |
| `S6-M07` | 💻 轻量脚本 | 🛡️ 评测与安全上线 | [AI 质检爱瞎挑刺或漏坑？测出真实检出与误报率](./labs/S6-M07-precision-recall-eval/) | `python3 labs/S6-M07-precision-recall-eval/verify.py` |

---

## 🛠️ 全仓自动化质量门禁（CI / 本地自检）

```bash
# 离线零 API Key 并发验证全部 48 个实验的标准参考实现 (solution.*) 100% 绿灯通过
python3 scripts/verify_all_labs.py --solution

# 完整双向红绿审计（验证全部 48 个 starter 呈红灯待完成提示且无异常栈 + 全部 48 个 solution 绿灯通过）
python3 scripts/verify_all_labs.py --audit-both
```
