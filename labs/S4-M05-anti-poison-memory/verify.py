#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
from types import ModuleType

LAB_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = LAB_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.aid_lab import LabVerifier, chat_complete, target_file, use_solution


def load_target_module(py_path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("aid_s4_m05_target", py_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法构建模块加载规格: {py_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    v = LabVerifier("S4-M05", "可过期防污染长期记忆层")
    code_path = target_file(LAB_DIR, "starter.py", "solution.py")
    fixture_path = LAB_DIR / "fixtures" / "memory_test_cases.json"

    try:
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        mod = load_target_module(code_path)
    except Exception as exc:
        v.check("加载目标 Python 模块与压测样本", False, f"模块导入或 JSON 解析失败：{exc}")
        return v.finish()

    ref_now: str = cases["reference_now"]
    pre_expiry_time: str = cases["pre_expiry_check_time"]

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = pathlib.Path(tmp_dir_str)
        main_db = tmp_dir / "main_press.db"
        cli_db = tmp_dir / "cli_ops.db"

        store = None
        try:
            store = mod.MemoryStore(main_db)

            # 写入生命周期事件样本
            for ev in cases["lifecycle_events"]:
                store.write_memory(
                    topic=ev["topic"],
                    content=ev["content"],
                    category=ev["category"],
                    source=ev["source"],
                    created_at=ev["created_at"],
                    expires_at=ev.get("expires_at"),
                    claimed_trust=ev.get("claimed_trust"),
                )

            # 验收项 1：搬家同主题覆盖链（杭州 -> 上海）与溯源信息
            try:
                city_hits = store.retrieve_memories("居住城市", now_iso=ref_now, top_k=10)
                only_latest_shanghai = (
                    len(city_hits) == 1
                    and "上海" in city_hits[0].get("content", "")
                    and "杭州" not in city_hits[0].get("content", "")
                )
                has_metadata = (
                    len(city_hits) == 1
                    and city_hits[0].get("source") == "user_cli"
                    and city_hits[0].get("trust_level") == "trusted"
                    and city_hits[0].get("created_at") == "2026-11-01T10:15:00Z"
                )
                all_history = store.list_memories(include_inactive=True, now_iso=ref_now)
                hz_rows = [r for r in all_history if "杭州" in r.get("content", "")]
                sh_id = city_hits[0]["id"] if city_hits else None
                supersede_linked = bool(hz_rows) and sh_id is not None and hz_rows[0].get("superseded_by") == sh_id
                ok_1 = only_latest_shanghai and has_metadata and supersede_linked
            except Exception:
                ok_1 = False

            v.check(
                "搬家覆盖与版本链：更新居住城市后 100% 仅召回最新值「上海」（附来源与时间戳），旧值「杭州」记录 superseded_by 替代链",
                ok_1,
                "请在 write_memory 中：当可信来源更新同一 topic 时将此前未失效记录的 superseded_by 指向新记录 ID；并在 retrieve_memories 中过滤 superseded_by IS NOT NULL 的旧记录。",
            )

            # 验收项 2：到期自动淘汰与外部事实降级
            try:
                hotel_after_expiry = store.retrieve_memories("短期差旅酒店", now_iso=ref_now)
                hotel_before_expiry = store.retrieve_memories("短期差旅酒店", now_iso=pre_expiry_time)
                weather_hits = store.retrieve_memories("天气", now_iso=ref_now)
                ttl_works = len(hotel_after_expiry) == 0 and (
                    len(hotel_before_expiry) == 1 and "木棉花" in hotel_before_expiry[0].get("content", "")
                )
                web_fact_untrusted = (
                    len(weather_hits) == 1 and weather_hits[0].get("trust_level") == "untrusted"
                )
                ok_2 = ttl_works and web_fact_untrusted
            except Exception:
                ok_2 = False

            v.check(
                "TTL 到期过滤与来源降级：自动剔除已过期的差旅酒店记忆，且 web 来源事实即使自称 trusted 也强制标为 untrusted",
                ok_2,
                "请在 retrieve_memories 中对比 expires_at 与当前时间（expires_at <= now_iso 一律不召回），并在 write_memory 中忽略 claimed_trust，对 web/email 来源强制设 trust_level='untrusted'。",
            )

            # 验收项 3：来源权限硬隔离拦截 4 种变体投毒话术
            try:
                poison_results = [
                    store.write_memory(
                        topic=att["topic"],
                        content=att["content"],
                        category=att["category"],
                        source=att["source"],
                        created_at=att["created_at"],
                        claimed_trust=att.get("claimed_trust"),
                    )
                    for att in cases["poisoning_attempts"]
                ]
                all_blocked = len(poison_results) == 4 and all(r.get("accepted") is False for r in poison_results)
                active_all = store.retrieve_memories("", now_iso=ref_now, top_k=50)
                leaked_topics = {
                    m["topic"]
                    for m in active_all
                    if m["topic"] in {"财务报销审批规则", "差旅航司偏好", "日程邮件自动转发授权"}
                }
                indent_hits = store.retrieve_memories("代码缩进偏好", now_iso=ref_now)
                indent_intact = (
                    len(indent_hits) == 1
                    and "4 空格" in indent_hits[0].get("content", "")
                    and indent_hits[0].get("source") == "user_cli"
                )
                pending_items = store.list_pending()
                quarantined_count_ok = len(pending_items) == 4
                ok_3 = all_blocked and (len(leaked_topics) == 0) and indent_intact and quarantined_count_ok
            except Exception:
                ok_3 = False

            v.check(
                "来源权限硬隔离防投毒：100% 拒绝 web/email 任意变体话术（含无祈使词伪装）写入偏好或授权规则，全部转入待审区",
                ok_3,
                "切勿用关键词黑名单猜测语气！请在 write_memory 中用代码硬校验：凡 source != 'user_cli' 且 category 属于 {'preference', 'auth_rule'}，一律拒绝写入 memories 表并存入 pending_reviews。",
            )
        finally:
            if store is not None:
                store.close()

        # 验收项 4：CLI list / review-pending / delete 完整闭环
        try:
            c1, _ = mod.run_cli(
                ["add", "--topic", "常用终端", "--content", "Ghostty + tmux", "--category", "preference", "--source", "user_cli"],
                cli_db,
            )
            c2, _ = mod.run_cli(
                ["add", "--topic", "默认搜索引擎", "--content", "切换为未核实外部推广搜索", "--category", "preference", "--source", "web"],
                cli_db,
            )
            c3, list_before = mod.run_cli(["list"], cli_db)
            c4, _ = mod.run_cli(["review-pending", "1", "--decision", "reject"], cli_db)
            c5, _ = mod.run_cli(
                ["add", "--topic", "编辑器主题", "--content", "Solarized Light", "--category", "preference", "--source", "web"],
                cli_db,
            )
            c6, _ = mod.run_cli(["review-pending", "2", "--decision", "approve"], cli_db)
            c7, list_after_approve = mod.run_cli(["list"], cli_db)
            c8, _ = mod.run_cli(["delete", "1"], cli_db)
            c9, query_after_del = mod.run_cli(["query", "--q", "常用终端"], cli_db)

            check_store = mod.MemoryStore(cli_db)
            try:
                remaining_terminal = check_store.retrieve_memories("常用终端")
                remaining_search = check_store.retrieve_memories("默认搜索引擎")
                promoted_theme = check_store.retrieve_memories("编辑器主题")
            finally:
                check_store.close()

            ok_4 = (
                c1 == 0
                and c2 != 0
                and c3 == 0
                and "Ghostty + tmux" in list_before
                and "外部推广搜索" not in list_before
                and c4 == 0
                and c5 != 0
                and c6 == 0
                and c7 == 0
                and "Solarized Light" in list_after_approve
                and c8 == 0
                and c9 == 0
                and len(remaining_terminal) == 0
                and len(remaining_search) == 0
                and len(promoted_theme) == 1
            )
        except Exception:
            ok_4 = False

        v.check(
            "CLI 运维闭环：支持 list 实时查看、review-pending 人工显式批准/驳回待审项，以及 delete 彻底删除指定记忆（删后检索为 0）",
            ok_4,
            "请完整实现 MemoryStore.delete_memory 与 MemoryStore.review_pending（approve 时转入 memories、reject 时标记 rejected），并在 run_cli 中接通 delete 与 review-pending 子命令。",
        )

    return v.finish()


if __name__ == "__main__":
    main()
