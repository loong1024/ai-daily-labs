# [S4-M06] 盲目上多 Agent 越拆越慢？单双架构对比与 A2A 取舍实验

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **实验类型**：`doc`（架构决策沙盒 · 零代码友好） | **专题**：`agent_mcp` | **预计耗时**：75 分钟

---

## 1. 场景痛点与实验目标

不少团队在立项复杂 AI 自动化系统时，容易掉进“多智能体形式主义”陷阱：

1. **强拆强耦合任务，互相覆盖文件**：把同一个单仓 PR 里的“改代码、补单测、写发布说明”强拆给三个并行子 Agent，由于缺少完整共享上下文，函数签名与错误码对不上，甚至互相覆盖工作区文件。
2. **协议边界错配（MCP vs A2A 混用）**：给本地确定性的 `git diff`、`pytest` 硬套一层远程 A2A 服务；反过来面对跨部门不透明黑盒（如法务部开源合规审查系统），却妄想直连人家底层数据库。
3. **忽视协调税与排障灾难**：未测算多角色同步上下文带来的 4–10 倍 Token 膨胀与延迟飙升，拆完比单兵闭环更慢、更贵、更难定位故障。

**实验目标**：  
本实验提供一份真实的 **《含三大架构反模式的跟风多 Agent 立项初稿》**（`fixtures/flawed_team_proposal.md`）与量化评估标尺（`fixtures/architecture_rubric.json`），带你在 75 分钟内完成 **Anthropic vs Cognition 边界辨析、A/B 双版架构草图绘制、四维量化打分选型（含改选阈值条件）**，并亲手起草一份合规的 **A2A Agent Card**！

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验任务书、步骤指引与验收指南（本文件） |
| `fixtures/flawed_team_proposal.md` | 待纠偏业务案例：某研发效能团队《PR 变更审查与开源合规放行系统》初版跟风多 Agent 提案（内含强拆共享工作区、协议反配、零成本测算 3 处典型漏洞） |
| `fixtures/architecture_rubric.json` | 架构评审标准配置：必答理论分界点、四维评分项清单与 A2A Agent Card 必填四要素规范 |
| `starter_prompt.md` | **待改进起点文件**：盲目追捧“Agent 越多越好”的反面提示词与未完成的架构决策文档骨架 |
| `solution_prompt.md` | **标准参考实现**：防跟风双盲架构评审提示词 + A/B 双版完整架构草图 + 四维打分决策表 + 标准 A2A Agent Card JSON 草案 |
| `verify.py` | 自动化量化验收脚本（校验理论分界、A/B 双草图要素、四维 1–5 分制打分表、演进阈值条件与 Agent Card JSON 结构） |

---

## 3. Vibe Coding 一键启动口令

将下面这段口令直接粘贴给 Cursor / Claude Code / Windsurf 等 AI 编程助手即可开启结对评审：

```text
请阅读 @labs/S4-M06-single-vs-multi-agent/README.md 与 fixtures/ 素材，按根目录 AGENTS.md 结对教练协议带我逐步改进 starter_prompt.md 并运行 verify.py 直至全部验收通过。
```

> **💡 免代码平替玩法**：非技术业务或产品负责人可直接把 `starter_prompt.md` 第四部分的 **四维打分表**（子任务可解耦度、上下文共享紧密度、成本与延迟敏感度、调试排障复杂度）复制到团队飞书/Google Docs 立项文档中，用文字框图替代代码细节完成“单兵全能 vs 多岗位协办”拍板。

---

## 4. 动手步骤指引

1. **阅读待纠偏初稿并跑基线**：先读 `fixtures/flawed_team_proposal.md`，运行 `python3 verify.py` 查看 `starter_prompt.md` 缺失的核心决策要素。
2. **厘清三大理论与协议边界（第一、二部分）**：
   - 对照 Anthropic 多智能体调研经验与 Cognition《Don't Build Multi-Agents》教训，写清 **适合并行拆分** 与 **必须单兵串行（共享上下文 + 行动隐含决策）** 各至少 2 条依据；
   - 讲清 **交接（Handoff，转移会话控制权）** 与 **按契约委派（Contract Delegation，编排者保权并按输入输出契约回收结果）** 的区别；
   - 划清 **连确定性工具/数据源用 MCP**（如本地 `git diff`、`pytest`）与 **跨边界不透明黑盒智能体协办用 A2A**（如法务部独立演进的开源许可证审查 Agent，含 `input-required` 待补充输入状态说明）的界线。
3. **绘制真实项目 A/B 双版架构草图（第三部分）**：
   - **A 版**：单智能体串行闭环（本地 MCP 工具集 + 外部法务 A2A 按需协办）；
   - **B 版**：编排者 Orchestrator + 按契约隔离工作区的多智能体；
   - 在两版草图中明确标出 **共享状态** 与 **交接点/契约边界**。
4. **完成四维量化评分矩阵并设定改选阈值（第四部分）**：
   - 按 1–5 分制对 A/B 两版评估【子任务可解耦度】、【上下文共享紧密度】、【成本与延迟敏感度】、【调试排障复杂度】；
   - 给出当前单仓常规 PR 场景的选型结论，并写明 **在何种业务规模或耦合度变化下触发从 A 版改选 B 版** 的量化阈值条件。
5. **起草合规 A2A Agent Card 草案（第五部分）**：
   - 为跨部门法务开源合规智能体编写完整 JSON，确保包含 `name`、`url`、`authentication`（含 `schemes`，切勿写真实密钥！测试占位统一用 `FAKE_TEST_KEY_DO_NOT_USE_12345`）、`skills`（含 `id` 与 `description`）四要素。

---

## 5. 量化验收命令

在当前实验目录执行（或在仓库根目录执行 `python3 labs/S4-M06-single-vs-multi-agent/verify.py`）：

```bash
# 检查你当前的 starter_prompt.md 架构方案进度（初始状态预期为 FAIL 并给出中文提示）
python3 verify.py

# 验证标准参考方案 solution_prompt.md（预期 5/5 全绿 PASS）
python3 verify.py --solution
```
