# S1-M06 · 资料塞满却总答偏？大篇幅“中间遗忘”与前缀缓存实测

> **所属章节**：Ch.3 长文档与结构化 API · **门槛**：轻量脚本 · **预计耗时**：35 分钟

## 1. 场景痛点
长文档问答中把几十段检索结果一股脑塞进上下文后，模型常漏看排在中间的关键修订条款（Lost-in-the-Middle），且每次把变动问题拼在最前面导致静态长前缀缓存（Prompt Caching）全部失效。

## 2. Vibe Coding 一键开练口令
```text
请阅读 @labs/S1-M06-lost-in-middle/README.md 与 fixtures/probe_docs.json，按根目录 AGENTS.md 结对教练协议，帮我完善 starter.py 中的上下文去噪首尾重排与静态前缀构造逻辑，并运行 python3 labs/S1-M06-lost-in-middle/verify.py 验收通过。
```

## 3. 本目录实用资源
- `fixtures/probe_docs.json`：含新旧冲突条款、关键证据与大量无关噪音段落的评测探针集。
- `starter.py`：朴素拼接基线（未去噪、把高相关证据埋在中间、动态时间戳放首行破坏缓存）。
- `solution.py`：标准参考实现（过滤低分噪音、高置信最新证据排布首尾、固定 ≥1500 字符静态前缀）。
- `verify.py`：红绿自动裁判（`python3 verify.py` 测当前进度，`python3 verify.py --solution` 测标准答案）。
