# S0-M11 · 多渠道海量用户差评吐槽（VoC）归因：逐条低温打标与批次质量暴雷预警

<!-- SCENARIO_HEADER_START -->
## 🎬 场景与能力拆解概览

| 💥 真实开发翻车现场 | 🔍 触发问题的工程时机 | 🛡️ 要练成的核心防线 |
| :--- | :--- | :--- |
| 消费硬件与电商团队每周收到多语种杂乱差评，过去整包塞进聊天窗问“大家抱怨啥”，AI 只盯末尾几条包装小事瞎总结，漏掉新批次断连暴雷。 | 每周多渠道用户之声（VoC）质量监控环节，输入含中英双语、多平台及批次号线索的 30 条真实感差评样本（见 fixtures）。 | 用低温（temperature=0）逐条提取机型、故障部件与批次 JSON 入库，再靠 Python 确定性环比统计提前揪出 B111 批次蓝牙缺陷。 |

- **核心能力积木**：`B06 原生 JSON Schema + 缺证据拒答锁` · `B05 上下文提纯分块 + 静态前缀缓存`
- **推荐实现链路**：逐条读取多渠道 JSONL 差评 → 固定 temperature=0 与枚举 Schema 独立抽取机型/故障部件/批次（无批次标 UNKNOWN） → Python 确定性汇总双周环比增幅 → 自动触发异常批次质量预警简报
- **头号避坑红线**：把几十上百条差评一次性拼成超长文本让大模型直接写周报并心算占比，既被末尾评论带偏漏掉中段暴雷簇，又在高温采样下标签漂移。
<!-- SCENARIO_HEADER_END -->


> **所属章节**：Ch.3 长文档与结构化 API · 长报告精读、模型 API 调用与批量表格抽取  
> **预计耗时**：45 分钟 ｜ **实验类型**：可运行 Python 批处理工程实验（支持云端 API / 本地 Ollama / 离线零 Key 回放）

## 1. 真实业务痛点

消费硬件与跨境电商团队每周都会从京东、天猫、小红书、Amazon US、Reddit 等多渠道收回几百条中英混杂的用户差评（Voice of Customer, VoC）。新手最常踩三大坑：

1. **整包塞进聊天窗问“大家抱怨啥”（近因偏差漏报暴雷）**：把几十条差评拼成一大段丢给模型写总结，模型注意力会高度偏向末尾最后几条无关痛痒的“快递外盒压痕、硅胶耳塞偏硬”，反而把夹在中段的新固件批次 `B111` 集中蓝牙断连事故漏得一干二净！
2. **高温采样且不锁枚举（标签五花八门没法统计）**：默认 `temperature=0.8~0.9` 下，同一故障一会儿叫 `"蓝牙老断"`、一会儿叫 `"Bluetooth unstable"`，下游根本无法按字段稳定聚合；遇到没写批次号的评论还会顺口编出假批次号。
3. **让大模型心算环比百分比**：概率接龙模型不擅长精确分组计数，归因打标交给低温 LLM，周环比计数与阈值告警必须交给确定性 Python 代码！

## 2. 目录文件说明

- `fixtures/voc_reviews_30.jsonl`：开箱即用的 30 条跨渠道（京东、天猫、小红书、Amazon US、Reddit、App Store）中英文用户差评，包含 `W1` 基线周（15 条）与 `W2` 监控周（15 条，中段潜伏 `AeroBuds Pro` 新批次 `B111` 蓝牙断连暴雷簇，末尾故意放置包装与耳塞常规小吐槽测试近因偏差）。
- `starter.py`：待修复的基线脚本（存在 `temperature=0.9` 高温漂移、缺少枚举与 `UNKNOWN` 约束、整包单次投喂漏读中段、未实现 Python 环比聚合与简报渲染）。
- `solution.py`：标准参考实现（逐条 `temperature=0.0` 结构化 JSON 打标 + 确定性 `Counter` 环比暴雷检测 + Markdown 预警简报）。
- `verify.py`：一键红绿闭环量化验收脚本。

## 3. Vibe Coding 一键开练口令

```text
请阅读 @labs/S0-M11-voc-batch-cluster/README.md 与 fixtures/voc_reviews_30.jsonl，按根目录 AGENTS.md 结对教练协议带我完善 starter.py 的逐条低温打标与批次暴雷统计，运行 python3 labs/S0-M11-voc-batch-cluster/verify.py 直至通过。
```

> **本地开源模型扩展**：若已安装 [Ollama](https://github.com/ollama/ollama)，只需设置环境变量 `OLLAMA_MODEL=qwen2.5:3b`（或任意轻量指令模型）即可用本地模型真实跑通全部 30 条中英差评打标！

## 4. 验收命令

```bash
# 1) 检查当前 starter.py 进度（未修改前返回红灯诊断提示，退出码 1）
AID_FORCE_MOCK=1 python3 labs/S0-M11-voc-batch-cluster/verify.py

# 2) 验证标准参考实现 solution.py（4 项指标 100% 通过，退出码 0）
AID_FORCE_MOCK=1 python3 labs/S0-M11-voc-batch-cluster/verify.py --solution
```
