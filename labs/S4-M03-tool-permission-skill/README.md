# S4-M03：给 Agent 接高危工具总怕捅娄子？六维权限审查 Skill 实战

> **所属章节**：Ch.6 自主智能体 Agent · Agentic AI 四大设计模式、MCP 生态与安全沙箱  
> **实验类型**：`skill` ｜ **专题**：`agent_mcp` ｜ **预计耗时**：60 分钟 ｜ **零代码友好**：是（纯编辑 Markdown 即可通关！）

---

## 一、场景需求与常见痛点

每当团队准备给智能体新增函数工具（Tool Schema）或接入社区第三方 MCP Server 时，安全与工程评审常常顾此失彼；而如果直接把大段安全审查规则硬塞进日常通用 System Prompt，又会引发严重的注意力干扰：

1. **缺乏预览与参数边界**：工具描述含糊、缺少先预览再落库（Dry-run）与参数枚举约束，模型极易带通配符 `*` 误删文件，或被无分页的超大返回撑爆上下文。
2. **踩中“致命三要素”（Lethal Trifecta）**：无意间让同一个 Agent 同时拥有“读取私密数据 + 接收不可信外部网页/邮件输入 + 对外发信/Webhook 外传”三项能力，一旦遭遇间接提示注入就会导致核心数据外泄。
3. **日常任务天天误触发**：把工具权限审查规则写得触发范围过宽，导致平时改一句海报文案、调一个普通 Python 折扣函数或改一行 CSS 样式时，助手也天天跳出来做权限审查。

**实验目标**：  
无需编写复杂代码，直接完善即插即用的 Agent Skill 文件（`starter.md` → 标准 `SKILL.md`），实现 **精准 Frontmatter 触发边界（连续 3+ 次普通修改 0 误触发）** 与 **六维工具权限体检清单（对高危坏例三大红线 100% 标为 `BLOCKER`）**。

---

## 二、本目录资源说明

```text
labs/S4-M03-tool-permission-skill/
├── README.md                         # 实验说明、Skill 部署方法与免代码用法
├── fixtures/
│   ├── mcp_review_cases.json         # 4 组工具/MCP 审查回归样本（常规插件、三大高危坏例、信息残缺样本、安全只读样本）
│   └── router_trigger_logs.json      # 7 条客户端真实请求序列（3 条工具审查正例 + 4 条连续日常文案/代码修改反例）
├── starter.md                        # 起点残缺 Skill 配置（触发词泛滥导致误触发、仅 2 条模糊检查项、缺 BLOCKER 红线与只读约束）
├── solution.md                       # 标准生产级 SKILL.md（可直接复制到 .claude/skills/agent-tool-review/SKILL.md）
└── verify.py                         # 自动化红蓝对抗验收脚本（测试路由静默度 + 六维完备度 + 高危坏例拦截率）
```

---

## 三、Vibe Coding 一键启动口令

将下面口令直接粘贴给你的 AI 助手（Cursor / Claude Code / Windsurf 等）：

```text
请阅读 @labs/S4-M03-tool-permission-skill/README.md 与 fixtures/ 测试素材，按根目录 AGENTS.md 结对教练协议带我完善 starter.md 六维权限审查清单，运行 verify.py 直到全部验收通过。
```

---

## 四、实操步骤指引

### 步骤 1：运行红灯基线，查看残缺 `starter.md` 的漏报与误触发问题
```bash
python3 labs/S4-M03-tool-permission-skill/verify.py
```
你会直观看到 `starter.md` 存在的四大问题：
1. YAML 头部 `description` 写成了“任何修改任务都自动运行”，导致连续 4 次日常文案、业务逻辑、CSS 和 SQL 修改全部误触发；
2. 审查步骤只有“名字好不好听、参数有没有写注释”两条，缺失返回值精简、危险操作隔离、最小权限范围与注入面检查；
3. 未定义 `BLOCKER / MAJOR / MINOR` 分级与高危红线，面对“通配符删除目录 + 全局管理员令牌 + 读取私密薪资库叠加外部网页与外发邮件”的高危坏例完全漏报；
4. 错误地要求助手“直接覆盖改写用户原配置文件”，违背只读审校安全约束。

### 步骤 2：完善 `starter.md` 六维权限审查 Skill（零代码纯中文编辑）
对照以下要点修改 `starter.md`：
1. **收敛 YAML Frontmatter 触发条件**：
   - `name: agent-tool-review`
   - `description` 明确限定仅当新增/修改 Agent 工具定义（函数 Schema、MCP Tool）、接入第三方 MCP Server 或用户要求审查工具/权限时触发；并显式声明**不用于审查普通业务代码或日常文案修改**。
2. **补齐六维审查步骤**：
   - **命名与描述**：名称具体不重叠；写清用途、何时不该用与参数格式示例；
   - **参数约束**：用足枚举（`enum`）、类型、必填与格式约束，严查可被滥用的自由文本或通配符 `*`；
   - **返回值**：只返回决策所需最小字段，大结果支持过滤/分页/截断，错误信息具体可操作；
   - **危险操作**：写入、删除、发送、付款与只读工具严格分离，具备预览（Dry-run）、人工确认、可撤销或幂等键；
   - **权限范围**：凭证遵循最小权限并限定资源范围（严禁全局管理员令牌），授权由下游系统强制校验而非依赖模型自觉；
   - **注入面**：检查是否将网页、邮件、Issue 等不可信内容带入上下文；严查同一 Agent 同时具备“私密数据访问 + 不可信内容输入 + 对外通信外发”的**致命三要素**，并排查第三方工具描述中的可疑隐藏指令。
3. **规范输出表格与只读约束**：
   - 规定使用 `| 严重级别 | 工具 | 问题 | 依据 | 修改建议 |` 表格，明确 `BLOCKER` / `MAJOR` / `MINOR` 三级标准，最后给出“是否建议上线”结论及最多 3 条优先修复项；
   - 明确两条硬约束：① 信息不足时列出需补充内容，不要猜测；② 只给出修改建议，不直接改动代码或配置文件。

### 步骤 3：部署到你的本地客户端（可选实战扩展）
验收全绿后，可一键部署为真实项目的常驻技能：
```bash
mkdir -p .claude/skills/agent-tool-review
cp labs/S4-M03-tool-permission-skill/starter.md .claude/skills/agent-tool-review/SKILL.md
```
> **网页端免安装用法**：直接复制改进后的 `starter.md` 正文粘入网页版 AI 对话框作为首条“安全审校员指令”，再粘入 `fixtures/mcp_review_cases.json` 中的配置即可当场体验红线体检！

---

## 五、验收命令

```bash
# 检查当前 starter.md 修改进度（零代码修改 Markdown 后直接复跑）
python3 verify.py

# 在仓库根目录运行
python3 labs/S4-M03-tool-permission-skill/verify.py

# 验证标准参考配置 solution.md（应 100% 全绿通过）
python3 verify.py --solution
```
