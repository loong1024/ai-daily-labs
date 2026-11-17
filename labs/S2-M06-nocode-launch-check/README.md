# S2-M06：零代码自动化一上线就翻车？通用上线体检表与三招无代码排雷

## 场景与痛点
飞书多维表格、钉钉、Make 或 Zapier 流程只拿单条正常样本测通就上线，常因连交重复触发、空日期崩溃、报错无告警、明文贴密钥或未设预算封顶而翻车。本实验基于“活动报名自动摘要发群”沙盒模板完成七维自检与三招无代码排雷。

## 目录资源
- `fixtures/workflow_draft_and_runs.json`：含隐患的无代码流程配置草稿与 6 条演练测试单（正常单、连点重复单、空日期乱码单、意图模糊单、接收端断联单、百人群发单）。
- `starter_prompt.md`：漏项基线版上线记录（待完善）。
- `solution_prompt.md`：完整七维自检与三招演练修复参考记录。
- `verify.py`：自动化验收脚本。

## Vibe Coding 一键开练口令
> 请阅读 `@labs/S2-M06-nocode-launch-check/README.md` 与 `fixtures/`，带我完善 `starter_prompt.md` 并运行 `python3 labs/S2-M06-nocode-launch-check/verify.py` 直到通过。

## 实操步骤
1. **过七维体检表**：对照 `fixtures/workflow_draft_and_runs.json` 核查触发、数据、LLM 节点、错误处理、人工审批、密钥与成本、故障演练七项。
2. **演练一（连点去重）**：检查 `SUB-2026-001` 连续提交两次时的单号/邮箱查重规则，并收窄触发条件防止写回自触发。
3. **演练二（空值兜底）**：为空日期乱码单 `SUB-2026-002` 配置“待人工核对”分流，为模糊单 `SUB-2026-003` 配置“其他/不确定”兜底。
4. **演练三（告警与封顶）**：验证 `SUB-2026-004` 断联失败告警、为 `SUB-2026-005` 群发前加人工确认，将假密钥移入平台凭证库并设月度消费上限。

## 验收命令
```bash
python3 verify.py            # 验收当前 starter_prompt.md 进度
python3 verify.py --solution # 验收 solution_prompt.md 参考实现
```
