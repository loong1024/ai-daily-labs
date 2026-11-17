# S3-M07 不装 ES 补齐关键词检索：单文件 SQLite FTS5

> **所属章节**：Ch.4 私域知识库 RAG · 搭建高可信私域知识库与检索增强（RAG）  
> **实验类型**：白盒 Python 工程骨架包 | **预计耗时**：30 分钟

## 1. 场景痛点与实验目标

纯向量检索在面对精确报错码（如 `ERR_502_UPSTREAM_RESET`）和硬件/芯片专有型号（如 `HX-900Pro`）时极易“语义漂移”排到十名开外；但很多个人或中小团队不想为了补齐关键词召回而额外部署吃内存的 Elasticsearch 后台集群。Python 标准库自带的 `sqlite3` `FTS5` 全文引擎是绝佳的单文件平替，但新手第一次上手几乎必踩三个反直觉大坑：

1. **`bm25()` 正负号排反**：SQLite FTS5 内置 `bm25()` 返回的是**负数**（越负代表越相关），误写 `ORDER BY bm25(...) DESC` 会把最匹配的文档排到倒数第一！
2. **`trigram` 中文双字词 0 命中陷阱**：启用 `tokenize='trigram'` 后，至少 3 个字符才会生成三元组索引，搜 `超时`、`权限`、`死锁` 等高频双字中文词会直接返回 `0` 条结果！
3. **缺双路融合排序**：没有把关键词精确召回与向量语义召回做 RRF（Reciprocal Rank Fusion）合并，报错码依然进不了前 3 名。

**本实验目标**：全程仅使用 **Python 标准库 `sqlite3`**（零后台服务、零第三方包），完成 FTS5 `trigram` 建表、`bm25() ASC` 正确排序、`<3` 字符中文短词 `LIKE` 兜底，以及约 **15 行 RRF 混合排序函数**。

---

## 2. 目录文件说明

- `fixtures/kb_chunks.json`：24 段真实运维与后端排障知识库笔记（涵盖精确报错码、专有硬件型号、多频次关键词对比组及双字中文核心概念）。
- `fixtures/eval_queries.json`：6 组混合检索回归测试题（含单路纯向量 Top-20 候选排名 `vector_top20`，展示纯向量在报错码与型号上的漏召回/排名靠后现象）。
- `starter.py`：待修复的 SQLite FTS5 + RRF 模块（包含 `bm25 DESC` 排反、双字中文词返回空列表、RRF 未融合直接透传向量结果 3 处典型缺陷）。
- `solution.py`：标准参考实现（纯标准库 `sqlite3`，简洁高可读）。
- `verify.py`：自动化红绿量化验收脚本。

---

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf：

```text
请阅读 @labs/S3-M07-sqlite-fts5-search/README.md 与 fixtures/，按 AGENTS.md 教练协议改进 starter.py，运行 python3 labs/S3-M07-sqlite-fts5-search/verify.py 直至通过。
```

---

## 4. 动手步骤指引

1. **检查 FTS5 建表与 `bm25()` 排序方向 (`search_keywords`)**：
   - 确认虚拟表采用 `CREATE VIRTUAL TABLE chunks_fts USING fts5(title, body, tokenize='trigram')`；
   - 将 SQL 中的 `ORDER BY bm25(chunks_fts) DESC` 修正为 `ORDER BY bm25(chunks_fts) ASC`，并用双引号安全包裹 `MATCH` 短语（如 `'"' + term.replace('"', '""') + '"'`），避免连字符 `-` 被误解析为操作符。
2. **补齐 `<3` 字符中文双字词兜底逻辑 (`search_keywords`)**：
   - 对长度 `< 3` 的查询词（如 `超时`、`权限`、`死锁`），自动走参数化 `LIKE '%词%'` 查询 `chunks_meta` 表（标题命中优先于正文命中），消除双字词 0 命中盲区。
3. **编写 15 行 RRF 混合合并函数 (`rrf_fusion` & `hybrid_search`)**：
   - 将关键词路前 20 名与向量路前 20 名按 1-based 排名累加 `score += 1.0 / (k + rank)`（默认 `k = 60`），按融合总分降序返回，确保报错码、专有型号与中文双字词稳定进入前 3 名。

> **免代码平替方案**：若无需自己开发底座，可直接使用内置“向量 + 全文检索”混合开关的桌面知识库客户端（如 Cherry Studio 或 Dify 混合检索模式），在知识库设置中勾选 RRF 重排即可。

---

## 5. 验收命令

```bash
# 检查当前 starter.py 修复进度（初始状态触发红灯提示，退出码为 1）
python3 labs/S3-M07-sqlite-fts5-search/verify.py

# 验证标准参考答案 solution.py（全部量化断言通过，退出码为 0）
python3 labs/S3-M07-sqlite-fts5-search/verify.py --solution
```
