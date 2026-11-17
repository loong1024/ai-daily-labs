# S2-M08：百条批处理断电就从头烧钱？手写断点续跑、限速与容错尾行骨架

## 场景与痛点
批量调用大模型处理数百条工单时，全并发极易撞上 HTTP 429 限流，中途 `Ctrl+C` 强杀若留下半行 JSONL 会导致下次重启解析崩溃，混入一两条空内容坏数据（毒丸）更会让整批任务前功尽弃。本实验基于内置 429 模拟桩与 30 条测试样本（含 2 条毒丸），构建高可靠异步批处理骨架。

## 目录资源
- `fixtures/batch_inputs.jsonl`：30 条待摘要工单样本（其中 `rec-011` 与 `rec-024` 为内容缺失的必报错毒丸）。
- `starter.py`：含并发失控、缺退避重试、半行解析崩溃与缺死信隔离缺陷的基线骨架。
- `solution.py`：完整实现 SHA-256 幂等键、`Semaphore(5)`、指数退避加抖动、残缺尾行自愈与 `dlq.jsonl` 隔离的参考方案。
- `verify.py`：覆盖并发峰值、429 自愈、半行续跑零重跑与死信隔离的四项量化验收脚本。

## Vibe Coding 一键开练口令
> 请阅读 `@labs/S2-M08-checkpoint-batch-runner/README.md` 与 `starter.py`，补全并发限速、断点续跑与死信隔离，运行 `python3 labs/S2-M08-checkpoint-batch-runner/verify.py` 直到通过。

## 实操步骤
1. **SHA-256 幂等键**：在 `compute_item_key` 中组合 `id`、`prompt_version` 与 `content` 计算 64 位十六进制指纹。
2. **并发限速与 429 退避**：用 `asyncio.Semaphore(max_concurrency)` 将在途任务锁在 5 以内，对 `RateLimitError` 做最多 3 次带随机抖动的指数退避。
3. **耐半行崩溃断点续跑**：启动扫描 `outputs.jsonl` 时用 `try/except json.JSONDecodeError` 跳过并清理残缺尾行，每次成功落盘立即 `flush()`。
4. **死信隔离**：将不可恢复的毒丸样本及重试耗尽条目连同报错原因写入 `dlq.jsonl`，确保其余 28 条正常完成。

## 验收命令
```bash
python3 verify.py            # 验收当前 starter.py 进度
python3 verify.py --solution # 验收 solution.py 标准参考实现
```
