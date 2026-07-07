# -*- coding: utf-8 -*-
"""2025 版国家医保药品目录入库脚本

数据源: 原始数据/基本医保药品目录.pdf (2026-07-06 维护)

用法:
  python -m webapp.ingest_yp_2025          # 增量入库 (幂等)
  python -m webapp.ingest_yp_2025 --reset  # 重建表

预期规模 (4 类):
  西药       ~1979 (含 ★ 引用)
  中成药     ~1442 (含 ★ 引用)
  谈判西药   ~396
  谈判中成药 ~73
  中药饮片   ~892 + 1 不得支付
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from .parse_yp_2025 import Drug, parse_pdf, stats
from .db import DB_PATH


DDL = """
CREATE TABLE IF NOT EXISTS yp_catalog_2025 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_no      TEXT NOT NULL DEFAULT '',
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    list_class   TEXT NOT NULL DEFAULT '',
    category_code TEXT NOT NULL DEFAULT '',
    category_name TEXT NOT NULL DEFAULT '',
    dosage_form   TEXT NOT NULL DEFAULT '',
    payment_standard TEXT NOT NULL DEFAULT '',
    payment_validity TEXT NOT NULL DEFAULT '',
    remark       TEXT NOT NULL DEFAULT '',
    star_ref     TEXT NOT NULL DEFAULT '',
    page_no      INTEGER NOT NULL DEFAULT 0,
    version      TEXT NOT NULL DEFAULT '2025',
    UNIQUE(category, list_class, list_no, name, dosage_form, version)
);
CREATE INDEX IF NOT EXISTS idx_yp25_cat ON yp_catalog_2025(category);
CREATE INDEX IF NOT EXISTS idx_yp25_code ON yp_catalog_2025(category_code);
CREATE INDEX IF NOT EXISTS idx_yp25_name ON yp_catalog_2025(name);

CREATE VIRTUAL TABLE IF NOT EXISTS yp_catalog_2025_fts USING fts5(
    name, category_name, dosage_form, remark,
    content='yp_catalog_2025', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS yp25_ai AFTER INSERT ON yp_catalog_2025 BEGIN
    INSERT INTO yp_catalog_2025_fts(rowid, name, category_name, dosage_form, remark)
    VALUES (new.id, new.name, new.category_name, new.dosage_form, new.remark);
END;
CREATE TRIGGER IF NOT EXISTS yp25_ad AFTER DELETE ON yp_catalog_2025 BEGIN
    INSERT INTO yp_catalog_2025_fts(yp_catalog_2025_fts, rowid, name, category_name, dosage_form, remark)
    VALUES ('delete', old.id, old.name, old.category_name, old.dosage_form, old.remark);
END;
CREATE TRIGGER IF NOT EXISTS yp25_au AFTER UPDATE ON yp_catalog_2025 BEGIN
    INSERT INTO yp_catalog_2025_fts(yp_catalog_2025_fts, rowid, name, category_name, dosage_form, remark)
    VALUES ('delete', old.id, old.name, old.category_name, old.dosage_form, old.remark);
    INSERT INTO yp_catalog_2025_fts(rowid, name, category_name, dosage_form, remark)
    VALUES (new.id, new.name, new.category_name, new.dosage_form, new.remark);
END;
"""

BATCH_SOURCE = "yp_catalog_2025"
BATCH_LABEL = "2025版国家医保药品目录 (基本医保药品目录 2026-07-06)"
BATCH_PDF_PATH = r"原始数据/基本医保药品目录.pdf"
BATCH_PUB_DATE = "2026-07-06"


def reset(conn: sqlite3.Connection):
    print("[reset] 删表 + FTS 影子表 ...")
    conn.executescript("""
        DROP TABLE IF EXISTS yp_catalog_2025;
        DROP TABLE IF EXISTS yp_catalog_2025_fts;
        DROP TABLE IF EXISTS yp_catalog_2025_fts_config;
        DROP TABLE IF EXISTS yp_catalog_2025_fts_data;
        DROP TABLE IF EXISTS yp_catalog_2025_fts_docsize;
        DROP TABLE IF EXISTS yp_catalog_2025_fts_idx;
        DROP TRIGGER IF EXISTS yp25_ai;
        DROP TRIGGER IF EXISTS yp25_ad;
        DROP TRIGGER IF EXISTS yp25_au;
    """)
    conn.commit()
    print("[reset] 重建 DDL ...")
    conn.executescript(DDL)
    conn.commit()


def ensure_schema(conn: sqlite3.Connection):
    conn.executescript(DDL)
    conn.commit()


def upsert_batch(conn: sqlite3.Connection) -> str:
    """注册/更新 batch 记录 (用 source 作主键)."""
    cur = conn.execute(
        "SELECT source FROM nhsa_batches WHERE source = ?",
        (BATCH_SOURCE,),
    )
    if cur.fetchone():
        return BATCH_SOURCE
    conn.execute(
        """INSERT INTO nhsa_batches
           (source, batch_label, pub_date, pdf_path, record_count, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            BATCH_SOURCE,
            BATCH_LABEL,
            BATCH_PUB_DATE,
            BATCH_PDF_PATH,
            0,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return BATCH_SOURCE


def insert_drugs(conn: sqlite3.Connection, drugs):
    sql = """
        INSERT OR IGNORE INTO yp_catalog_2025
            (list_no, name, category, list_class, category_code, category_name,
             dosage_form, payment_standard, payment_validity, remark,
             star_ref, page_no, version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            d.list_no, d.name, d.category, d.list_class, d.category_code,
            d.category_name, d.dosage_form, d.payment_standard,
            d.payment_validity, d.remark, d.star_ref, d.page_no, "2025",
        )
        for d in drugs
    ]
    before = conn.total_changes
    conn.executemany(sql, rows)
    conn.commit()
    after = conn.total_changes
    return after - before, len(rows) - (after - before)


def rebuild_fts(conn: sqlite3.Connection):
    conn.execute("INSERT INTO yp_catalog_2025_fts(yp_catalog_2025_fts) VALUES('rebuild')")
    conn.commit()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", default=r"D:\Workspace\医保智审规则库\原始数据\基本医保药品目录.pdf")
    p.add_argument("--reset", action="store_true", help="重建表")
    args = p.parse_args(argv)

    t0 = time.time()
    print(f"[parse] {args.pdf}")
    drugs = parse_pdf(args.pdf)
    print(f"[parse] 共 {len(drugs)} 条, 耗时 {time.time()-t0:.1f}s")
    s = stats(drugs)
    print(f"[parse] 分类: {s['by_category']}")

    print(f"[connect] {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        if args.reset:
            reset(conn)
        else:
            ensure_schema(conn)

        batch_id = upsert_batch(conn)
        print(f"[batch] {batch_id}")

        ins, skp = insert_drugs(conn, drugs)
        print(f"[insert] 新增 {ins}, 跳过 (重复) {skp}, 耗时 {time.time()-t0:.1f}s")

        if args.reset:
            print("[fts] 重建索引 ...")
            rebuild_fts(conn)

        cnt = conn.execute("SELECT COUNT(*) FROM yp_catalog_2025").fetchone()[0]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) FROM yp_catalog_2025 GROUP BY category ORDER BY category"
        ).fetchall()
        print(f"[verify] yp_catalog_2025 总行数: {cnt}")
        for cat, n in by_cat:
            print(f"  {cat}: {n}")

        # 更新 record_count
        conn.execute(
            "UPDATE nhsa_batches SET record_count = ? WHERE source = ?",
            (cnt, BATCH_SOURCE),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"[done] 总耗时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()