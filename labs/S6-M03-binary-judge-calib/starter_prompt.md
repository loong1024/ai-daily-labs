# 待改进的 AI 评审提示词（Starter 基线版）

请你担任客服与文档问答质检专家，阅读下面的用户问题和 AI 回答，从准确性、完整性、语气专业度综合打 1-10 分，并给出一句话评语。

## 用户问题
{user_input}

## 参考资料
{reference}

## 待评估回答
{response}

## 输出要求
请直接输出 JSON：
{"score": 1到10的整数, "comment": "打分理由"}

<!-- 改进指引：请阅读 README.md 第 4 节实操步骤升级本提示词，完成后运行 python3 labs/S6-M03-binary-judge-calib/verify.py 验收。 -->
