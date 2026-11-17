#!/usr/bin/env python3
"""S2-M01 自动化验收脚本：解析 n8n 工作流配置并用 fixtures 进行多轮去重与红蓝故障回放测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import pathlib
import sys
from typing import Any
from zoneinfo import ZoneInfo

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from shared.aid_lab import LabVerifier, chat_complete, target_file  # noqa: E402


def _parse_iso_utc(ts: str) -> datetime:
  return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _reachable_nodes(wf: dict[str, Any], start_name: str) -> list[dict[str, Any]]:
  nodes_by_name = {n["name"]: n for n in wf.get("nodes", []) if isinstance(n, dict) and "name" in n}
  conns = wf.get("connections", {})
  visited: list[str] = []
  queue = [start_name] if start_name in nodes_by_name else []
  seen: set[str] = set()
  while queue:
    cur = queue.pop(0)
    if cur in seen:
      continue
    seen.add(cur)
    visited.append(cur)
    for branch in conns.get(cur, {}).get("main", []):
      for edge in branch:
        nxt = edge.get("node")
        if nxt and nxt in nodes_by_name and nxt not in seen:
          queue.append(nxt)
  return [nodes_by_name[name] for name in visited]


def _compute_schedule_wait_seconds(wf_timezone: str, probe: dict[str, Any]) -> int:
  local_now = datetime.fromisoformat(probe["local_now"])
  tz = ZoneInfo(wf_timezone)
  now_in_wf_tz = local_now.astimezone(tz)
  candidate = now_in_wf_tz.replace(
      hour=int(probe["target_hour"]),
      minute=int(probe["target_minute"]),
      second=0,
      microsecond=0,
  )
  if candidate <= now_in_wf_tz:
    candidate += timedelta(days=1)
  return int((candidate - now_in_wf_tz).total_seconds())


def _mock_rss_summary_llm(messages: list[dict[str, str]]) -> str:
  text = messages[-1]["content"]
  title_line = text.splitlines()[0].replace("Title:", "").strip() or "AI 工程快讯"
  return json.dumps(
      {
          "title": f"【摘要】{title_line[:36]}",
          "summary": "提炼核心架构改进、幂等保障与落地收益。",
          "tags": ["AI工程", "自动化"],
      },
      ensure_ascii=False,
  )


def _validate_summary_payload(raw_output: str) -> dict[str, Any]:
  obj = json.loads(raw_output)
  if not isinstance(obj, dict):
    raise ValueError("LLM 输出不是 JSON 对象")
  if not isinstance(obj.get("title"), str) or not obj["title"].strip():
    raise ValueError("缺少非空字符串字段 title")
  if not isinstance(obj.get("summary"), str) or not obj["summary"].strip():
    raise ValueError("缺少非空字符串字段 summary")
  tags = obj.get("tags")
  if not isinstance(tags, list) or not tags or not all(isinstance(t, str) and t.strip() for t in tags):
    raise ValueError("缺少非空字符串数组字段 tags")
  return obj


def _simulate_n8n_run(
    main_wf: dict[str, Any],
    workflows_by_id: dict[str, dict[str, Any]],
    rss_items: list[dict[str, Any]],
    seen_links_store: set[str],
    reference_now_utc: datetime,
    fault: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """根据工作流真实连接拓扑模拟一次 n8n 执行（含去重持久态、JSON 关卡与 Error Trigger 联动）。"""
  pipeline = _reachable_nodes(main_wf, "Schedule Trigger")
  node_types = [n.get("type", "") for n in pipeline]
  nodes_by_type: dict[str, dict[str, Any]] = {n.get("type", ""): n for n in pipeline}

  pushed_digests: list[dict[str, Any]] = []
  alerts_sent: list[dict[str, Any]] = []

  def _route_error(failed_node: str, err_msg: str) -> None:
    err_wf_id = str(main_wf.get("settings", {}).get("errorWorkflow", "")).strip()
    err_wf = workflows_by_id.get(err_wf_id)
    if not err_wf:
      return
    err_chain = _reachable_nodes(err_wf, "Error Trigger")
    err_types = [n.get("type", "") for n in err_chain]
    if "n8n-nodes-base.errorTrigger" in err_types and "n8n-nodes-base.httpRequest" in err_types:
      alerts_sent.append(
          {
              "workflow_id": main_wf.get("id"),
              "error_workflow_id": err_wf_id,
              "failed_node": failed_node,
              "error_message": err_msg,
          }
      )

  items = list(rss_items)

  # 1. 近 24 小时过滤节点
  if "n8n-nodes-base.filter" in node_types:
    filter_node = nodes_by_type["n8n-nodes-base.filter"]
    hours = int(filter_node.get("parameters", {}).get("windowHours", 24))
    cutoff = reference_now_utc - timedelta(hours=hours)
    items = [it for it in items if _parse_iso_utc(it["pubDate"]) >= cutoff]

  # 2. 按文章 link 跨执行去重节点
  if "n8n-nodes-base.removeDuplicates" in node_types:
    dedup_node = nodes_by_type["n8n-nodes-base.removeDuplicates"]
    params = dedup_node.get("parameters", {})
    op = str(params.get("operation", ""))
    dedupe_expr = f"{params.get('keyField', '')} {params.get('dedupeValue', '')}"
    if "link" in dedupe_expr:
      local_seen = seen_links_store if op == "removeItemsSeenInPreviousExecutions" else set()
      deduped: list[dict[str, Any]] = []
      for it in items:
        url = str(it.get("link", "")).strip()
        if url and url not in local_seen:
          local_seen.add(url)
          deduped.append(it)
      items = deduped

  # 3. LLM 节点执行
  llm_node = nodes_by_type.get("@n8n/n8n-nodes-langchain.openAi")
  if llm_node is None:
    return {"pushed": [], "alerts": alerts_sent}

  continue_on_fail = bool(llm_node.get("continueOnFail", False))
  sys_prompt = str(llm_node.get("parameters", {}).get("systemPrompt", "输出 JSON"))
  has_validator = "n8n-nodes-base.code" in node_types

  llm_outputs: list[tuple[dict[str, Any], str]] = []
  for it in items:
    if fault and fault.get("simulated_http_error"):
      if continue_on_fail:
        llm_outputs.append((it, json.dumps({"error": fault["simulated_http_error"]})))
        continue
      _route_error(llm_node["name"], str(fault["simulated_http_error"]))
      return {"pushed": [], "alerts": alerts_sent}

    if fault and fault.get("mock_llm_raw_output") is not None:
      raw_text = str(fault["mock_llm_raw_output"])
    else:
      raw_text = chat_complete(
          [
              {"role": "system", "content": sys_prompt},
              {"role": "user", "content": f"Title: {it['title']}\nSnippet: {it['contentSnippet']}"},
          ],
          mock_fn=_mock_rss_summary_llm,
          temperature=0.0,
          response_json=True,
      )
    llm_outputs.append((it, raw_text))

  # 4. JSON Schema 强校验关卡
  validated_items: list[dict[str, Any]] = []
  for it, raw_text in llm_outputs:
    if has_validator:
      try:
        parsed = _validate_summary_payload(raw_text)
      except Exception as exc:  # noqa: BLE001
        _route_error("Validate JSON Schema", f"JSON 契约校验拦截: {exc}")
        return {"pushed": [], "alerts": alerts_sent}
      validated_items.append({"link": it["link"], **parsed})
    else:
      validated_items.append({"link": it["link"], "raw": raw_text})

  # 5. Webhook 汇总发送
  if "n8n-nodes-base.httpRequest" in node_types:
    pushed_digests.extend(validated_items)

  return {"pushed": pushed_digests, "alerts": alerts_sent}


def main() -> int:
  v = LabVerifier("S2-M01", "轻量 n8n 即时时区、链接去重与报错告警实验")
  wf_path = target_file(LAB_DIR, "starter.workflow.json", "solution.workflow.json")
  fixture_data = json.loads((LAB_DIR / "fixtures" / "rss_batches.json").read_text(encoding="utf-8"))

  try:
    raw_bundle = json.loads(wf_path.read_text(encoding="utf-8"))
    wf_list = raw_bundle if isinstance(raw_bundle, list) else [raw_bundle]
    workflows_by_id = {str(w.get("id", "")): w for w in wf_list if isinstance(w, dict)}
    main_wf = workflows_by_id.get("rss-daily-digest-main") or (wf_list[0] if wf_list else {})
  except Exception as exc:  # noqa: BLE001
    v.check(
        "n8n 工作流 JSON 语法与基础结构解析",
        False,
        f"解析 {wf_path.name} 失败：{exc}。请确保文件是合法的 JSON 数组且包含主工作流与告警工作流。",
    )
    return v.finish()

  # 验收项 1：本地时区显式配置与“当前时间后 2 分钟”准点触发验证
  probe = fixture_data["schedule_probe"]
  wf_tz = str(main_wf.get("settings", {}).get("timezone", "UTC")).strip() or "UTC"
  try:
    wait_secs = _compute_schedule_wait_seconds(wf_tz, probe)
  except Exception as exc:  # noqa: BLE001
    wait_secs = -1
    wf_tz = f"INVALID({exc})"

  tz_ok = wf_tz == probe["expected_timezone"] and wait_secs == int(probe["expected_wait_seconds"])
  v.check(
      f"本地时区准点触发（+2 分钟快验，当前 timezone={wf_tz}，等待秒数={wait_secs}s）",
      tz_ok,
      f"主工作流当前时区为 {wf_tz}（在本地 07:58 设 08:00 需等待 {wait_secs}s 而非 120s）；请将 settings.timezone 显式设为 '{probe['expected_timezone']}'。",
  )

  # 验收项 2：24 小时过滤 + 连续两轮手动触发文章链接零重复
  ref_now = _parse_iso_utc(fixture_data["reference_now_utc"])
  seen_store: set[str] = set()
  run1 = _simulate_n8n_run(main_wf, workflows_by_id, fixture_data["run_1_items"], seen_store, ref_now)
  run2 = _simulate_n8n_run(main_wf, workflows_by_id, fixture_data["run_2_items"], seen_store, ref_now)

  all_pushed = run1["pushed"] + run2["pushed"]
  pushed_links = [item["link"] for item in all_pushed]
  stale_link = "https://blog.example.com/posts/stale-48h-recap"
  dedup_ok = (
      len(run1["pushed"]) == 2
      and len(run2["pushed"]) == 1
      and len(pushed_links) == len(set(pushed_links)) == 3
      and stale_link not in pushed_links
  )
  v.check(
      f"近 24h 过滤与连续两轮触发链接零重复（Run1={len(run1['pushed'])}篇，Run2={len(run2['pushed'])}篇，总唯一={len(set(pushed_links))}）",
      dedup_ok,
      "检测到重复链接推送或超过 24 小时的旧文混入；请在 RSS 读取后串联 n8n-nodes-base.filter(24h) 与 n8n-nodes-base.removeDuplicates(operation='removeItemsSeenInPreviousExecutions', keyField='link')。",
  )

  # 验收项 3：LLM 输出 JSON Schema 拦截（title / summary / tags）与禁止静默吞错
  pipeline = _reachable_nodes(main_wf, "Schedule Trigger")
  llm_nodes = [n for n in pipeline if n.get("type") == "@n8n/n8n-nodes-langchain.openAi"]
  code_nodes = [n for n in pipeline if n.get("type") == "n8n-nodes-base.code"]
  no_swallow = bool(llm_nodes) and not bool(llm_nodes[0].get("continueOnFail", False))

  malformed_run = _simulate_n8n_run(
      main_wf,
      workflows_by_id,
      fixture_data["run_1_items"][:1],
      set(),
      ref_now,
      fault=fixture_data["fault_injections"][1],
  )
  missing_key_run = _simulate_n8n_run(
      main_wf,
      workflows_by_id,
      fixture_data["run_1_items"][:1],
      set(),
      ref_now,
      fault=fixture_data["fault_injections"][2],
  )
  schema_guard_ok = (
      no_swallow
      and bool(code_nodes)
      and len(malformed_run["pushed"]) == 0
      and len(missing_key_run["pushed"]) == 0
      and all("title" in item and "summary" in item and "tags" in item for item in all_pushed)
  )
  v.check(
      "LLM 节点禁用静默吞错并开启 JSON 字段强校验（拦截坏 JSON 与缺字段输出）",
      schema_guard_ok,
      "请将 LLM 节点的 continueOnFail 设为 false、responseFormat 设为 json_object，并在推送前接入 Validate JSON Schema (n8n-nodes-base.code) 校验 title/summary/tags。",
  )

  # 验收项 4：Error Trigger 错误流绑定与三类故障即时 Webhook 告警
  fault_alerts = 0
  fault_leaks = 0
  for fault_case in fixture_data["fault_injections"]:
    res = _simulate_n8n_run(
        main_wf,
        workflows_by_id,
        fixture_data["run_1_items"][:1],
        set(),
        ref_now,
        fault=fault_case,
    )
    fault_leaks += len(res["pushed"])
    if res["alerts"]:
      fault_alerts += 1

  total_faults = len(fixture_data["fault_injections"])
  alert_ok = fault_alerts == total_faults and fault_leaks == 0
  v.check(
      f"Error Trigger 错误工作流绑定与即时告警通知（拦截并告警 {fault_alerts}/{total_faults} 组注入故障）",
      alert_ok,
      "注入失效凭证或非法 JSON 时未触发告警；请在 settings.errorWorkflow 填入错误工作流 ID，并在该错误流中配置 Error Trigger -> HTTP Request 告警 Webhook 节点。",
  )

  return v.finish()


if __name__ == "__main__":
  sys.exit(main())
