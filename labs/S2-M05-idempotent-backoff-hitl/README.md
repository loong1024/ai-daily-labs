# S2-M05：群发周报怕重发、503 卡死或超支？幂等退避、审批与熔断演练

> **所属章节**：Ch.5 自动化 AI 工作流 · 确定性 AI 工作流编排与无人值守自动化  
> **实验类型**：`idea` | **专题**：`workflow` | **预计耗时**：90 分钟

---

## 1. 场景痛点与实验目标

独立开发者或小团队搭建自动化周报生成与群发流水线时，最容易在以下三个坑里翻车：

1. **半途超时重跑导致重复轰炸**：第 6 个订户超时报错后重跑脚本，前 5 个已成功收信的订户又收到第二封一模一样的周报。
2. **503 死磕或错误重试烧穿额度**：遇到 `400` 无效邮箱也盲目重试，遇到持续 `503` 无退避死循环，既没有死信落盘也没有单期预算硬熔断。
3. **无公网域名导致人工审批悬空**：想加一道“人看一眼点确认再群发”，本地脚本没公网回调地址就干脆省掉审批，或者超时后错误地“默认自动发出”。

**实验目标**：在本地零外部依赖（纯 Python 标准库 + SQLite）完成两阶段工程加固，并通过 **四合一破坏性演练**：
- **Part A（幂等、退避死信与预算硬熔断）**：基于 SQLite 建立 `(issue_id, subscriber_id)` 唯一幂等约束；区分可重试错误（`429`/`5xx`/`TIMEOUT`，按 $2^n$ 秒加随机抖动最多重试 4 次）与不可重试错误（`400`/`401`，0 次重试直接跳过）；重试耗尽落入 `dead_letters` 死信表并提供 `replay_dead_letters` 仅补发失败者入口；记录每次 LLM 调用费用并实现单期预算硬熔断与草稿质量关卡重写。
- **Part B（免公网穿透一次性鉴权审批与 30 秒超时中止）**：实现本地一次性随机审批令牌（支持本地轻量回调确认与 CLI/API 审批队列），确保令牌 **点过即失效（防重放）**，且审批超时（演练模式设为 **30 秒**）后 **默认中止发送（绝不自动发出）**。

> 💡 **免代码平替提示**：非开发同学可用“飞书多维表格（以 `期号+邮箱` 建防重唯一索引）+ 飞书自动化审批节点”搭同款流程：推送群卡片审批，测试期将超时阈值设为 30 秒验证自动取消发送，并同步在模型平台锁死月度用量告警。

---

## 2. 本目录文件说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验背景、两阶段架构指引与四合一演练说明 |
| `fixtures/subscribers.json` | 8 位模拟订阅者（覆盖正常收信、偶发 503/429 后恢复、持续 503/超时进死信、400 无效地址不可重试） |
| `fixtures/issue_context.json` | `2026-W20` 期周报素材、时区配置、草稿关卡规则与模型单次调用计费参数 |
| `starter.py` | 起点基线流水线（无幂等防重、盲目无退避重试、审批超时错误自动群发、无预算熔断） |
| `solution.py` | 标准参考实现（含 SQLite 幂等表、抖动退避、死信补发、预算熔断、一次性审批令牌与本地 HTTP 确认器） |
| `verify.py` | 四合一破坏性演练验收脚本（注入虚拟时钟与退避探测器，秒级完成 30 秒超时与退避曲线验真） |

---

## 3. Vibe Coding 一键开练口令

将下面这段口令直接粘贴给 Cursor / Claude Code / Windsurf 等 AI 编程助手即可开启结对演练：

```text
请阅读 @labs/S2-M05-idempotent-backoff-hitl/README.md 与 fixtures/，按 AGENTS.md 结对教练协议带我改进 starter.py，运行 python3 verify.py 直至全部验收通过。
```

---

## 4. 实操步骤指引

1. **Part A-1：建立 SQLite 幂等表与死信队列**  
   在 `starter.py` 的 `_init_db` 中为 `send_logs` 增加 `UNIQUE(issue_id, subscriber_id)` 唯一约束，并创建 `dead_letters` 表。发送前先查 `send_logs`，状态为 `sent` 的订户直接跳过（并将幂等键 `f"{issue_id}:{subscriber_id}"` 一并传给邮件网关）。
2. **Part A-2：错误分级、带抖动指数退避与仅补发死信**  
   - 遇到 `429`、`500`/`502`/`503`/`504` 或 `TIMEOUT` 时，按 `2 ** attempt + jitter`（`attempt` 从 1 到 4，共最多重试 4 次）调用 `self.sleep_fn(delay)` 退避重试；重试耗尽仍失败者写入 `dead_letters` 并追加高优告警到 `self.alerts`；
   - 遇到 `400`/`401`/`403` 等请求或地址错误，**0 次重试**直接记为 `skipped_invalid`；
   - 实现 `replay_dead_letters(issue_id)`：只读取该期 `dead_letters` 中的待补发订户重新投递，成功后从死信表移除并更新 `send_logs`。
3. **Part A-3：草稿质量关卡与单期预算硬熔断**  
   - 每次调用 LLM 前后向 `cost_ledger` 记账，一旦当期累计花费超过 `max_budget_usd` 阈值，立即中止流程（返回 `status="aborted_budget"`）并记录高优告警；
   - 检查生成的周报草稿（字数达标、链接为 `https://`、不含未替换的 `{{...}}` 占位符），不通过则附带原因最多重写 2 次。
4. **Part B：本地一次性鉴权审批与 30 秒超时演练**  
   - 生成带随机 `appr_` 前缀的一次性令牌存入 `approvals` 表，记录 `expires_at = clock_fn() + timeout_seconds`；
   - `approve_issue(issue_id, token)` 校验令牌匹配、未过期且 `used == 0`，通过后立即置 `used = 1`（第二次使用同一令牌必须返回 `False`）；
   - `dispatch_issue(issue_id)` 发送前核验审批状态：若未审批或当前时间已超过 `expires_at`，立即将审批单置为 `expired`、返回 `status="expired_aborted"` 且一封邮件都不发！

---

## 5. 验收命令

在实验目录（`labs/S2-M05-idempotent-backoff-hitl/`）下执行：

```bash
# 运行四合一破坏性演练，验收你当前修改的 starter.py
python3 verify.py

# 验证标准参考答案 solution.py
python3 verify.py --solution
```
