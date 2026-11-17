# S6-M01 改提示词崩老功能？用 promptfoo 搭自动回归闸门

## 场景与痛点
每次优化提示词或升级模型后，靠手动复制两三条样例肉眼核对，经常遇到“新场景好看了，上周调通的退款识别和闲聊拒答却悄悄崩了”：
- 自编两三条顺风局样例永远全绿，遇到退款、拼单备注、非记账闲聊等边界输入就翻车；
- 把格式和枚举字段也交给主观评审模型打分，既费 Token 又飘忽不定；
- 缺少自动化 CI 门禁与基线回滚配置，改坏提示词直接合入主干。

## 目录资源说明
- `fixtures/bookkeeping_cases.json`：开箱即用的 **20 条记账回归测试集**（涵盖 11 条常规/小额支出、3 条退款边界、3 条多人 AA/垫付开放备注、3 条非记账拒答用例）。
- `prompts/classify_v1.txt`：稳定基线提示词（完整定义支出、退款、拒答与备注忠实约束）。
- `prompts/classify_v2_broken.txt`：故意改坏的退化版提示词（精简提示词时漏掉退款与拒答规则，并鼓励脑补扩写备注）。
- `prompts/classify_v2.txt`：修复后的迭代版提示词（保留全部确定性规则并优化备注凝练度）。
- `starter.yaml`：残缺的 Promptfoo 回归配置（仅 3 条用例、未锁定模型快照与零温、滥用 `llm-rubric`、指向退化版提示词且未开启 CI 拦截与回滚）。
- `solution.yaml`：生产级 Promptfoo 回归与 CI 门禁配置（可直接用于 `npx promptfoo@latest eval -c solution.yaml`）。
- `verify.py`：纯标准库 YAML 解析与离线/在线自适应回归门禁验收器。

## Vibe Coding 一键启动口令
将下面这句话直接粘贴给 Cursor / Claude Code / Windsurf：

> 请阅读 @labs/S6-M01-ci-eval-gate/README.md 与 fixtures/ 样本，按 AGENTS.md 协议带我完善 starter.yaml 回归配置并运行 python3 labs/S6-M01-ci-eval-gate/verify.py 直至全绿。

## 动手步骤
1. **查看初始退化报告**：运行 `python3 verify.py`，查看 `starter.yaml` 在样本覆盖、断言分层、v2 退化拦截上的红灯诊断。
2. **锁定模型快照与完整题库**：在 `providers` 中锁定带日期模型快照（如 `openai:chat:gpt-4o-mini-2024-07-18`）与 `temperature: 0`，并将 `fixtures/bookkeeping_cases.json` 的 20 条用例完整纳入 `tests`。
3. **实施断言分层纪律**：所有用例统一用 `is-json` + `javascript`（或 `contains`）做确定性字段校验；仅对多人 AA / 垫付等 3 条开放式备注质量补充 `llm-rubric` 忠实度检查。
4. **配置 CI 门禁与秒级回滚**：将候选提示词切换为修复后的 `file://prompts/classify_v2.txt`（保留 `v1` 并排对比），在 `ci_gate` 中启用 `block_on_regression: true`、`min_pass_rate: 0.95` 与 `rollback_prompt: file://prompts/classify_v1.txt`。
5. **可选本地可视化对比**：若本地安装了 Node.js 并配置了 `OPENAI_API_KEY`，可运行 `npx promptfoo@latest eval -c solution.yaml` 与 `npx promptfoo@latest view` 查看并排对比面板。

## 验收命令
```bash
# 验收当前 starter.yaml 配置（初始状态预期为 FAIL 退出码 1）
python3 labs/S6-M01-ci-eval-gate/verify.py

# 验证标准参考配置 solution.yaml（预期 100% PASS 退出码 0）
python3 labs/S6-M01-ci-eval-gate/verify.py --solution
```
