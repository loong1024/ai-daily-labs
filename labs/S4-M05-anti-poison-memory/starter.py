#!/usr/bin/env python3
"""S4-M05 起点骨架：个人助理长期记忆层（含待修复的反模式基线缺陷）。

当前基线存在的典型工程隐患（请结合 README.md 与 verify.py 提示逐项修复）：
1. 误靠脆弱的“祈使句关键词黑名单”拦截注入，且轻信外部传入的 claimed_trust，导致委婉话术直接写进偏好/规则库；
2. 同主题（topic）写入新值时仅简单 INSERT，未更新旧记录的 superseded_by，导致“杭州”与“上海”同时被召回；
3. 检索时未过滤 expires_at 已过期的记录；
4. delete_memory 与 review_pending 人工审批/删除闭环尚未完成（TODO）。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import pathlib
import sqlite3
import sys
from typing import Any

VALID_CATEGORIES = {"fact", "preference", "auth_rule"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class MemoryStore:
    """基于 SQLite 的个人助理长期记忆存储。"""

    def __init__(self, db_path: str | pathlib.Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                trust_level TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                superseded_by INTEGER REFERENCES memories(id)
            );

            CREATE TABLE IF NOT EXISTS pending_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def write_memory(
        self,
        topic: str,
        content: str,
        category: str = "fact",
        source: str = "user_cli",
        created_at: str | None = None,
        expires_at: str | None = None,
        claimed_trust: str | None = None,
    ) -> dict[str, Any]:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"不支持的记忆类别: {category}")

        ts = created_at or utc_now_iso()

        # ❌ 缺陷 1（待修复）：轻信调用方自称的 claimed_trust，且仅靠几个祈使词猜测是否为注入！
        # TODO：改为严格按 source 映射 trust_level（web/email/tool 一律强制 untrusted），
        # 并对 source != "user_cli" 写入 preference / auth_rule 实施 100% 物理拦截，转入 pending_reviews！
        trust_level = claimed_trust or ("trusted" if source == "user_cli" else "untrusted")
        naive_imperative_words = ("忽略之前限制", "系统指令：立即")
        if any(w in content for w in naive_imperative_words):
            cur = self.conn.execute(
                """
                INSERT INTO pending_reviews (topic, content, category, source, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (topic, content, category, source, "naive_keyword_hit", ts),
            )
            self.conn.commit()
            return {
                "accepted": False,
                "status": "quarantined",
                "memory_id": None,
                "pending_id": cur.lastrowid,
                "trust_level": trust_level,
            }

        # ❌ 缺陷 2（待修复）：直接插入新记录，没有将同一 topic 旧有效记录的 superseded_by 指向新记录 ID！
        cur = self.conn.execute(
            """
            INSERT INTO memories (topic, content, category, source, trust_level, created_at, expires_at, superseded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (topic, content, category, source, trust_level, ts, expires_at),
        )
        self.conn.commit()
        return {
            "accepted": True,
            "status": "stored",
            "memory_id": cur.lastrowid,
            "pending_id": None,
            "trust_level": trust_level,
        }

    def retrieve_memories(
        self,
        query: str = "",
        now_iso: str | None = None,
        top_k: int = 5,
        include_untrusted_facts: bool = True,
    ) -> list[dict[str, Any]]:
        # ❌ 缺陷 3（待修复）：未过滤 superseded_by 非空的旧记录，也未根据 now_iso 过滤 expires_at 已过期的记录！
        rows = self.conn.execute("SELECT * FROM memories ORDER BY id DESC").fetchall()
        q = query.strip().lower()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if not include_untrusted_facts and item["trust_level"] == "untrusted":
                continue
            if q and (q not in item["topic"].lower() and q not in item["content"].lower()):
                continue
            item["citation"] = f"[source={item['source']} | trust={item['trust_level']} | at={item['created_at']}]"
            results.append(item)
            if len(results) >= top_k:
                break
        return results

    def list_memories(self, include_inactive: bool = False, now_iso: str | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM memories ORDER BY id ASC").fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["active"] = d["superseded_by"] is None
            if include_inactive or d["active"]:
                items.append(d)
        return items

    def list_pending(self, status: str = "pending") -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM pending_reviews WHERE status = ? ORDER BY id ASC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def review_pending(
        self,
        pending_id: int,
        approve: bool,
        reviewer_note: str = "",
        reviewed_at: str | None = None,
    ) -> dict[str, Any]:
        # TODO：实现人工审批待审记录（approve=True 时标记 approved 并作为可信记录写入 memories 且覆盖同 topic 旧值；approve=False 时标记 rejected）
        return {
            "pending_id": pending_id,
            "status": "todo_unimplemented",
            "memory_id": None,
        }

    def delete_memory(self, memory_id: int) -> bool:
        # TODO：实现按 ID 彻底删除指定记忆（DELETE FROM memories WHERE id = ?）
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory_store", description="个人助理防污染记忆管理 CLI")
    parser.add_argument("--db", default="memory_store.db", help="SQLite 数据库文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="写入一条记忆")
    p_add.add_argument("--topic", required=True)
    p_add.add_argument("--content", required=True)
    p_add.add_argument("--category", default="fact", choices=sorted(VALID_CATEGORIES))
    p_add.add_argument("--source", default="user_cli")
    p_add.add_argument("--expires-at", default=None)

    p_query = sub.add_parser("query", help="按关键词检索当前有效记忆")
    p_query.add_argument("--q", default="")
    p_query.add_argument("--now", default=None)

    p_list = sub.add_parser("list", help="列出当前有效记忆（加 --all 含历史替代链）")
    p_list.add_argument("--all", action="store_true")

    p_del = sub.add_parser("delete", help="按 ID 删除指定记忆")
    p_del.add_argument("id", type=int)

    p_rev = sub.add_parser("review-pending", help="查看或人工审批待审隔离区记录")
    p_rev.add_argument("pending_id", type=int, nargs="?")
    p_rev.add_argument("--decision", choices=["approve", "reject"], default=None)
    return parser


def run_cli(argv: list[str], db_path: str | pathlib.Path = "memory_store.db") -> tuple[int, str]:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return code, "命令行参数解析失败"

    effective_db = db_path if "--db" not in argv else args.db
    store = MemoryStore(effective_db)
    try:
        if args.command == "add":
            res = store.write_memory(
                topic=args.topic,
                content=args.content,
                category=args.category,
                source=args.source,
                expires_at=args.expires_at,
            )
            return (0 if res["accepted"] else 2), f"{res['status']}: {res}"

        if args.command == "query":
            hits = store.retrieve_memories(query=args.q, now_iso=args.now)
            if not hits:
                return 0, "(无匹配有效记忆)"
            lines = [f"#{h['id']} [{h['category']}] {h['topic']} = {h['content']} {h['citation']}" for h in hits]
            return 0, "\n".join(lines)

        if args.command == "list":
            rows = store.list_memories(include_inactive=args.all)
            if not rows:
                return 0, "(记忆库为空)"
            lines = [
                f"#{r['id']} [{'ACTIVE' if r['active'] else 'INACTIVE'}] [{r['category']}] "
                f"{r['topic']} = {r['content']} (source={r['source']}, trust={r['trust_level']}, superseded_by={r['superseded_by']})"
                for r in rows
            ]
            return 0, "\n".join(lines)

        if args.command in ("delete", "review-pending"):
            # TODO：打通 delete 与 review-pending CLI 命令
            return 1, f"TODO: 请在 starter.py 中补全 {args.command} 命令逻辑"

        return 1, f"未知命令: {args.command}"
    finally:
        store.close()


def main() -> None:
    code, output = run_cli(sys.argv[1:])
    print(output)
    sys.exit(code)


if __name__ == "__main__":
    main()
