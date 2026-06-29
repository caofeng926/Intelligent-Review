"""CLI search: cross-source FTS5 query of knowledge points."""
from __future__ import annotations
import os
import sys
import argparse
import time
import json

import sqlite3
from . import db


def highlight(text: str, query: str) -> str:
    if not text or not query:
        return text or ""
    # simple Chinese-aware highlight: substring match
    out = text
    for q in query.split():
        if q and q in out:
            out = out.replace(q, f"[{q}]")
    return out


def main():
    ap = argparse.ArgumentParser(description="Search 医保智审知识库 (XLSX + PDF).")
    ap.add_argument("query", help="search keywords")
    ap.add_argument("--source", choices=("nhsa_batch", "pdf_2025"), help="filter by source")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    t0 = time.time()
    with db.connect() as conn:
        sql = """
            WITH q AS (SELECT rowid, bm25(kp_fts) AS score FROM kp_fts WHERE kp_fts MATCH ?)
            SELECT kp.id, kp.subject_name, kp.detection_logic, kp.logic_basis,
                   kp.codes, kp.code_count, kp.remark,
                   r.rule_subject, r.source, b.batch_label, b.pub_date,
                   q.score
            FROM knowledge_points kp
            JOIN rules r ON r.id = kp.rule_id
            JOIN batches b ON b.id = r.batch_id
            JOIN q ON q.rowid = kp.id
        """
        # append * for prefix matching (FTS5 + unicode61 on CJK)
        q = args.query if args.query.endswith("*") or " " in args.query else args.query + "*"
        params = [q]
        if args.source:
            sql += " AND r.source = ?"
            params.append(args.source)
        sql += " ORDER BY q.score LIMIT ?"
        params.append(args.limit)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    elapsed_ms = (time.time() - t0) * 1000

    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return

    print(f"\nquery: {args.query!r}  |  hits: {len(rows)}  |  {elapsed_ms:.1f} ms")
    print("=" * 80)
    for i, r in enumerate(rows, 1):
        sn = highlight((r["subject_name"] or "")[:60], args.query)
        dl = highlight((r["detection_logic"] or "")[:120], args.query)
        print(f"\n[{i}] [{r['source']}] {r['batch_label']}  ·  {r['rule_subject']}")
        print(f"    对象: {sn}")
        print(f"    逻辑: {dl}{'…' if len(r['detection_logic'] or '') > 120 else ''}")
        if r["codes"]:
            print(f"    代码: {(r['codes'] or '')[:60]}")
        if r["code_count"]:
            print(f"    代码数: {r['code_count']}")
    print()


if __name__ == "__main__":
    main()
