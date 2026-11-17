# [S0-M01] 长文总被截断或超支？tiktoken 实测中英与代码账单

> **所属章节**：Ch.3 长文档与结构化 API · 长报告精读、模型 API 调用与批量表格抽取  
> **实验类型**：`github`（白盒 Python 工程骨架包） | **零代码友好**：否 | **预计耗时**：40 分钟

## 1. 场景需求与三大计费盲区

在批量精读企业长报告、抽取结构化 JSON 表格或做多语言摘要前，工程团队经常因为“没提前算清 Token 账”踩坑：

1. **按字数拍脑袋估算**：默认“1 个汉字 ≈ 1 个 Token”，把长篇中文报告直接塞进上下文，导致后半截关键数据被截断或接口报错。
2. **输出端带缩进裸奔**：模型输出单价往往是输入单价的 **3～4 倍**，直接返回 `indent=4` 的美化 JSON，成百上千个缩进空格与换行白白吃掉高价输出额度。
3. **跨模型沿用同一套计数经验**：只按某一种分词器估算成本，换用其他代际或其他厂商模型后，实际月度账单偏差巨大。

## 2. 本目录实验资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `fixtures/samples.json` | **500 字规模四合一对照语料与计费参数**：包含语义对齐的 ~500 字中文、英文、Python 代码、四空格缩进 JSON，以及多模型输入/输出百万 Token 单价配置。 |
| `starter.py` | **待修复工程基线**：已内置兼容真实 `tiktoken` 与离线零依赖 Byte-Level BPE 的 `load_encoding` 适配器，但核心统计、字节切片归因与月度账单函数仍停留在“按字符拍脑袋 + 不区分输入输出单价 + 未压缩 JSON”的有缺陷版本。 |
| `solution.py` | **标准参考实现**：完整实现双编码对比、`decode_single_token_bytes` 字节归因、JSON 去缩进压缩及 30 天月度账单核算。 |
| `verify.py` | **自动化红绿验收脚本**：动态加载目标模块，对四类语料、字节切片无损还原、半字 UTF-8 碎片检出与月度省钱账单执行量化断言。 |

> **零外部依赖说明**：若本地已安装 `tiktoken`（`pip install tiktoken`），`load_encoding` 会优先调用官方 `tiktoken`；若在离线或纯净标准库环境中运行，会自动启用内置确定性 Byte-Level BPE 分词器（完整支持 `.encode()` 与 `.decode_single_token_bytes()`）。

## 3. Vibe Coding 一键开练口令

```text
请阅读 @labs/S0-M01-token-budget-calc/README.md 与 fixtures/，按教练协议带我补全 starter.py 的分词实测与月度账单逻辑，运行 python3 labs/S0-M01-token-budget-calc/verify.py 直到通过。
```

## 4. 动手实践步骤

1. **实测四类 500 字样本的双编码比值（`benchmark_samples`）**：在 `starter.py` 中分别加载 `o200k_base` 与 `cl100k_base`，对 `中文`、`英文`、`代码`、`JSON` 统计真实 Token 数、计算 `Token/字符` 比值（保留两位小数），并核算与“1 字 = 1 Token”初始预测值之间的误差 `naive_diff = tokens - chars`。
2. **字节级切片归因（`inspect_token_bytes`）**：调用 `enc.decode_single_token_bytes(tid)` 逐个检查切分出的原始字节，统计：
   - **UTF-8 半字字节碎片（`partial_utf8_count`）**：单看该 Token 无法独立解码为合法 UTF-8 字符的片段（直观解释为何 `cl100k_base` 下一个汉字常拆成 2～3 个 Token）；
   - **纯空白缩进 Token（`whitespace_token_count`）** 与 **JSON 结构符号 Token（`syntax_token_count`）**。
3. **核算 30 天输入/输出差异化月度账单（`estimate_monthly_bill`）**：
   - 将带缩进的 `output_pretty_json` 解析后用 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 压缩为语义等价的紧凑 JSON；
   - 严格区分**输入原文单价（`input_price_per_1m`）**与**更高输出 JSON 单价（`output_price_per_1m`）**，按每天 `100` 篇、连续 `30` 天计算压缩前后的月度总账单与净省美金。
4. **打印完整实测报告并核对多模型差异**：直接运行 `python3 labs/S0-M01-token-budget-calc/starter.py` 查看三张实测对照表，验证切换模型前必须调用目标模型自有计数接口的工程结论。

## 5. 量化验收命令

```bash
# 检查当前 starter.py 实现进度（初始运行预期亮红灯并给出具体修复提示）
python3 labs/S0-M01-token-budget-calc/verify.py

# 验证标准参考实现 solution.py（预期全部指标 100% 通过）
python3 labs/S0-M01-token-budget-calc/verify.py --solution
```
