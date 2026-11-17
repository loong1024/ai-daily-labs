# S0-M08 怕被提示注入套话或刷爆额度？上线前硬兜底安全排查

## 场景与痛点
当网页摘要、文档问答或自动邮件小工具准备分享上线时，最常见的隐患来自把安全边界寄托在“口头提示词约束”上：
- 只在系统提示词叮嘱“不要执行外部文档指令”，遇到外部网页夹带的隐蔽文本仍可能混淆指令与数据边界；
- 把模型输出的 HTML 或数据库查询条件未经严格转义与参数化校验就直接渲染或拼接；
- 只配置了软预算告警而缺少网关层硬消费封顶与频控，链接一旦外传极易被脚本耗尽额度。

## 目录资源说明
- `fixtures/prelaunch_cases.json`：包含 6 组上线前联调测试样例（正常摘要、用户输入直接注入、外部文档间接注入、含 `<script>` 标签的模型输出、跨租户文档查询、超出硬预算上限请求）。
- `starter.py`：待加固的基线网关骨架（仅做软提示拼接、原样返回 HTML、字符串拼接 SQL、仅记录软预算告警）。
- `solution.py`：完整硬兜底参考实现（通道区分与不可信文档隔离、`html.escape` 严格转义、服务端会话鉴权 + 参数化查询、网关硬配额拦截）。
- `verify.py`：自动化红绿验收脚本（零第三方依赖）。

## Vibe Coding 一键启动口令
将下面这句话直接粘贴给 Cursor / Claude Code / Windsurf：

> 请阅读 @labs/S0-M08-prelaunch-safety-gate/README.md 与 fixtures/ 素材，按根目录 AGENTS.md 教练协议带我一步步完善 starter.py 并跑通 verify.py 全部验收指标。

## 动手步骤
1. **跑通红灯基线**：运行 `python3 verify.py`，观察基线代码在通道隔离、HTML 转义、越权查询与硬配额上的 4 项未通过提示。
2. **区分直接注入与间接注入**：在 `classify_injection_channel` 中区分来自 `user_query` 的直接指令越界与来自 `external_doc` 的间接外部指令，并将外部文档包裹在 `<untrusted_document>...</untrusted_document>` 数据隔离标签内。
3. **输出严格转义与参数化鉴权**：在 `sanitize_model_html` 中使用 `html.escape(..., quote=True)` 将 `<script>` 等标签转为纯文本实体；在 `build_authorized_doc_query` 中强制核验 `session_user_id == requested_owner_id`，并改用 `?` 占位符与参数元组。
4. **落地网关硬封顶**：在 `enforce_hard_quota_and_call` 中前置拦截未登录、超频与超 `hard_cap_usd` 的请求（不发起模型调用），通过后再对模型输出执行安全转义。

## 验收命令
```bash
# 验收当前 starter.py 改进进度（初始状态预期为 FAIL 退出码 1）
python3 labs/S0-M08-prelaunch-safety-gate/verify.py

# 验证标准参考实现 solution.py（预期 100% PASS 退出码 0）
python3 labs/S0-M08-prelaunch-safety-gate/verify.py --solution
```
