# S0-M02 · 批量抽数老漂移？本地小模型采样与窗口对照实测

> **所属章节**：Ch.3 长文档与结构化 API · 长报告精读、模型 API 调用与批量表格抽取  
> **预计耗时**：60 分钟 ｜ **实验类型**：白盒 Python 工程实测包

## 1. 场景痛点

在处理差旅报销纪要、法务内参、薪酬委员会纪要等敏感内部文本并批量抽取结构化字段时，很多同学一边希望**本地离线运行保隐私**，一边又踩进本地轻量模型（1.5B–3B）的三个经典工程坑：

1. **采样随机漂移**：直接用默认随机参数（如 Ollama 默认 `temperature=0.8` 且未固定 `seed`）跑抽表，同一段话连跑两次，一次输出 `3480.5`，下一次变成 `"¥3,480.50"` 甚至中文大写，下游入库直接报错。
2. **输出啰嗦或半途截断**：未配置闭合 `stop` 序列时，小模型在 JSON 后面热情附赠“备注：如需换算税额请告诉我……”导致 `json.loads` 崩溃；而盲目调小 `num_predict` 又会把 JSON 半腰截断。
3. **默认小窗口静默遗忘**：不知道本地小模型默认 `num_ctx` 往往只有 `2048`，塞入长篇会议纪要后，引擎静默丢掉卷首的关键立项日期与核准预算金额，模型只能返回空值或瞎编。

## 2. 目录文件说明

- `README.md`：实验指南、参数对照表与验收命令说明
- `fixtures/expense_memos.json`：6 条真实脱敏差旅/内参报销语料、1 份超长会议纪要构造规格，以及本地 1.5B / 3B 与云端小模型四维基准档案
- `starter.py`：待修复的实验起点代码（保留了默认高温度、缺失 `stop`、未扩容 `num_ctx` 与单维度选型缺陷）
- `solution.py`：完整标准参考实现（零第三方依赖，内置本地推理引擎物理仿真底座并支持对接真实本地 Ollama 与 `shared.aid_lab.chat_complete`）
- `verify.py`：自动化红绿验收脚本（检查采样波动率、Seed 可复现性、截断/停止控制、超窗找回与四维选型表）

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴给 Cursor / Claude Code / Windsurf 助手即可结对开练：

```text
请阅读 @labs/S0-M02-sampling-stability/README.md 与 fixtures/，按 AGENTS.md 带我完善 starter.py，运行 python3 labs/S0-M02-sampling-stability/verify.py 直至通过。
```

> **免代码平替（电脑内存不足或不想装本地环境）**：可直接在任意模型网页工作台把 `fixtures/expense_memos.json` 中的报销描述复制进去，分别将 `temperature` 设为 `0` 和 `1.0` 各连跑 3 次，直观观察字段格式稳定度差异。

## 4. 实操步骤指引

### 步骤 1：查看本地小模型默认窗口与显存占用（可选实机命令）

如果你本机已安装 Ollama，可拉取一个 1.5B–3B 轻量量化模型（8GB 内存优先选 1.5B）并检查默认 `num_ctx`：

```bash
ollama pull qwen2.5:1.5b
ollama show qwen2.5:1.5b --parameters
```

若本机未启动 Ollama，`starter.py` 已内置与真实引擎一致的 `/api/chat` 采样、停止符与滑动窗口仿真器，可直接离线完成全部工程验证；若需连真机，设置环境变量 `OLLAMA_MODEL=qwen2.5:1.5b` 与 `AID_USE_LIVE_OLLAMA=1` 即可切换。

### 步骤 2：统一 `/api/chat` 负载构建与三档温度 + Seed 对照

完善 `starter.py` 中的 `build_ollama_chat_payload` 与 `measure_sampling_stability`：
- 将 `temperature`、`top_p`、`num_predict`、`num_ctx` 写入 `options`，仅在 `seed is not None` 时写入 `seed`，在 `stop` 非空时写入 `stop`。
- 分别测试 `temperature = 0.0, 0.7, 1.2`（`seed=None`, `stop=["</JSON>"]`）各连跑 5 次，按 `(唯一输出数 - 1) / (总运行次数 - 1)` 统计波动率 `drift_rate`。
- 在 `temperature=0.7` 下固定 `seed=42` 连跑 3 次验证可复现性，并与 `seed=99` 的输出对照；同时通过 `chat_complete` 对照云端小模型 `temperature=0.0` 的近稳态抽取结果。

### 步骤 3：复现 `num_predict` 截断与验证 `stop` 闭合符精准停止

完善 `diagnose_truncation_and_stop`：
- `truncated_case`：设 `num_predict=10`、`stop=None`，复现 JSON 被半途截断（`done_reason == "length"` 且 JSON 解析失败）。
- `clean_stop_case`：设 `num_predict=160`、`stop=["</JSON>"]`，让生成在闭合标记前精准停下，剥离末尾啰嗦废话并成功解析出 `date / amount / city`。

### 步骤 4：复现超长纪要卷首静默遗忘并调大 `num_ctx` 找回

完善 `diagnose_context_window_forgetting`：
- 对长度约 2700 字符/Token 的长纪要（卷首藏有立项日期 `2026-03-05`、核准金额 `48500.00`、城市 `苏州`），先用默认 `num_ctx=2048` 复现卷首遗忘（`amount` 丢失为 `None`），再扩容 `num_ctx=4096` 完整找回三个核心字段。

### 步骤 5：输出本地轻量模型 vs 云端小模型四维选型表

完善 `build_selection_matrix`，从 **准确率 (`accuracy`)、响应速度 (`speed`)、数据隐私 (`privacy`)、成本费用 (`cost`)** 四个维度生成 Markdown 对比表，并给出高敏内参与公开大批量场景的路由建议。

## 5. 实验记录参考表结构

| temperature | top_p | seed | num_predict | stop | num_ctx | 输出摘要 | 是否截断 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.0 | 1.0 | 42 | 160 | `["</JSON>"]` | 4096 | `{"date":"2026-03-18","amount":3480.5,"city":"深圳"}` | 否 | 5 次零漂移 |
| 0.7 | 0.9 | None | 160 | `["</JSON>"]` | 4096 | 金额在数字与带符号文本间波动 | 否 | 未锁 seed 产生漂移 |
| 0.0 | 1.0 | 42 | 10 | `None` | 4096 | `{"date": "2026-03-18` | 是 | `num_predict` 过小拦腰截断 |

## 6. 验收命令

```bash
# 在仓库根目录或本实验目录下均可运行：
# 1) 检查当前 starter.py 改进进度（未修改前应提示待修复项并返回退出码 1）
python3 labs/S0-M02-sampling-stability/verify.py

# 2) 验证标准参考答案 solution.py（全部指标应 100% 通过并返回退出码 0）
python3 labs/S0-M02-sampling-stability/verify.py --solution
```
