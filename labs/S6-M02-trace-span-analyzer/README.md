# S6-M02 AI 偶发卡顿答错难排查？用 Langfuse 串联链路 Trace

## 场景与痛点
当 AI 应用包含知识库检索、外部工具调用与大模型生成等多步链路时，普通零散打印日志会带来三大盲区：
- 偶发超时或答非所问时，无法还原同一次请求里究竟是检索超时、空召回硬编还是参数解析报错；
- 最终回答碰巧正确，后台却对同一个天气/汇率接口重复调用了三四次，白白浪费数倍延迟与费用；
- 未做前置脱敏就把用户手机号、邮箱与明文 ID 上报到云端可观测面板，造成隐私合规风险。

## 目录资源说明
- `fixtures/sample_multistep_request.json`：包含 2 条典型多步请求原始事件（1 条含手机号/邮箱敏感信息的正常多步请求，1 条最终状态为 `ok` 但内部重复调用 3 次 `get_weather` 的隐性异常请求）。
- `fixtures/abnormal_traces.jsonl`：**24 条异常链路样本**（涵盖重复调工具、慢检索超时、空召回幻觉、工具参数解析失败 4 类典型线上问题，跨 `v2.1` / `v2.2` 两个提示词版本）。
- `starter.py`：待完善的链路脱敏、轨迹检查与坏例归因骨架。
- `solution.py`：完整标准实现（支持 Langfuse 风格 Trace/Span 组装、PII 掩码与用户 ID 哈希、重复工具调用轨迹拦截、24 条坏例归因排序与种子回归集导出）。
- `verify.py`：自动化红绿验收脚本（零第三方依赖）。

## Vibe Coding 一键启动口令
将下面这句话直接粘贴给 Cursor / Claude Code / Windsurf：

> 请阅读 @labs/S6-M02-trace-span-analyzer/README.md 与 fixtures/ 日志，按根目录 AGENTS.md 协议带我改进 starter.py 并跑通 verify.py 全部链路验收。

## 动手步骤
1. **运行红灯基线**：执行 `python3 verify.py`，查看当前 `starter.py` 在链路脱敏、重复调工具拦截与坏例归因上的 4 项待修复提示。
2. **串联多步 Span 并前置脱敏**：在 `scrub_pii` 与 `build_sanitized_trace` 中对 11 位手机号、邮箱做掩码脱敏，对 `user_id` 做单向哈希（保留聚合能力且不暴露身份），将检索、工具、模型步骤组装到同一 `trace_id` 下并记录耗时与 Token。
3. **编写轨迹异常检查器**：在 `audit_trace_trajectory` 中按工具名称统计单次请求调用次数，只要同一工具调用 `> 1` 次即标记 `"duplicate_tool_call"` 并判定不通过（即使 `status == "ok"`）。
4. **20+ 坏例贴标排序与种子导出**：在 `triage_abnormal_traces` 中统计 `fixtures/abnormal_traces.jsonl` 的错因分布，按样本数降序提取前 3 类根因、计算各版本 P95 延迟，并将典型坏例脱敏导出为 JSONL 回归种子集。

## 验收命令
```bash
# 验收当前 starter.py 改进进度（初始状态预期为 FAIL 退出码 1）
python3 labs/S6-M02-trace-span-analyzer/verify.py

# 验证标准参考实现 solution.py（预期 100% PASS 退出码 0）
python3 labs/S6-M02-trace-span-analyzer/verify.py --solution
```
