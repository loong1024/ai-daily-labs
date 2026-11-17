# LLM 变更检查（Starter 草稿版）

修改提示词后请先跑一下测试，看看总体通过率有没有下降，如果没下降就可以直接提交代码。

## 步骤
1. 运行评测脚本。
2. 如果总体分数比之前高或持平，直接执行 git commit。

<!-- TODO 改进提示：
1. 补齐顶部 YAML Frontmatter（`name: llm-change-gate` 与 `description:` 触发说明）。
2. 明确触发范围：`prompts/` 目录、模型标识与 temperature 等采样参数、检索配置（切分大小/检索条数/重排）。
3. 补齐 `critical` 高危用例一票否决硬门槛（总通过率 ≥ 基线，且任何 critical 用例不得由通过变为失败）。
4. 明确禁止为了凑通过率擅自修改或删除评测用例，以及 PASS 时写入 `CHANGELOG-llm.md`（含回滚方式）、FAIL 时中止提交。
-->
