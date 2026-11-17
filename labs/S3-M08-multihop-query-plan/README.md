# S3-M08 · 多轮追问总是搜偏？查询路由与结构化规划

> **所属章节**：Ch.4 私域知识库 RAG · 搭建高可信私域知识库与检索增强（RAG）  
> **实验类型**：`prompt` + 白盒检索路由工程 | **预计耗时**：55 分钟

## 1. 场景与常见痛点

在企业私域知识库的多轮问答中，如果把用户的原话直接扔进向量库或全文检索，经常遇到三类典型翻车：

1. **指代缺失导致搜偏**：用户追问“那它的超时怎么配？”，由于原句不含上文主语 `UpstreamPool`，检索器被“超时怎么配”吸到前端 Toast 弹窗文档。
2. **闲聊与格式指令硬查库**：遇到“你好，谢谢！把上面那句话翻成英文”也照常触发检索，既浪费延迟又把无关客服话术切片塞进上下文。
3. **精确报错码与时效边界丢失**：`ERR_502_TIMEOUT`、`check_keepalive_idle` 被分词器拆碎或小写化；“对比去年和今年的方案”“今年最新规范”没有转化为结构化日期过滤与正交子查询，导致已废弃的旧版归档排在第一。

## 2. 实验目标

升级查询规划提示词与检索路由脚本，打通以下四步闭环：
- **`need_retrieval` 门禁路由**：识别闲聊、致谢与纯上文翻译/格式指令，直接跳过检索（触发次数为 `0`）。
- **`standalone_query` 与 `sub_queries` 拆解**：结合对话历史还原指代主语；遇到跨年份/多对象对比拆成 2–3 条正交子查询。
- **`exact_terms` 零篡改精确分流**：原样提取报错码、函数名与配置项（保留大小写与下划线），显式送入精确关键词检索通道。
- **`time_filter` 元数据过滤 + 并行 RRF 融合**：输出 `{"after": "YYYY-MM-DD", "before": "YYYY-MM-DD"}` 在元数据层拦截过期归档，并对多路检索结果做 Reciprocal Rank Fusion（RRF）融合排序。

## 3. 本目录文件说明

- `fixtures/kb_chunks.json`：10 条脱敏网关与向量平台知识库切片（含 2023/2024 历史归档干扰项、前端同名配置噪声项、精确故障码排障手册）。
- `fixtures/dialog_cases.json`：5 组典型多轮对话测试集（指代追问、报错码排障、跨年方案对比、今年最新规范、闲聊致谢）。
- `starter.py`：基线版实现（直拿原话做朴素双字切分检索，无闲聊跳过、无精确词路由与时间过滤）。
- `solution.py`：完整参考实现（含结构化查询规划提示词、`chat_complete` 三模调用、精确词 BM25 通道、元数据时间过滤与并行 RRF）。
- `verify.py`：自动化红绿验收脚本。

## 4. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf：

```text
请阅读 @labs/S3-M08-multihop-query-plan/README.md 与 fixtures/，按 AGENTS.md 带我改进 starter.py 并运行 python3 labs/S3-M08-multihop-query-plan/verify.py 直到全部通过。
```

## 5. 动手步骤指引

1. **复现基线翻车**：运行 `python3 starter.py` 或 `python3 verify.py`，观察 5 组多轮输入在原话直搜下的搜偏、旧文档污染与无效查库现象。
2. **升级查询规划契约**：完善 `starter.py` 中的 `PLANNER_SYSTEM_PROMPT` 与 `build_query_plan()`，严格输出 `need_retrieval`、`standalone_query`、`exact_terms`、`sub_queries` 与 `time_filter`。
3. **校验规划字段保真**：确保 `ERR_502_TIMEOUT` 与 `check_keepalive_idle` 大小写和下划线零篡改，跨年对比题拆分为 2 条年度子查询，闲聊题 `need_retrieval=false` 且 `sub_queries=[]`。
4. **打通多路检索与 RRF**：在 `execute_routed_search()` 中先拦截无需检索请求，再执行 `time_filter` 元数据过滤，随后将 `standalone_query`、`sub_queries` 与 `exact_terms` 精确检索结果通过 RRF（`k=60`）合并。
5. **免代码平替（可选）**：若不写代码，可直接复制 `solution.py` 中的 `PLANNER_SYSTEM_PROMPT` 与 `fixtures/dialog_cases.json` 到网页版大模型，人工核对输出的 JSON 路由字段。

## 6. 量化验收命令

```bash
# 验收当前 starter.py 修改进度（初始为红灯提示，改完后应全绿通过）
python3 labs/S3-M08-multihop-query-plan/verify.py

# 对照检查标准参考实现（应 100% 通过）
python3 labs/S3-M08-multihop-query-plan/verify.py --solution
```
