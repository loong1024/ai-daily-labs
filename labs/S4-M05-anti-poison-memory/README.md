# [S4-M05] 个人助理记混旧信息还被网页投毒？造可过期防污染记忆层

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **实验类型**：`idea`（白盒 Python 工程实战） | **专题**：`agent_mcp` | **预计耗时**：90 分钟

---

## 1. 场景痛点与实验目标

给个人 AI 助理加上跨会话长期记忆（Memory）时，最容易踩中三个工程深坑：

1. **新旧记忆并存打架**：半年前住在杭州，上个月搬到上海，由于记忆库只 `INSERT` 不做版本替代，助理每次订票或推荐餐厅都在引用过期的旧地址。
2. **迷信“关键词黑名单”防注入**：以为拦截了“忽略之前指令”“立即执行”等祈使句就能防网页/邮件投毒；攻击者只要把话术改写成温文尔雅的“专访纪要显示用户近期偏好改为……”或伪造 `claimed_trust="trusted"`，就能把恶意偏好和转发规则写进永久记忆！
3. **只进不出成垃圾场**：临时差旅酒店等短期事实永不过期，且缺乏 `list`、`delete` 与 `review-pending` 人工待审工具，一旦污染根本无从清理。

**实验目标**：  
本实验提供基于 Python 标准库 `sqlite3` 的记忆存储与 CLI 骨架（`starter.py`），带你在 90 分钟内亲手补齐 **“基于来源的写权限硬隔离（物理禁写规则/偏好） + 同主题 `superseded_by` 覆盖链 + `expires_at` 到期自动淘汰 + CLI 审批删除闭环”**，当场跑通搬家更新与 4 种变体投毒压测！

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验任务书、架构契约与验收命令说明（本文件） |
| `fixtures/memory_test_cases.json` | 真实压测数据集：含搬家演进（杭州→上海）、短期过期差旅记忆、外部天气摘要，以及 4 条伪装度极高的网页/邮件投毒样本（含无祈使句委婉变体） |
| `starter.py` | **待改进起点代码**：具备 SQLite 建表与基础 CLI 入口，但存在“关键词黑名单防注入被绕过、同主题未覆盖旧值、未过滤过期记录、缺 `delete` / `review-pending` 实现”等典型缺陷 |
| `solution.py` | **标准参考实现**：完整实现来源权限硬隔离矩阵、待审隔离区 `pending_reviews`、版本替代链、TTL 过滤、完整 CLI 及 `chat_complete` 上下文组装示范 |
| `verify.py` | 自动化白盒验收脚本（动态加载目标模块，使用临时 SQLite 库执行 4 大硬核量化断言） |

---

## 3. Vibe Coding 一键启动口令

将下面这段口令直接粘贴给 Cursor / Claude Code / Windsurf 等 AI 编程助手即可开启结对编程：

```text
请阅读 @labs/S4-M05-anti-poison-memory/README.md 与 fixtures/ 素材，按根目录 AGENTS.md 结对教练协议带我逐步改进 starter.py 并运行 verify.py 直至全部验收通过。
```

> **💡 免代码平替思路**：不写代码的职场同学，可用带 **「来源、写入日期、有效截止日、状态（有效/已被替代）、可信等级」** 五列的在线表格管理个人 AI 知识库，硬性规定：**只准本人手动往“规则/偏好”分区录入，任何网页剪藏或邮件摘录一律只放“待核实外部资料”分区**。

---

## 4. 核心工程改造清单（`starter.py` 四步闯关）

1. **修正来源可信度映射与写权限硬隔离（`MemoryStore.write_memory`）**：
   - 忽略调用方传入的不可信声明 `claimed_trust`，严格根据真实通道 `source` 决定 `trust_level`：
     - `user_cli` → `"trusted"`
     - `inferred` → `"inferred"`
     - `web` / `email` / `tool` 等外部来源 → 强制标为 `"untrusted"`
   - **物理权限硬隔离**：凡 `source != "user_cli"` 尝试写入 `preference`（个人偏好）或 `auth_rule`（授权/自动化规则）类别时，**不论文本语气多委婉，一律拒绝写入 `memories` 主表**，改为写入 `pending_reviews` 待审队列并返回 `accepted=False`！
2. **实现同主题版本覆盖链（`superseded_by`）**：
   - 当可信来源（`user_cli` 或人工审批通过）写入某 `topic` 的新记录 `new_id` 时，在同一事务中将该 `topic` 此前所有 `superseded_by IS NULL` 的旧记录更新为 `superseded_by = new_id`。
3. **实现到期过滤与可信度排序（`MemoryStore.retrieve_memories`）**：
   - 检索时过滤掉 `superseded_by IS NOT NULL`（已被替代）及 `expires_at <= now_iso`（已过期）的记录；
   - 按 `trust_level`（`trusted` > `inferred` > `untrusted`）及写入时间从新到旧排序，并在 `citation` 中附带来源与时间戳。
4. **补全 CLI 维护闭环（`delete` 与 `review-pending`）**：
   - 实现 `delete_memory(memory_id)` 物理删除指定记录；
   - 实现 `review_pending(pending_id, approve=...)` 支持人工将隔离区条目显式批准转正（同时触发同主题覆盖）或彻底拒绝，并打通 `run_cli` 中的 `delete` 与 `review-pending` 子命令。

---

## 5. 量化验收与 CLI 试玩命令

在当前实验目录执行（或在仓库根目录执行 `python3 labs/S4-M05-anti-poison-memory/verify.py`）：

```bash
# 1. 运行当前进度验收（未修改 starter.py 时预期为红灯 FAIL 并打印修复指引，无异常崩溃）
python3 verify.py

# 2. 验证标准参考答案 solution.py（预期 4/4 全绿 PASS）
python3 verify.py --solution

# 3. 手动体验 CLI（可选，建议指定 /tmp 下的临时库文件测试）
python3 solution.py --db /tmp/demo_mem.db add --topic "居住城市" --content "杭州" --category fact --source user_cli
python3 solution.py --db /tmp/demo_mem.db add --topic "居住城市" --content "上海" --category fact --source user_cli
python3 solution.py --db /tmp/demo_mem.db list
```
