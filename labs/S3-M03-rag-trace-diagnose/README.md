# S3-M03 · RAG 五层取证排障：Trace 归因与单变量修复

> **所属章节**：Ch.4 私域知识库 RAG · **门槛**：Skill 技能封装 / 轻量脚本 · **预计耗时**：35 分钟

## 1. 场景痛点
线上 RAG 答非所问时，团队常凭感觉盲目换更大的生成模型或乱调 chunk_size，其实故障可能出在 **入库解析、查询改写、粗召回、重排截断、生成忠实度** 五层中的任意一层。

## 2. Vibe Coding 一键开练口令
```text
请阅读 @labs/S3-M03-rag-trace-diagnose/README.md 与 fixtures/rag_traces.json，按根目录 AGENTS.md 结对教练协议，补全 starter.py 中的五层证据链诊断器与缺失真值追问逻辑，运行 python3 labs/S3-M03-rag-trace-diagnose/verify.py 验收通过。
```
