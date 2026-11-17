# S2-M01 · 竞品动态与行业异动情报流：轻量 n8n 定时抓取、单号幂等去重与异常即时告警

<!-- SCENARIO_HEADER_START -->
## 🎬 场景与能力拆解概览

| 👤 真实客户痛点现场 | 📍 用在什么业务场景 | 🎯 要实现的核心能力 |
| :--- | :--- | :--- |
| 商业分析与出海运营盯防竞品调价和清关新规时，过去默认 UTC 定时总晚八小时，多渠道转载刷屏销售群，密钥过期静默断更几天都没人发现。 | 每日晨会前多源竞品与行业政策自动情报流，输入含云帆 CRM 降价、欧盟清关新规、渠道同源转载重单、48h 旧闻及假密钥与坏 JSON 故障样本。 | 跑通本地时区两分钟快验、24h 时效过滤与情报单号跨轮幂等去重，100% 拦住脏 JSON 并联动 Error Trigger 秒发异常告警。 |

- **核心能力积木**：`B10 幂等防重账本 + 退避死信 + 人工审批门` · `B06 原生 JSON Schema + 缺证据拒答锁` · `B09 入口轻重分级路由 + 多路并行/硬关卡`
- **推荐实现链路**：锁定 Asia/Shanghai 定时触发 → 拉取竞品与政策多路源 → 过滤 24h 内新异动 → 按情报单号与链接跨执行幂等去重 → LLM 产出结构化摘要并过 Schema 硬关卡 → 失败联动 Error Trigger 秒推告警
- **头号避坑红线**：切忌在 LLM 节点勾选 continueOnFail 静默吞错却不接字段校验与 Error Trigger，否则密钥失效或模型吐客套话时会把报错直接发进业务大群。
<!-- SCENARIO_HEADER_END -->


> **所属章节**：Ch.5 自动化 AI 工作流 · 确定性 AI 工作流编排与无人值守自动化  
> **实验类型**：`github` 即插即用 n8n 双工作流配置包 | **预计耗时**：60 分钟

## 1. 业务现场与常见翻车点

商业分析、出海运营与销售支持团队每天晨会（`08:00`）前需要盯紧**竞品突发降价、海关清关新规与头部货代附加费异动**。用轻量 n8n 搭自动情报早报时，最容易踩中三个生产级暗坑：

1. **默认 UTC 时区导致晨会情报变“下午茶”**：容器默认 `UTC` 时区，定时触发写成 `08:00`，结果等到北京时间 `16:00` 才推，销售谈完单才看到竞品早已降价 30%。
2. **渠道转载与二次重跑疯狂刷屏**：竞品官网公告与多家渠道媒体快讯指向同一情报单号（`event_id`）和原文链接（`link`），再加上未过滤超 24 小时的旧周报，大群每天被重复动态和旧闻轰炸。
3. **静默吞错导致情报断更无人知**：LLM 节点勾选了 `continueOnFail: true` 且缺 JSON 字段硬校验，一旦 API 密钥过期（`401`）或模型吐出夹带客套话的坏 JSON，整条流水线要么把报错当简报发进业务大群，要么静默停摆好几天没人收到告警。

## 2. 实验目标

在 60 分钟内完成一套可直接导入 `n8nio/n8n` 的双工作流配置包（**主情报流 + `Error Trigger` 异常即时告警流**），通过本地拓扑回放验收器与单容器双验真，达成：
- **显式本地时区（`Asia/Shanghai`）**：把触发器设为“当前时间后 2 分钟”（如 `07:58` 测 `08:00`）准点触发，无需跨天苦等。
- **24 小时时效过滤 + 情报单号/链接跨轮幂等去重**：剔除 48 小时前陈旧盘点，连续两轮触发对同源转载与历史已推情报 100% 幂等拦截，仅放行新增异动。
- **JSON 字段强校验 + 独立 `Error Trigger` 即时告警**：注入失效测试凭证 `FAKE_TEST_KEY_DO_NOT_USE_12345` 或残缺 JSON 时，主推送立即熔断阻断，并秒级向值班 Webhook 发出故障告警。

## 3. 本目录文件说明

- `fixtures/rss_batches.json`：含“晨会前 +2 分钟”时区探针、连续两轮行业异动情报批次（含云帆 CRM 降价 30%、欧盟锂电池清关 EPR 新规、星航速递美西拥堵附加费上调 12%、渠道同源转载重复单 `INTEL-20261116-001`、48 小时陈旧周报）及 3 组红蓝故障注入样本（失效占位凭证 `FAKE_TEST_KEY_DO_NOT_USE_12345`、非 JSON 客套文本、缺字段 JSON）。
- `starter.workflow.json`：待修复的基线 n8n 工作流导出数组（默认 `UTC` 时区、缺 24h 过滤与幂等去重节点、`continueOnFail: true` 吞错、未绑定 `Error Trigger` 告警流）。
- `solution.workflow.json`：标准参考双工作流配置包（可直接通过 `n8n import:workflow` 或网页端一键导入）。
- `verify.py`：工作流拓扑解析与多轮幂等/红蓝故障回放验收脚本（免装 Docker 亦可秒级验真）。

## 4. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf：

```text
请阅读 @labs/S2-M01-n8n-dedup-alert/README.md 与 fixtures/，按 AGENTS.md 带我修复 starter.workflow.json 并运行 python3 labs/S2-M01-n8n-dedup-alert/verify.py 直到通过。
```

## 5. 动手步骤指引

1. **（可选）轻量拉起单容器 n8n**：
   ```bash
   docker run -it --rm --name n8n-intel-lab -p 5678:5678 \
     -e GENERIC_TIMEZONE=Asia/Shanghai -e TZ=Asia/Shanghai \
     n8nio/n8n:latest
   ```
   新建飞书/企微群自定义机器人或打开 Webhook.site 获取免配置测试接收 URL（注：正式早 8 点无人值守需部署于常开云主机或托管平台，防笔记本合盖休眠漏跑）。
2. **修复时区偏差**：在 `starter.workflow.json` 主工作流的 `settings.timezone` 中将 `"UTC"` 改为 `"Asia/Shanghai"`，验证本地 `07:58` 距 `08:00` 触发仅需 `120` 秒。
3. **补齐近 24 小时过滤与单号/链接幂等去重**：在两路情报源读取节点后串联 `n8n-nodes-base.filter`（仅保留 24 小时内新异动）与 `n8n-nodes-base.removeDuplicates`（`operation: "removeItemsSeenInPreviousExecutions"`，`keyField` 绑定 `event_id` 或 `link`，`dedupeValue: "={{ $json.event_id || $json.link }}"`）。
4. **加严 JSON 契约并绑定 `Error Trigger` 即时告警**：将 LLM 节点的 `continueOnFail` 设为 `false`、`responseFormat` 设为 `json_object`，串联 `Validate JSON Schema`（`n8n-nodes-base.code`）强检非空 `title`、`summary` 与非空数组 `tags`；并在 `settings.errorWorkflow` 绑定 `"intel-digest-error-alert"`，在告警流中连好 `Error Trigger -> Push Error Alert Webhook`。

## 6. 量化验收命令

```bash
# 验收当前 starter.workflow.json 修改进度（初始为红灯拦截诊断，修好后全绿通过）
python3 labs/S2-M01-n8n-dedup-alert/verify.py

# 对照检查标准参考配置包（应 100% 全绿通过）
python3 labs/S2-M01-n8n-dedup-alert/verify.py --solution
```
