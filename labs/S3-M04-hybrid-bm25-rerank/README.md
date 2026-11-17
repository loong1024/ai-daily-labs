# S3-M04 · 报错码总漏召回？混合检索与中文重排实测

> **所属章节**：Ch.4 私域知识库 RAG · **门槛**：手把手原型实现 · **预计耗时**：40 分钟

## 1. 场景痛点
纯稠密向量检索擅长同义词泛化，但遇到精确报错码（如 `ERR-4091-LOCK`）、硬件型号（`HX-920B`）或冷门参数名时常排到 20 名开外。通过 **字面分词 BM25 + 稠密向量 RRF 倒数秩融合 + 交叉特征精排（Rerank）** 即可兼顾语义与精确命中。

## 2. Vibe Coding 一键开练口令
```text
请阅读 @labs/S3-M04-hybrid-bm25-rerank/README.md 与 fixtures/eval_corpus.json，按根目录 AGENTS.md 结对教练协议，补全 starter.py 中的中文+代号分词 BM25、RRF 双路融合与轻量精排函数，运行 python3 labs/S3-M04-hybrid-bm25-rerank/verify.py 验收通过。
```
