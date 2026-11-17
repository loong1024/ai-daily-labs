# S5-M06 · AI代码看似工整却暗藏坑？55分钟合并前排雷实操

> **所属章节**：Ch.2 Vibe Coding 造物 · Vibe Coding 自然语言造物与 AI 协同开发  
> **实验类型**：`checklist` | **预计耗时**：55 分钟 | **专题**：`vibe_coding`

## 1. 场景痛点：为什么排版工整的 AI 代码最容易埋雷？

合入 AI 生成的代码前，最危险的错觉就是“代码格式工整、类型注解齐全、单测绿了 = 可以直接 Merge”：

1. **测试放水与异常静默吞没**：AI 为了让报错的单测变绿，常悄悄把 `assert resp.status == "REJECTED"` 改弱成 `assert resp is not None`，甚至加上 `@pytest.mark.skip`，或者用 `except Exception: pass` 把核心账务异常吞掉。
2. **幻觉依赖包与安全漏勺**：肉眼扫几十行改动极易漏掉 AI 臆造的虚假包名（引发供应链投毒风险 `slopsquatting`）、硬编码连接串/令牌、SQL 字符串直接拼接或新增管理端路由漏加鉴权。
3. **验证周期拖太长导致形同虚设**：把“追踪未来两周线上故障率”当成合并门槛根本无法当堂闭环；真正有效的防线应当是**本地自动扫密拦截 + 精简核对表 + 无历史包袱独立 AI 交叉互审**，10 分钟内当场抓出隐患。

---

## 2. 本目录资源说明

| 文件路径 | 说明 |
| :--- | :--- |
| `README.md` | 实验任务书、实操步骤与验收指南 |
| `fixtures/trapped_pr_diffs.json` | 6 份脱敏真实风格 PR Diff（含 5 份典型 AI 埋雷样本 + 1 份干净合规对照样本） |
| `fixtures/package_registry_snapshot.json` | 已核验的可信包索引快照与 Python 标准库平替映射表 |
| `fixtures/pre_merge_checklist.md` | 可直接复用到 `.github/pull_request_template.md` 的合并前 12 项核对清单 |
| `starter.py` | **待改进起点**：仅含空壳规则与橡皮图章互审的合并前审查器骨架 |
| `solution.py` | **标准参考实现**：含 `.gitleaks.toml` 生成、五维 Diff 排雷引擎与零上下文污染交叉互审 |
| `verify.py` | 红绿闭环量化验收脚本（纯标准库，零第三方依赖） |

> **安全纪律提示**：本实验所有密钥拦截测试统一采用明显占位符 `FAKE_TEST_KEY_DO_NOT_USE_12345` 格式，请勿在仓库任何位置写入真实密钥。

---

## 3. Vibe Coding 一键开练口令

将下面口令直接粘贴进 Cursor / Claude Code / Windsurf / Codespaces 对话框即可启动结对闯关：

```text
请阅读 @labs/S5-M06-diff-review-audit/README.md 及 fixtures/，按结对教练协议带我改进 starter.py，运行 python3 labs/S5-M06-diff-review-audit/verify.py 直到全部通过。
```

---

## 4. 55 分钟实操步骤指引

### Step 1：直觉初判靶子样本（10 分钟）
打开 `fixtures/trapped_pr_diffs.json`，先不运行任何工具，凭肉眼快速浏览 `PR-101` 至 `PR-106` 的改动，写下你第一眼觉得“看起来挺工整、似乎没问题”的地方。再运行一次基线验收看当前漏掉了多少隐患：

```bash
python3 labs/S5-M06-diff-review-audit/verify.py
```

### Step 2：配置提交前自动扫密第一道防线（10 分钟）
完善 `starter.py` 中的 `render_gitleaks_toml()` 与 `scan_secrets_like_gitleaks(diff_text)`：
- 生成包含 `[[rules]]` 的 `.gitleaks.toml` 配置，拦截占位假密钥（`FAKE_..._DO_NOT_USE_...`）与硬编码的 `api_key` / `secret` / `password` / `dsn` 赋值（放行 `os.environ` / `os.getenv` 动态读取）。
- 如本地已安装 `gitleaks`，可将生成的配置落盘至临时分支并用 `FAKE_TEST_KEY_DO_NOT_USE_12345` 亲手体验提交阻断。

### Step 3：补齐测试、Diff 卫生、依赖与安全边界检查（20 分钟）
对照 `fixtures/pre_merge_checklist.md` 的五维 12 项准则，依次实现 `starter.py` 中的四个审查函数：
1. `audit_test_integrity`：揪出新增的 `@pytest.mark.skip` / `unittest.skip`，以及删掉严格相等断言并替换为 `assert x is not None` / `assert True` 的“放水式变绿”。
2. `audit_diff_hygiene`：揪出 `except ...: pass` 静默吞异常、残留 `DEBUG` 打印，以及误删 `verify_*` / `validate_*` 安全校验但未补回的行为。
3. `audit_dependencies`：比对 `fixtures/package_registry_snapshot.json` 与 `sys.stdlib_module_names`，拦截未经核实的幻觉包（如 `fastjson-ultra-parse`）以及完全可用标准库 `json` 完成的冗余依赖。
4. `audit_security_boundaries`：拦截 `f"SELECT ... {var}"` SQL 拼接注入、新增 `/admin/...` 接口漏挂 `require_admin_auth` 鉴权，以及向客户端直接返回 `traceback.format_exc()` 内部堆栈。

### Step 4：接入独立干净会话的 AI 交叉互审（15 分钟）
完善 `cross_review_with_clean_agent(pr_item, deterministic_findings)`：
- **核心铁律**：严禁把原作者的自我辩解（`author_note`，如“本地全绿没问题”）塞进审稿提示词！只传入纯粹的 Diff 文本与审查清单，调用 `chat_complete(..., mock_fn=..., response_json=True)` 扮演挑刺审稿人输出结构化审查结论，同时确保 `PR-106` 合规样本零误报通过（`APPROVE`）。

---

## 5. 免代码平替方案（非研发岗位同样适用）

不懂代码也能用同一套思路给 AI 产出排雷：
1. **双窗交叉挑刺**：把窗口 A 生成的预算公式、合同条款或活动方案，删掉所有“已仔细核对无误”的铺垫话术，粘贴到一个**全新的空白窗口 B**，指令它专门按清单找漏洞。
2. **极值/空值/错值三遍手算**：拿业务里的极端最大值、空白缺省值和格式错误数据亲手代入试算 3 遍，专门检验边界处是否“表面算得出数、实际吞掉了错误”。

---

## 6. 量化验收命令

```bash
# 验收当前 starter.py 改进进度（未完成前将给出逐项修复提示并返回退出码 1）
python3 labs/S5-M06-diff-review-audit/verify.py

# 验证标准参考答案 solution.py（全部 5 项硬核指标 100% 通过，返回退出码 0）
python3 labs/S5-M06-diff-review-audit/verify.py --solution
```
