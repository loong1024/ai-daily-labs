# S6-M01 改提示词崩老功能？搭电商客服退赔黄金回归闸门

<!-- SCENARIO_HEADER_START -->
## 🎬 场景与能力拆解概览

| 👤 真实客户痛点现场 | 📍 用在什么业务场景 | 🎯 要实现的核心能力 |
| :--- | :--- | :--- |
| 电商客服与审单工具负责人每次为修一处客户反馈微调提示词，手试两三条就裸发上线，结果把残缺单追问和防套话骗退规则全改崩，陷入“修一处崩五处”泥潭。 | 用在智能售后发版与 CI 准入环节，输入 20 条含常规查单、遮挡缺单号残缺单、大额转人工与伪造系统指令骗退单的真实回归样本。 | 搭建锁死模型快照与零温的自动回归闸门，用规则断言兜底分流字段、二元评审严查工单摘要忠实度，退化自动阻断并支持秒回滚基线。 |

- **核心能力积木**：`B12 黄金回归考卷 + 全链路账本 + 网关降级` · `B06 原生 JSON Schema + 缺证据拒答锁` · `B09 入口轻重分级路由 + 多路并行/硬关卡`
- **推荐实现链路**：沉淀 20 条含残缺单与骗退单的黄金样本 → 锁死模型日期快照与零温参数 → 配齐 JSON 确定性断言与工单摘要二元核查 → 并排跑通 v1/v2 对比基线 → 接入 CI 退化阻断闸门并配置一键回滚指针
- **头号避坑红线**：拿两三条顺风局样例手测通过就全量覆盖旧提示词，或把订单号、金额等确定性字段全丢给主观大模型打分，既漏拦骗退单又找不回稳定旧版。
<!-- SCENARIO_HEADER_END -->


## 场景与痛点
维护日均数千单的电商智能客服与退赔审单工具时，最怕陷入**“按下葫芦浮起瓢”**的死循环：
- 为了让小额退款更快，顺手精简了一句提示词，结果手试 3 条常规单全过，一上线却把**漏单号的残缺单**直接放行退款，甚至被**伪造系统指令与冒充总监口令的恶意套话骗退单**打穿风控；
- 把订单号、退赔金额、路由动作等确定性字段全扔给主观评审模型打 1–10 分，既慢又飘忽不定；
- 缺少自动化 CI 回归准入与一键回滚开关，改坏提示词直接覆盖线上环境。

## 目录资源说明
- `fixtures/order_triage_cases.json`：开箱即用的 **20 条电商售后黄金回归样本**（涵盖 4 条常规物流发票查单、4 条 ≤200 元合规小额自动退赔、4 条漏单号/遮挡打码/缺金额凭证的残缺单、4 条大额/专票/定制生鲜升级人工单、4 条伪造指令与黑产套话骗退单）。
- `prompts/triage_v1.txt`：稳定生产基线提示词（完整锁死五档分流边界、缺单号标 `MISSING`、骗退拦截归零及摘要零脑补约束）。
- `prompts/triage_v2_broken.txt`：故意改坏的激进退化草稿（删掉残缺单追问与防骗退规则，遇退钱一律秒批，还在工单摘要里私自脑补赠送 50 元无门槛券承诺）。
- `prompts/triage_v2.txt`：修复后的正式候选版提示词（完整保留五档风控红线并优化工单摘要凝练度）。
- `starter.yaml`：残缺的 Promptfoo 回归配置（仅 3 条顺风局样例、浮动模型别名与 `temperature: 0.7`、滥用 `llm-rubric`、指向退化提示词且未开启 CI 阻断与回滚）。
- `solution.yaml`：生产级 Promptfoo 黄金回归与 CI 阻断门禁配置（可直接用于 `npx promptfoo@latest eval -c solution.yaml`）。
- `verify.py`：纯标准库 YAML 解析与离线/在线三模自适应回归门禁验收器。

## Vibe Coding 一键启动口令
将下面这句话直接粘贴给 Cursor / Claude Code / Windsurf：

> 请阅读 @labs/S6-M01-ci-eval-gate/README.md 与 fixtures/ 样本，按 AGENTS.md 协议带我完善 starter.yaml 回归配置并运行 python3 labs/S6-M01-ci-eval-gate/verify.py 直至全绿。

## 动手步骤
1. **查看初始退化诊断**：运行 `python3 verify.py`，观察 `starter.yaml` 在边界覆盖、断言分层与退化拦截上的红灯报告。
2. **锁定模型快照与 20 条黄金题库**：在 `providers` 中锁死带日期模型快照（如 `openai:chat:gpt-4o-mini-2024-07-18`）与 `temperature: 0`，并将 `fixtures/order_triage_cases.json` 的 20 条真实售后样本全部纳入 `tests`。
3. **实施断言分层纪律**：20 条用例统一用 `is-json` + `javascript` 精确校验 `order_id`、`intent`、`action`、`refund_amount`；仅对 4 条复杂升级人工工单补充 `llm-rubric` 审查 `summary` 是否忠实无脑补赔偿。
4. **开启 CI 阻断闸门与秒级回滚**：将候选提示词切换为修复后的 `file://prompts/triage_v2.txt`（保留 `triage_v1.txt` 并排对照），在 `ci_gate` 中启用 `block_on_regression: true`、`min_pass_rate: 0.95` 与 `rollback_prompt: file://prompts/triage_v1.txt`。
5. **可选本地可视化对比**：若本地安装了 Node.js 并配置了 `OPENAI_API_KEY`，可运行 `npx promptfoo@latest eval -c solution.yaml` 与 `npx promptfoo@latest view` 查看新旧版本逐条差异。

## 验收命令
```bash
# 验收当前 starter.yaml 配置（初始状态预期为 FAIL 退出码 1）
python3 labs/S6-M01-ci-eval-gate/verify.py

# 验证标准参考配置 solution.yaml（预期 100% PASS 退出码 0）
python3 labs/S6-M01-ci-eval-gate/verify.py --solution
```
