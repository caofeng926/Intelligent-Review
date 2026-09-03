"""Ingest the NHSA consumables CSV (from API) into consumable_codes table.

Source: 原始数据/HC/医保医用耗材_YYYYMMDD.csv (downloaded from NHSA API)
Drops any codes that were in the previous PDF-based version but no longer
in the latest CSV (i.e. retired codes).
"""
from __future__ import annotations
import csv
import os
import re
import sqlite3
import time
from datetime import datetime
from typing import Iterable

from . import db


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "原始数据")

CSV_PATH = os.path.join(DATA_DIR, "HC", "医保医用耗材_20260626.csv")

BATCH = 5000


def _split_code_name(v: str) -> tuple[str, str]:
    """'01-非血管介入治疗类材料' -> ('01', '非血管介入治疗类材料')."""
    if not v:
        return "", ""
    m = re.match(r"^(\d{2})[-－—](.*)$", v.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", v.strip()


def iter_rows(csv_path: str) -> Iterable[tuple]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            l1 = _split_code_name(r.get("一级分类（学科、 品类）", ""))
            l2 = _split_code_name(r.get("二级分类（用途、 品目）", ""))
            l3 = _split_code_name(r.get("三级分类（部位、功能、 品种）", ""))
            yield (
                r.get("耗材代码", "").strip(),
                l1[0], l1[1], l2[0], l2[1], l3[0], l3[1],
                r.get("医保通用名分类", "").strip(),
                r.get("耗材材质", "").strip(),
                r.get("规格（特征、参数）", "").strip(),
                r.get("医保通用名编号", "").strip(),
                r.get("医保通用名", "").strip(),
                r.get("耗材企业", "").strip(),
            )


def main():
    if not os.path.exists(CSV_PATH):
        raise SystemExit(f"CSV not found: {CSV_PATH}")
    print(f"CSV: {CSV_PATH}  ({os.path.getsize(CSV_PATH):,} bytes)")
    t0 = time.time()
    db.init_db()

    inserted = 0
    new_codes: set[str] = set()
    batch: list[tuple] = []
    with db.connect() as conn:
        # 1) Collect new codes (for diff after)
        for row in iter_rows(CSV_PATH):
            new_codes.add(row[0])
        print(f"  CSV unique codes: {len(new_codes)}")

        # 2) Find which existing codes will be dropped
        old_codes = set(r[0] for r in conn.execute("SELECT code FROM consumable_codes").fetchall())
        to_drop = old_codes - new_codes
        print(f"  old codes: {len(old_codes)}, will drop: {len(to_drop)}")

        # 3) Delete codes that no longer exist in new CSV
        if to_drop:
            chunk = 5000
            drop_list = list(to_drop)
            for i in range(0, len(drop_list), chunk):
                qmarks = ",".join("?" for _ in drop_list[i:i+chunk])
                conn.execute(f"DELETE FROM consumable_codes WHERE code IN ({qmarks})",
                             drop_list[i:i+chunk])
            print(f"  deleted {len(to_drop)} retired codes")

        # 4) Insert / replace new rows
        for row in iter_rows(CSV_PATH):
            batch.append(row)
            if len(batch) >= BATCH:
                conn.executemany(
                    """INSERT OR REPLACE INTO consumable_codes(
                        code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name,
                        generic_category, material, spec, generic_no, generic_name, manufacturer)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    batch,
                )
                inserted += len(batch)
                batch = []
                if inserted % (BATCH * 4) == 0:
                    print(f"  inserted={inserted:,} t={time.time()-t0:.1f}s")
        if batch:
            conn.executemany(
                """INSERT OR REPLACE INTO consumable_codes(
                    code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name,
                    generic_category, material, spec, generic_no, generic_name, manufacturer)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                batch,
            )
            inserted += len(batch)

        # 5) FTS rebuild
        conn.execute("INSERT INTO consumable_codes_fts(consumable_codes_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO consumable_codes_fts(consumable_codes_fts) VALUES('optimize')")

        # 6) Update nhsa_batches
        conn.execute(
            """INSERT OR REPLACE INTO nhsa_batches(
                source, batch_label, pub_date, csv_path, record_count, sysflag, ingested_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("consumable_codes", "医保医用耗材分类与代码 2026-06-26 (CSV)",
             "2026-06-26", CSV_PATH, len(new_codes), "1375",
             datetime.utcnow().isoformat()),
        )
        new_total = conn.execute("SELECT COUNT(*) FROM consumable_codes").fetchone()[0]

    print(f"=== Done ===")
    print(f"  inserted/updated: {inserted:,}")
    print(f"  dropped: {len(to_drop):,}")
    print(f"  final row count: {new_total:,}")
    print(f"  elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()