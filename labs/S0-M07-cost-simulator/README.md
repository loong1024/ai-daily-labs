# S0-M07 · 千条反馈和长文怎么跑最省？80 行 Python 成本模拟器

> **所属章节**：Ch.3 长文档与结构化 API · 长报告精读、模型 API 调用与批量表格抽取  
> **预计耗时**：30 分钟 ｜ **实验类型**：白盒 Python 工程骨架包

## 1. 场景痛点

在启动 2000 条用户反馈抽表或百页长报告批处理之前，拍脑袋直接调实时 API 往往会多花 5–10 倍冤枉钱：

1. **误以为短前缀也能吃上缓存折扣**：每条请求都拼上系统规则与样例前缀，却不知道主流平台要求固定前缀 **$\ge 1024$ Token** 才触发自动前缀缓存（Prompt Caching）；前缀只有 800 Token 时其实条条都在按全价计费。
2. **忽视高价输出与思考 Token 的放大效应**：主流模型的输出（含推理/思考链 Token）单价通常是输入单价的 **4 倍**（如输入 `$2/1M` vs 输出 `$8/1M`），让模型每条多写 200 个解释性废话 Token，总账单直接翻倍。
3. **离线任务白白错过 Batch API 半价通道**：明明第二天早上看结果就够的批量抽表任务，仍然走实时同步接口全价跑，错失异步 Batch API 的 5 折优惠。

## 2. 目录文件说明

- `README.md`：计费公式契约、四种省钱策略说明与验收命令
- `fixtures/pricing_scenarios.json`：两档模型价格表（旗舰推理档 vs 轻量高性价比档，含不同缓存叠加规则）与 6 组典型批处理负载场景（含 `800 / 1023 / 1024 / 1200` 前缀边界与 `300 -> 80` 输出压缩对照）
- `starter.py`：待修复的成本模拟器起点代码（缺少 `>= 1024` 缓存触发门槛校验、漏算高价输出单价、未完成策略 B/D 与完整 Markdown 账单表）
- `solution.py`：约 95 行零依赖纯 Python `dataclasses` 标准实现
- `verify.py`：手算级精度对账与边界条件自动化验收脚本

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf 助手即可结对完成：

```text
请阅读 @labs/S0-M07-cost-simulator/README.md 与 fixtures/，按 AGENTS.md 带我完善 starter.py，运行 python3 labs/S0-M07-cost-simulator/verify.py 直至通过。
```

> **免代码平替**：不想写代码时，可用 Excel 建一张 4 行公式表，将 `任务条数 × (固定前缀 + 变动输入)` 与 `任务条数 × 输出长度` 分别乘以实时全价、`IF(前缀>=1024, 缓存价, 原价)` 以及异步 Batch 0.5 折扣系数，10 分钟拉出对比柱状图。

## 4. 四种策略精确计费口径（与手算对账完全一致）

设任务条数为 $N$（`task_count`），固定系统前缀为 $P$（`prefix_tokens`），单条变动文本为 $V$（`variable_input_tokens`），单条输出（含思考）为 $O$（`output_tokens`），紧凑输出保留比例为 $r$（`compact_output_ratio`，默认 `0.5`）：

- **缓存门槛判断**：仅当 `P >= pricing.cache_min_prefix_tokens`（默认 `1024`）时 `cache_triggered = True`，否则 `False`（800 或 1023 Token 前缀均按未命中缓存原价计算！）。
- **策略 A（`A_realtime_full` · 实时全价基线）**：
  - 输入费用 = $N \times (P + V) / 10^6 \times \text{input\_per\_1m}$
  - 输出费用 = $N \times O / 10^6 \times \text{output\_per\_1m}$
  - 缓存节省 = `0.0`
- **策略 B（`B_compact_output` · 精简输出字段与思考）**：
  - 输入费用与策略 A 相同；输出长度压缩为 $O \times r$，输出费用 = $N \times (O \times r) / 10^6 \times \text{output\_per\_1m}$；缓存节省 = `0.0`。
- **策略 C（`C_prefix_cache` · 前缀缓存实时调用）**：
  - 若 `cache_triggered` 为真，前缀部分按 `cached_input_per_1m` 计费，变动输入仍按 `input_per_1m` 计费；缓存节省 = $N \times P / 10^6 \times (\text{input\_per\_1m} - \text{cached\_input\_per\_1m})$。若未达门槛，费用与策略 A 完全一致，缓存节省为 `0.0`。
- **策略 D（`D_cache_plus_batch` · 前缀缓存 + Batch API 异步通道）**：
  - 常规 Batch 输入单价 `batch_in = input_per_1m * batch_discount_factor`，Batch 输出单价 `batch_out = output_per_1m * batch_discount_factor`。
  - 若 `cache_triggered` 为真：当厂商允许折上折（`stack_batch_on_cache=True`）时，前缀单价为 `cached_input_per_1m * batch_discount_factor`；否则取 `min(cached_input_per_1m, batch_in)`。缓存节省（相对纯 Batch 无缓存）= $N \times P / 10^6 \times \max(0, \text{batch\_in} - \text{d\_prefix\_rate})$。

## 5. 验收命令

```bash
# 1) 检查当前 starter.py 进度（未修改前返回红灯提示，退出码 1）
python3 labs/S0-M07-cost-simulator/verify.py

# 2) 验证标准参考实现 solution.py（手算对账与门槛测试 100% 通过，退出码 0）
python3 labs/S0-M07-cost-simulator/verify.py --solution
```
