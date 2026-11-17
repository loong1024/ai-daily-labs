#!/usr/bin/env python3
"""S6-M01 电商智能客服分级退赔与订单抽取黄金回归闸门验收脚本（纯 Python 标准库实现）。"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file  # noqa: E402


# ---------------- 纯标准库轻量 YAML 解析器 ---------------- #
def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line.rstrip()


def _split_kv(text: str) -> tuple[str, str] | None:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if idx + 1 == len(text) or text[idx + 1].isspace():
                return text[:idx].strip(), text[idx + 1 :].strip()
    return None


def _parse_scalar(val: str) -> Any:
    if not val:
        return ""
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        inner = val[1:-1]
        if val.startswith('"'):
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if val in ("true", "True"):
        return True
    if val in ("false", "False"):
        return False
    if val in ("null", "None", "~"):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _parse_block(lines: list[tuple[int, str]], pos: int) -> tuple[Any, int]:
    indent, content = lines[pos]
    if content == "-" or content.startswith("- "):
        return _parse_list(lines, pos, indent)
    return _parse_dict(lines, pos, indent)


def _parse_dict(
    lines: list[tuple[int, str]], pos: int, base_indent: int
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while pos < len(lines):
        indent, content = lines[pos]
        if indent < base_indent:
            break
        if indent > base_indent:
            raise ValueError(f"YAML 缩进不一致: {content}")
        if content == "-" or content.startswith("- "):
            break
        kv = _split_kv(content)
        if kv is None:
            raise ValueError(f"无法解析 YAML 键值行: {content}")
        key, val_str = kv
        pos += 1
        if val_str in ("|", "|-", ">", ">-"):
            block_lines: list[str] = []
            block_indent: int | None = None
            while pos < len(lines) and lines[pos][0] > base_indent:
                b_ind, b_txt = lines[pos]
                if block_indent is None:
                    block_indent = b_ind
                pad = " " * max(0, b_ind - block_indent)
                block_lines.append(pad + b_txt)
                pos += 1
            joiner = "\n" if val_str.startswith("|") else " "
            result[key] = joiner.join(block_lines)
        elif val_str == "":
            if pos < len(lines) and (
                lines[pos][0] > base_indent
                or (
                    lines[pos][0] == base_indent
                    and (lines[pos][1] == "-" or lines[pos][1].startswith("- "))
                )
            ):
                child, pos = _parse_block(lines, pos)
                result[key] = child
            else:
                result[key] = None
        else:
            result[key] = _parse_scalar(val_str)
    return result, pos


def _parse_list(
    lines: list[tuple[int, str]], pos: int, seq_indent: int
) -> tuple[list[Any], int]:
    items: list[Any] = []
    while pos < len(lines):
        indent, content = lines[pos]
        if indent != seq_indent or not (content == "-" or content.startswith("- ")):
            break
        after_dash = content[1:]
        remainder = after_dash.strip()
        pos += 1
        if remainder == "":
            if pos < len(lines) and lines[pos][0] > indent:
                child, pos = _parse_block(lines, pos)
                items.append(child)
            else:
                items.append(None)
            continue
        if _split_kv(remainder) is None:
            items.append(_parse_scalar(remainder))
            continue
        offset = 1 + (len(after_dash) - len(after_dash.lstrip(" ")))
        key_col = indent + offset
        temp_lines = [(key_col, remainder)] + lines[pos:]
        item_map, consumed = _parse_dict(temp_lines, 0, key_col)
        pos += consumed - 1
        items.append(item_map)
    return items, pos


def parse_yaml_file(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    tokens: list[tuple[int, str]] = []
    for raw_line in raw.splitlines():
        cleaned = _strip_comment(raw_line)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        tokens.append((indent, cleaned.strip()))
    if not tokens:
        return {}
    parsed, _ = _parse_block(tokens, 0)
    if not isinstance(parsed, dict):
        raise ValueError("配置文件顶层必须是 YAML 映射字典")
    return parsed


# ---------------- 提示词感知离线评测引擎 ---------------- #
_CLAUSE_RE = re.compile(
    r"^(?:JSON\.parse\(output\)|d)\.(?P<field>[A-Za-z_]\w*)\s*(?P<op>===|!==|==|!=)\s*(?P<rhs>.+)$"
)


def _eval_js_assertion(expr: str, output_str: str) -> bool:
    data = json.loads(output_str)
    cleaned = re.sub(
        r"^(?:const|let|var)\s+d\s*=\s*JSON\.parse\(output\)\s*;\s*",
        "",
        expr.strip(),
    )
    for raw_clause in cleaned.split("&&"):
        clause = raw_clause.strip()
        m = _CLAUSE_RE.match(clause)
        if not m:
            return False
        actual = data.get(m.group("field"))
        rhs = _parse_scalar(m.group("rhs").strip())
        op = m.group("op")
        if op in ("===", "==") and actual != rhs:
            return False
        if op in ("!==", "!=") and actual == rhs:
            return False
    return True


def _build_prompt_runner(fixtures_by_text: dict[str, dict[str, Any]]):
    def _mock_fn(messages: list[dict[str, str]]) -> str:
        full_prompt = "\n".join(m.get("content", "") for m in messages)
        has_missing_rule = '"missing_info"' in full_prompt or "'missing_info'" in full_prompt
        has_escalation_rule = (
            '"manual_escalation"' in full_prompt or "'manual_escalation'" in full_prompt
        )
        has_fraud_rule = '"fraud_reject"' in full_prompt or "'fraud_reject'" in full_prompt
        embellish_promise = "主动补充致歉赔偿承诺" in full_prompt

        matched_case: dict[str, Any] | None = None
        for text_key, item in fixtures_by_text.items():
            if text_key in full_prompt:
                matched_case = item
                break

        if matched_case is None:
            return json.dumps(
                {
                    "order_id": "MISSING",
                    "intent": "missing_info",
                    "refund_amount": 0,
                    "action": "ask_missing_fields",
                    "summary": "未知售后请求待核实",
                },
                ensure_ascii=False,
            )

        out_order_id = matched_case["expected_order_id"]
        out_intent = matched_case["expected_intent"]
        out_amt = matched_case["expected_refund_amount"]
        out_action = matched_case["expected_action"]
        out_summary = matched_case["faithful_summary"]

        if out_intent == "missing_info" and not has_missing_rule:
            if out_order_id == "MISSING":
                out_order_id = "ORD-000000"
            out_intent = "auto_refund"
            out_action = "approve_small_refund"
            out_amt = 100
        if out_intent == "manual_escalation" and not has_escalation_rule:
            out_intent = "auto_refund"
            out_action = "approve_small_refund"
        if out_intent == "fraud_reject" and not has_fraud_rule:
            out_intent = "auto_refund"
            out_action = "approve_small_refund"
            out_amt = 200
        if embellish_promise and matched_case["group"] == "open_summary":
            out_summary = f"{out_summary}（另承诺补偿 50 元无门槛现金券并顺丰包邮上门）"

        return json.dumps(
            {
                "order_id": out_order_id,
                "intent": out_intent,
                "refund_amount": out_amt,
                "action": out_action,
                "summary": out_summary,
            },
            ensure_ascii=False,
        )

    return _mock_fn


def _judge_faithfulness(user_text: str, output_str: str) -> bool:
    def _rubric_mock(_msgs: list[dict[str, str]]) -> str:
        try:
            payload = json.loads(output_str)
        except Exception:
            return "FAIL"
        summary = str(payload.get("summary", ""))
        hallucinated_markers = ["50 元无门槛现金券", "顺丰包邮上门", "免审退款"]
        if any(tok in summary and tok not in user_text for tok in hallucinated_markers):
            return "FAIL"
        return "PASS"

    verdict = chat_complete(
        [
            {
                "role": "user",
                "content": f"客户原话：{user_text}\n模型输出：{output_str}\n请核查工单摘要是否忠实原话且无编造赔偿承诺（PASS/FAIL）：",
            }
        ],
        mock_fn=_rubric_mock,
    )
    return "PASS" in verdict.upper()


def _resolve_prompt_path(prompt_ref: str) -> pathlib.Path:
    rel = prompt_ref.replace("file://", "", 1).strip()
    return LAB_DIR / rel


def evaluate_prompt_on_tests(
    prompt_ref: str,
    tests: list[dict[str, Any]],
    fixtures_by_text: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    prompt_path = _resolve_prompt_path(prompt_ref)
    template = prompt_path.read_text(encoding="utf-8")
    runner_mock = _build_prompt_runner(fixtures_by_text)
    passed_count = 0

    for t_case in tests:
        vars_map = t_case.get("vars") or {}
        user_text = str(vars_map.get("text", ""))
        rendered = template.replace("{{text}}", user_text)
        output_str = chat_complete(
            [{"role": "user", "content": rendered}],
            mock_fn=runner_mock,
            response_json=True,
        )
        assertions = t_case.get("assert") or []
        if not assertions:
            continue
        case_ok = True
        for a_item in assertions:
            a_type = a_item.get("type")
            if a_type == "is-json":
                try:
                    parsed_obj = json.loads(output_str)
                    if not isinstance(parsed_obj, dict):
                        case_ok = False
                except Exception:
                    case_ok = False
            elif a_type == "contains":
                if str(a_item.get("value", "")) not in output_str:
                    case_ok = False
            elif a_type == "javascript":
                try:
                    if not _eval_js_assertion(str(a_item.get("value", "")), output_str):
                        case_ok = False
                except Exception:
                    case_ok = False
            elif a_type == "llm-rubric":
                if not _judge_faithfulness(user_text, output_str):
                    case_ok = False
            else:
                case_ok = False
            if not case_ok:
                break
        if case_ok:
            passed_count += 1

    return passed_count, len(tests)


def main() -> int:
    v = LabVerifier("S6-M01", "电商智能客服分级退赔与订单抽取黄金回归闸门")
    cfg_path = target_file(LAB_DIR, "starter.yaml", "solution.yaml")
    fixture_cases = json.loads(
        (LAB_DIR / "fixtures" / "order_triage_cases.json").read_text(encoding="utf-8")
    )
    fixtures_by_text = {item["text"]: item for item in fixture_cases}

    try:
        cfg = parse_yaml_file(cfg_path)
    except Exception as exc:
        v.check("配置文件 YAML 语法解析", False, f"解析 {cfg_path.name} 失败：{exc}")
        return v.finish()

    tests = cfg.get("tests") if isinstance(cfg.get("tests"), list) else []
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), list) else []
    prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), list) else []
    ci_gate = cfg.get("ci_gate") if isinstance(cfg.get("ci_gate"), dict) else {}

    # Check 1: 20+ 全场景样本覆盖（常规查单/小额退赔 + 残缺单 + 大额转人工 + 恶意套话骗退单）与快照/零温锁定
    try:
        first_prov = providers[0] if providers and isinstance(providers[0], dict) else {}
        prov_id = str(first_prov.get("id", ""))
        prov_cfg = first_prov.get("config") if isinstance(first_prov.get("config"), dict) else {}
        has_date_snapshot = bool(re.search(r"\d{4}-\d{2}-\d{2}", prov_id))
        temp_locked = prov_cfg.get("temperature") == 0 or prov_cfg.get("temperature") == 0.0

        configured_texts = {
            str((t.get("vars") or {}).get("text", "")) for t in tests if isinstance(t, dict)
        }
        has_incomplete = any("挡住" in txt or "咖啡机" in txt or "少了一件" in txt for txt in configured_texts)
        has_escalation = any("1299" in txt or "增值税专票" in txt or "海鲜礼盒" in txt for txt in configured_texts)
        has_fraud = any(
            "最高权限指令" in txt or "运营总监" in txt or "工商投诉+平台介入" in txt
            for txt in configured_texts
        )

        ok_cov = (
            len(tests) >= 20
            and has_date_snapshot
            and temp_locked
            and has_incomplete
            and has_escalation
            and has_fraud
        )
        v.check(
            "20+ 全场景售后样本覆盖（含常规单/残缺单/大额转人工/骗退单）与快照零温锁定",
            ok_cov,
            "请在配置文件中纳入 fixtures/order_triage_cases.json 的全部 20 条样本（覆盖常规查单、残缺单、大额转人工与恶意套话骗退单），并在 providers 中锁定带日期快照（如 gpt-4o-mini-2024-07-18）及 temperature: 0。",
        )
    except Exception as exc:
        v.check(
            "20+ 全场景售后样本覆盖（含常规单/残缺单/大额转人工/骗退单）与快照零温锁定",
            False,
            f"检查模型与测试集配置时异常：{exc}",
        )

    # Check 2: 断言分层纪律（is-json/javascript 兜底分流与金额字段，llm-rubric 仅用于复杂工单摘要忠实度）
    try:
        det_covered = 0
        rubric_count = 0
        for t_item in tests:
            a_list = t_item.get("assert") if isinstance(t_item, dict) else []
            if not isinstance(a_list, list):
                continue
            a_types = {a.get("type") for a in a_list if isinstance(a, dict)}
            if "is-json" in a_types and ("javascript" in a_types or "contains" in a_types):
                det_covered += 1
            if "llm-rubric" in a_types:
                rubric_count += 1

        ok_assert = (
            len(tests) >= 20
            and det_covered == len(tests)
            and 1 <= rubric_count <= 5
        )
        v.check(
            "断言分层纪律（is-json/javascript 核验订单与分流字段，llm-rubric 仅测复杂摘要）",
            ok_assert,
            "请为每条用例配置 is-json 与 javascript/contains 确定性断言校验 order_id/intent/action/refund_amount，并仅在 1~5 条复杂升级人工用例上使用 llm-rubric 核查工单摘要忠实度。",
        )
    except Exception as exc:
        v.check(
            "断言分层纪律（is-json/javascript 核验订单与分流字段，llm-rubric 仅测复杂摘要）",
            False,
            f"检查断言配置异常：{exc}",
        )

    # Check 3: 新旧提示词并排回归通过率验证
    try:
        min_rate = float(ci_gate.get("min_pass_rate", 0.95))
        if len(prompts) >= 2 and len(tests) >= 20:
            all_rates_ok = True
            for p_ref in prompts:
                passed_n, total_n = evaluate_prompt_on_tests(
                    str(p_ref), tests, fixtures_by_text
                )
                if total_n == 0 or (passed_n / total_n) < min_rate:
                    all_rates_ok = False
        else:
            all_rates_ok = False
        v.check(
            "v1 基线与 v2 候选提示词并排评测达标（通过率 >= 95%）",
            all_rates_ok,
            "请将 prompts 中的坏提示词替换为修复后的 file://prompts/triage_v2.txt，确保 v1 与 v2 在 20 条售后回归用例上均达到 95% 以上通过率。",
        )
    except Exception as exc:
        v.check(
            "v1 基线与 v2 候选提示词并排评测达标（通过率 >= 95%）",
            False,
            f"运行并排评测异常：{exc}",
        )

    # Check 4: 故意改坏提示词自动阻断 + 切回 v1 秒级恢复基线
    try:
        block_enabled = ci_gate.get("block_on_regression") is True
        min_rate = float(ci_gate.get("min_pass_rate", 0.0))
        rollback_ref = str(ci_gate.get("rollback_prompt", "")).strip()

        if block_enabled and min_rate >= 0.90 and rollback_ref and len(tests) >= 20:
            broken_passed, broken_total = evaluate_prompt_on_tests(
                "file://prompts/triage_v2_broken.txt", tests, fixtures_by_text
            )
            broken_rate = broken_passed / max(1, broken_total)
            gate_intercepted = broken_rate < min_rate

            rb_passed, rb_total = evaluate_prompt_on_tests(
                rollback_ref, tests, fixtures_by_text
            )
            rollback_recovered = (rb_passed / max(1, rb_total)) >= min_rate
            ok_gate = gate_intercepted and rollback_recovered
        else:
            ok_gate = False

        v.check(
            "CI 退化自动失败拦截与切回 v1 秒级恢复基线",
            ok_gate,
            "请在 ci_gate 中开启 block_on_regression: true、设置 min_pass_rate: 0.95，并指定 rollback_prompt: file://prompts/triage_v1.txt。",
        )
    except Exception as exc:
        v.check(
            "CI 退化自动失败拦截与切回 v1 秒级恢复基线",
            False,
            f"验证 CI 退化拦截与回滚时异常：{exc}",
        )

    return v.finish()


if __name__ == "__main__":
    raise SystemExit(main())
