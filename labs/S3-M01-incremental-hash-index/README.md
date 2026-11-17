# S3-M01 · 本地笔记增量索引：哈希同步防旧块残留

> **所属章节**：Ch.4 私域知识库 RAG · **门槛**：轻量脚本 · **预计耗时**：40 分钟

## 1. 场景痛点
用本地 SQLite 索引几百篇 Markdown 笔记时，新手常直接 `INSERT` 新切片却忘了按 `doc_id` 清理旧切片，导致改完笔记后“作废旧金额/旧命令”依然残留在检索前 5 名误导回答；或者每次改动 1 篇就重算全部 500 篇的向量！

## 2. Vibe Coding 一键开练口令
```text
请阅读 @labs/S3-M01-incremental-hash-index/README.md 与 fixtures/notes_state.json，按根目录 AGENTS.md 结对教练协议，补全 starter.py 中基于 SHA-256 的原子增量同步与删稿级联清理逻辑，运行 python3 labs/S3-M01-incremental-hash-index/verify.py 验收通过。
```
