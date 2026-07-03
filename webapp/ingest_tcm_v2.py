"""Ingest NHSA TCM codes (B + Z, 疾病 + 证候) into tcm_codes table.

Source: 原始数据/TCM/all.json (downloaded from NHSA API toStdTcmTreeList)
Drops codes that no longer exist in the new version.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime

from . import db


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "原始数据")
JSON_PATH = os.path.join(DATA_DIR, "TCM", "all.json")


def main():
    if not os.path.exists(JSON_PATH):
        raise SystemExit(f"JSON not found: {JSON_PATH}")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        items = data.get("B", []) + data.get("Z", [])
    else:
        items = data
    print(f"Source: {JSON_PATH}  ({os.path.getsize(JSON_PATH):,} bytes)")
    print(f"Total nodes: {len(items)}")
    print(f"  B (疾病): {sum(1 for n in items if n.get('partcode') == 'B')}")
    print(f"  Z (证候): {sum(1 for n in items if n.get('partcode') == 'Z')}")

    db.init_db()
    with db.connect() as conn:
        # Build rows
        rows = []
        new_codes = set()
        for item in items:
            code = (item.get("tcmCode") or "").strip()
            if not code: continue
            new_codes.add(code)
            rows.append((
                code,
                item.get("tcmPid") or "",
                item.get("tcmName") or "",
                item.get("partcode") or "",
                int(item.get("codelength") or 0),
                int(item.get("level") or 0),
                item.get("applyExplain") or "",
                item.get("remark") or "",
                item.get("classCode") or "",
                item.get("className") or "",
            ))
        # Diff
        old_codes = set(r[0] for r in conn.execute("SELECT code FROM tcm_codes").fetchall())
        to_drop = old_codes - new_codes
        to_add = new_codes - old_codes
        print(f"\nDB old: {len(old_codes)}, will drop: {len(to_drop)}, will add: {len(to_add)}")

        # Delete old
        if to_drop:
            drop_list = list(to_drop)
            chunk = 1000
            for i in range(0, len(drop_list), chunk):
                qmarks = ",".join("?" for _ in drop_list[i:i+chunk])
                conn.execute(f"DELETE FROM tcm_codes WHERE code IN ({qmarks})", drop_list[i:i+chunk])
        # Insert/replace
        conn.executemany(
            """INSERT OR REPLACE INTO tcm_codes(
                code, p_code, name, part_code, code_length, level,
                apply_explain, remark, class_code, class_name)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        # FTS rebuild
        conn.execute("INSERT INTO tcm_codes_fts(tcm_codes_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO tcm_codes_fts(tcm_codes_fts) VALUES('optimize')")
        # Update nhsa_batches
        conn.execute(
            """INSERT OR REPLACE INTO nhsa_batches(
                source, batch_label, pub_date, json_path, record_count, sysflag, ingested_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("tcm_codes", "中医疾病/证候医保2.0版 (NHSA API 2026-06-30)",
             "2022-01-01", JSON_PATH, len(new_codes), "1057",
             datetime.utcnow().isoformat()),
        )
        new_total = conn.execute("SELECT COUNT(*) FROM tcm_codes").fetchone()[0]
        b_cnt = conn.execute("SELECT COUNT(*) FROM tcm_codes WHERE part_code='B'").fetchone()[0]
        z_cnt = conn.execute("SELECT COUNT(*) FROM tcm_codes WHERE part_code='Z'").fetchone()[0]
    print(f"\n=== Done ===")
    print(f"  final total: {new_total} (B={b_cnt}, Z={z_cnt})")
    print(f"  added: {len(to_add)}, dropped: {len(to_drop)}")


if __name__ == "__main__":
    main()