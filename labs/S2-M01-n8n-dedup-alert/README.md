# S2-M01 · 定时摘要总重推或错点？轻量 n8n 立即去重与告警实验

> **所属章节**：Ch.5 自动化 AI 工作流 · 确定性 AI 工作流编排与无人值守自动化  
> **实验类型**：`github` 即插即用 n8n 工作流配置包 | **预计耗时**：60 分钟

## 1. 场景与常见痛点

独立开发者用 n8n 搭建每日 RSS AI 摘要推送时，最容易踩中三个隐蔽工程坑：

1. **UTC 时区错位**：容器默认 `UTC` 时区，定时触发器写成 `08:00`，结果等到北京时间下午 `16:00` 才推；且未用“当前时间 +2 分钟”做当场快验。
2. **缺少跨轮次幂等去重**：多个订阅源交叉转载，或手动重跑/定时轮询时未按 `link` 去重且未过滤超过 24 小时的陈旧文章，同一篇内容反复轰炸群聊。
3. **静默失败无告警**：LLM 节点开启了 `continueOnFail: true` 或未校验输出 JSON 字段（`title`、`summary`、`tags`），一旦 API 密钥失效或模型吐出非标准文本，整条流静默吞错或把脏数据直接发进群，没人收到告警。

## 2. 实验目标

在 60 分钟内完成一套可直接导入 `n8nio/n8n` 的双工作流配置包（主摘要流 + `Error Trigger` 告警流），通过本地回放模拟器与真实单容器双验真，达成：
- **显式本地时区（`Asia/Shanghai`）**：把触发器设为“当前时间后 2 分钟”即可准点触发，告别跨天苦等。
- **24 小时过滤 + `link` 跨执行去重**：连续手动触发两轮，重复链接与超期旧文 100% 拦截。
- **JSON 字段强校验 + 独立 `Error Trigger` 告警流**：注入失效占位凭证 `FAKE_TEST_KEY_DO_NOT_USE_12345` 或脏 JSON 时，主推送立即阻断并秒发异常通知到测试 Webhook。

## 3. 本目录文件说明

- `fixtures/rss_batches.json`：含“后 2 分钟”时区探针、连续两轮 RSS 抓取批次（含跨源重复链接、48 小时过期旧文、第二轮新增文章）以及 3 组红蓝故障注入样本（失效占位凭证 `FAKE_TEST_KEY_DO_NOT_USE_12345`、破损 JSON、缺字段 JSON）。
- `starter.workflow.json`：残缺基线版 n8n 工作流导出数组（默认 `UTC` 时区、无 24h 过滤与 `removeDuplicates` 节点、`continueOnFail: true` 吞错、未绑定 `Error Trigger` 错误流）。
- `solution.workflow.json`：可直接通过 `n8n import:workflow` 或网页端导入的标准双工作流配置包（含主工作流与绑定好的 `Error Trigger` 告警工作流）。
- `verify.py`：工作流拓扑解析与多轮/红蓝故障回放验收器（无需启动 Docker 也能秒级验真配置完整性）。

## 4. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf：

```text
请阅读 @labs/S2-M01-n8n-dedup-alert/README.md 与 fixtures/，按 AGENTS.md 带我修复 starter.workflow.json 并运行 python3 labs/S2-M01-n8n-dedup-alert/verify.py 直到通过。
```

## 5. 动手步骤指引

1. **（可选）轻量拉起单容器 n8n**：
   ```bash
   docker run -it --rm --name n8n-lab -p 5678:5678 \
     -e GENERIC_TIMEZONE=Asia/Shanghai -e TZ=Asia/Shanghai \
     n8nio/n8n:latest
   ```
   新建飞书/企微群自定义机器人或打开 Webhook.site 获取免配置测试接收 URL（注：长期早 8 点无人值守需部署在常开云服务器或托管平台，避免笔记本休眠漏跑）。
2. **修复时区偏差**：在 `starter.workflow.json` 主工作流的 `settings.timezone` 中将 `"UTC"` 改为 `"Asia/Shanghai"`，核对 `Schedule Trigger` 节点在本地时间 `07:58` 下距 `08:00` 仅差 `2` 分钟。
3. **补齐近 24 小时过滤与按链接去重**：在 RSS 读取节点后串联 `n8n-nodes-base.filter`（仅保留 24 小时内条目）与 `n8n-nodes-base.removeDuplicates`（`operation: "removeItemsSeenInPreviousExecutions"`，去重字段绑定 `link`）。
4. **加严 JSON 契约并绑定 `Error Trigger`**：将 LLM 节点的 `continueOnFail` 设为 `false`，新增 `Validate JSON Schema` 校验节点（强检非空 `title`、`summary` 与非空数组 `tags`），并在 `settings.errorWorkflow` 绑定含 `n8n-nodes-base.errorTrigger` + 告警 Webhook 的错误工作流。

## 6. 量化验收命令

```bash
# 验收当前 starter.workflow.json 修改进度（初始为红灯拦截提示，修好后全绿通过）
python3 labs/S2-M01-n8n-dedup-alert/verify.py

# 对照检查标准参考配置包（应 100% 通过）
python3 labs/S2-M01-n8n-dedup-alert/verify.py --solution
```
