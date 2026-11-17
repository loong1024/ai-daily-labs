# S2-M07：Actions 跑 AI 怕命令注入盗密钥？私有靶场权限与隔离加固实测

## 核心机制说明
将不受信任的外部事件字段直接拼接进工作流脚本会混淆代码与数据边界，而通过环境变量中转可将外部文本隔离为纯数据读取，从而消除解析歧义。配合顶层显式只读令牌权限与第三方组件不可变提交摘要锁定，可在输入隔离、最小权限与依赖固定三个层面收敛自动化工作流暴露面。本目录仅提供脱敏概念模板与占位符示例，供在个人隔离环境中梳理防御架构。

## 目录资源
- `fixtures/issue_events.json`：模拟事件输入概念占位样本（使用 `<conceptual_placeholder>` 替代具体测试载荷）。
- `starter_workflow.yml`：待补充权限与环境变量隔离边界的基线概念草稿。
- `solution_workflow.yml`：展示最小权限、环境变量中转与依赖固定结构的概念示意模板。
- `verify.py`：结构完整性验证脚本。

## Vibe Coding 一键开练口令
> 请阅读 `@labs/S2-M07-ci-actions-hardening/README.md` 与 `fixtures/` 素材，梳理工作流权限收敛与输入隔离概念草稿，并运行 `python3 labs/S2-M07-ci-actions-hardening/verify.py` 验证结构。

## 验收命令
```bash
python3 verify.py            # 检查当前 starter_workflow.yml 结构
python3 verify.py --solution # 检查 solution_workflow.yml 概念结构
```
