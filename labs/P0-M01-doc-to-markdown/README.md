# P0-M01 · 看懂开源 AI 全家桶：文档转 Markdown 与工作台

> **所属章节**：Ch.0 通识与行业全景 · AI 核心术语导学与各行业应用全景  
> **实验类型**：GitHub 开源导读 + 白盒清洗实测 ｜ **零代码友好**：是 ｜ **预计耗时**：15 分钟

---

## 1. 场景需求与常见痛点

日常向主流大模型对话助手投喂带排版的办公文档（Word、PDF、Excel、PPT）时，常因视觉样式、页眉水印与复杂制表符干扰导致模型漏读数据。本实验带你拆解开源社区两大高星项目——**`microsoft/markitdown`**（前置净菜工）与 **`open-webui/open-webui`**（中央操作台）的上下游配合逻辑，并亲手验证“先转结构化 Markdown 再投喂问答”的准确率差异。

### 三大高频痛点
1. **表格错行与漏读**：直接把排版复杂的办公文档复制丢给主流大模型，常出现表格列错位、标题层级丢失与关键卡点数据漏读。
2. **对高星开源项目发怵**：看到 GitHub 高星仓库误以为必须写复杂代码才能理解，忽略了它们解决的核心业务分工。
3. **忽视前置格式净化**：不清楚为什么进阶使用者总强调先把杂乱资料转成 Markdown（`#` 标题 + `|` 竖线表格），再挂载进统一对话工作台。

---

## 2. 开源 AI 全家桶双核拆解

| 组件角色 | 代表开源项目 | 所在层级 | 核心解决痛点 |
| --- | --- | --- | --- |
| **前置净菜工** | `microsoft/markitdown` | 文档预处理层 | 剥离 PDF/Word/Excel/PPT 中的视觉样式、页眉页脚与水印，提炼出保留层级关系的 `#` 标题、`-` 列表与 `\|` 竖线表格，降低格式噪声与上下文窗口损耗。 |
| **中央操作台** | `open-webui/open-webui` | 交互工作台层 | 统一连接主流商业大模型与本地 Ollama 开源权重模型，支持将清洗好的 Markdown 文档挂载为团队知识库，并沉淀高频提示词预设模板。 |

---

## 3. 本目录资源说明

- `README.md`：本实验说明、免代码浏览器走读步骤与验收指南。
- `fixtures/raw_quarterly_review.txt`：从办公文档直接复制出的杂乱季度复盘原稿（含页眉页脚、机密水印、全角空格与制表符伪表格）。
- `fixtures/messy_office_docs.json`：5 份跨部门脱敏办公脏文本语料、6 项开源工具链核心能力卡片与问答核对基准。
- `starter.py`：待改进的半成品流水线基线（尚未剥离办公噪声、未还原竖线表格、混淆了上下游工具职责）。
- `solution.py`：零第三方依赖的标准参考实现（完整模拟文档净化、上下游职责映射与 `chat_complete` 问答准确度对比）。
- `verify.py`：自动化量化验收脚本（支持离线确定性 Mock 30 秒验证，也支持配置 `.env` 接入真实模型实测）。

---

## 4. Vibe Coding 一键启动口令

在 Cursor / Claude Code / Windsurf / GitHub Codespaces 对话框中直接粘贴以下口令：

```text
请阅读 @labs/P0-M01-doc-to-markdown/README.md 与 fixtures/，按根目录 AGENTS.md 教练协议带我改进 starter.py，运行 python3 labs/P0-M01-doc-to-markdown/verify.py 直到验收通过。
```

---

## 5. 实操步骤指引

### 方式 A：Vibe Coding 结对闯关（推荐）
1. **先看红灯基线**：运行下方验收命令，观察未修改的 `starter.py` 在哪几项指标上亮红灯。
2. **走读脏语料**：打开 `fixtures/raw_quarterly_review.txt`，直观对比杂乱页眉水印、制表符表格与干净 Markdown 的区别。
3. **分步改进 `starter.py`**：
   - 在 `clean_office_to_markdown` 中过滤页眉页脚、页码与机密水印，把 `文档标题：`、`一、...`、`●` 及 `[表格开始]...[表格结束]` 分别还原为 `#`、`##`、`-` 和标准 `| --- |` 竖线表格；
   - 在 `classify_toolchain_capabilities` 中准确区分 `markitdown`（文档预处理层）与 `open_webui`（交互工作台层）的职责边界；
   - 在 `compare_qa_accuracy` 中传入清洗后的结构化 Markdown 完成问答对比核验。
4. **再次运行验收**：直至 5 项指标全部变绿通过！

### 方式 B：免代码浏览器平替自测
1. 浏览器访问 `microsoft/markitdown` 与 `open-webui/open-webui` 项目主页，浏览 README 说明与界面预览图，找出格式转换清单以及“多模型切换、知识库挂载、提示词预设”三大功能区。
2. 复制 `fixtures/raw_quarterly_review.txt` 的杂乱原文，参考下方骨架手动改写一段带 `#` 标题与 `|` 竖线表格的 Markdown：
   ```markdown
   # 季度复盘摘要与渠道增长诊断
   ## 核心指标
   | 渠道 | 曝光量 | 转化率 | 主要卡点 |
   | --- | --- | --- | --- |
   | 搜索广告 | 125000 | 18% | 落地页首屏加载慢（平均 4.2 秒） |
   | 私域社群 | 48000 | 31% | 人工跟进响应滞后（超 45 分钟） |
   ```
3. 在任意主流大模型网页端新建两个空白对话，分别投喂改写前杂乱文本与改写后 Markdown，要求提炼“转化率最低的两个渠道及主要卡点”，对比回答准确度并用三句话总结上下游分工。

---

## 6. 量化验收命令

在实验子目录 `labs/P0-M01-doc-to-markdown/` 下执行：

```bash
# 验收当前 starter.py 改进进度（未修改前预期红灯并给出修复提示）
python3 verify.py

# 验收标准参考实现 solution.py（预期 100% 全绿通过）
python3 verify.py --solution
```

若在仓库根目录执行：

```bash
python3 labs/P0-M01-doc-to-markdown/verify.py
python3 labs/P0-M01-doc-to-markdown/verify.py --solution
```

> **提示**：默认使用离线确定性 Mock，无需任何 API Key 即可完成验收；如需连接真实接口，可在仓库根目录 `.env` 中配置（示例占位符如 `OPENAI_API_KEY=FAKE_TEST_KEY_DO_NOT_USE_12345`，请替换为你自己的有效配置或使用本地 `OLLAMA_MODEL`）。
