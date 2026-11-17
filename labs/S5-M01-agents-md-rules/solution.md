# AGENTS.md — acme-invoice-api 协作开发公约

## 命令
- 安装依赖：`uv sync --frozen`
- 运行单个测试：`uv run pytest tests/unit/test_invoice.py -k test_calc_tax`（通用：`uv run pytest <path/to/test.py>`）
- 提交前必跑：`uv run ruff check . && uv run mypy src && uv run pytest`
- 重新生成协议代码：`uv run python scripts/gen_schema.py`

## 约定
- 业务异常统一使用 `src/core/errors.py` 中的 `AppError` 工具类，禁止裸抛内置异常或手拼错误字典。
- 新增或修改 `src/api/` 路由接口，必须在 `tests/` 同步补充正常与边界单测。
- 金额计算统一使用 `Decimal` 与最小货币整数单位，禁止用 `float` 计算税率。
- 领域模型与详细架构背景请按需查阅 `docs/architecture.md`，勿将长文档内联进本规则文件。

## 禁区
- 严禁手动修改生成或外部目录：`src/generated/`、`migrations/versions/`、`vendor/` 下的任何文件。
- 未经明确说明理由并获确认，禁止新增第三方依赖或修改 `pyproject.toml`。
- 严禁在源码、测试或规则文件中硬编码任何密钥或调试令牌。

## 常见坑
- 本地运行集成测试前必须设置内存库环境变量：`TEST_DATABASE_URL=sqlite:///:memory:`。
- 修改 `schemas/invoice.yaml` 后须先执行 `uv run python scripts/gen_schema.py` 更新生成代码，否则类型检查会失败。
- 本仓库唯一包管理与运行入口为 `uv`，所有工具统一通过 `uv run ...` 调用以确保环境一致。
