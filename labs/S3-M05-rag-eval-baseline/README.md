# S3-M05 拒绝凭感觉调参：建 30 题双层回归评测基线

> **所属章节**：Ch.4 私域知识库 RAG · 搭建高可信私域知识库与检索增强（RAG）  
> **实验类型**：白盒 Python 工程骨架包 | **预计耗时**：80 分钟

## 1. 场景痛点与实验目标

在迭代私域知识库时，很多团队每次改完切片大小（如从 `500` 字改到 `1500` 字）或微调系统提示词后，只挑两三个顺眼问题试问一下就匆忙上线，结果经常踩进三大深坑：

1. **按下葫芦浮起瓢**：修好了一道跨段总结题，却让大量精准数字题和故障码题的召回率悄悄暴跌。
2. **拒答题污染生成均值**：把库外“无答案拒答题”混进普通问答一起算 `Response Relevancy`（答案相关性），模型老实回答“知识库未收录”反而被判 0 分，拉低整体均值甚至导致除零报错。
3. **检索与生成糊成一团**：端到端答错时，分不清到底是检索没捞到正确切片（该调切分/混合检索），还是捞到了切片但模型瞎编（该调提示词/温度）。

**本实验目标**：基于统一的 **30 题黄金评测集（25 道有答案题 + 5 道无答案拒答题）**，搭建一套零第三方硬依赖的一键双层回归评测脚本：
- **检索层（确定性代码计算）**：仅针对 25 道有答案题计算透明的 `Recall@5` 与 `MRR`；
- **生成层与拒答层剥离**：对 25 道有答案题调用轻量裁判模型（支持 `shared.aid_lab.chat_complete` 三模切换）评估 `Faithfulness`（忠实度）与 `Response Relevancy`（答案相关性）；将 5 道无答案题剥离后单独统计 `Refusal Accuracy`（拒答准确率）；
- **10 题人工抽检校准 + 单变量回归对照**：与人工标注样本对齐校准裁判尺子，并对比 `chunk_500` 基线与 `chunk_1500` 实验组的指标波动。

---

## 2. 目录文件说明

- `fixtures/eval_dataset_30.json`：30 题企业研发与行政制度知识库评测集（`Q01`–`Q25` 为有标准出处与答案的必答题，`Q26`–`Q30` 为库外无答案拒答题；同时附带 `chunk_500` 基线与 `chunk_1500` 大切片实验组两组检索与生成记录）。
- `fixtures/human_audit_10.json`：人工随机抽检的 10 条核验记录（含人工通过判定与偏差备注，用于校准自动裁判尺子）。
- `starter.py`：待修复的评测脚本骨架（存在把拒答题混入分母、只看 Top-1 漏算 MRR、缺少人工校准与单变量对比等典型缺陷）。
- `solution.py`：高可读性标准参考实现（零第三方依赖，兼容真实 API / Ollama / 离线确定性裁判）。
- `verify.py`：自动化红绿验收脚本。

---

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf：

```text
请阅读 @labs/S3-M05-rag-eval-baseline/README.md 与 fixtures/，按 AGENTS.md 教练协议改进 starter.py，运行 python3 labs/S3-M05-rag-eval-baseline/verify.py 直至通过。
```

---

## 4. 动手步骤指引

1. **查看 30 题测试集结构**：打开 `fixtures/eval_dataset_30.json`，观察 `unanswerable` 字段如何区分 25 道库内有答案题与 5 道库外无答案题。
2. **修复检索层指标 (`compute_retrieval_metrics`)**：过滤出 `not item["unanswerable"]` 的 25 道题，精确计算 `recall_at_5`（前 5 个切片命中 `gold_chunk_id` 的比例）与 `mrr`（首个命中位置倒数 `1 / rank` 的均值）。
3. **剥离无答案题并实现裁判打分 (`evaluate_rag_run`)**：
   - 完善 `is_refusal_answer` 拒答语义规则；
   - 对 25 道有答案题调用 `judge_generation_item` 计算 `faithfulness` 与 `response_relevancy`；
   - 对 5 道无答案题**单独统计** `refusal_accuracy`，严禁混入 `response_relevancy` 分母。
4. **对齐 10 题人工抽检 (`calibrate_judge_alignment`)**：将自动判定结果与 `fixtures/human_audit_10.json` 逐条比对，输出一致率 `agreement_rate`、平均偏差 `mean_bias` 及分歧题号列表 `discrepant_ids`。
5. **生成单变量对照报告 (`compare_configs`)**：对比 `chunk_500` 基线与 `chunk_1500` 实验组，自动识别检索退步并输出结构化 `baseline.json` 兼容字典。

> **免代码平替方案**：若暂不写代码，可直接新建一张 15–30 题电子表格（列：`问题 | 标准出处 | 是否无答案题 | 检索找对 | 回答忠实 | 最终答对`），每次调完知识库切分参数后人工抽测打钩对比，同样切记把“无答案拒答题”单列统计。

---

## 5. 验收命令

```bash
# 检查当前 starter.py 修复进度（初始状态会提示待改进项，退出码为 1）
python3 labs/S3-M05-rag-eval-baseline/verify.py

# 验证标准参考答案 solution.py（全部指标全绿通过，退出码为 0）
python3 labs/S3-M05-rag-eval-baseline/verify.py --solution
```
