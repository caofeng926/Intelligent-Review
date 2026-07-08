# -*- coding: utf-8 -*-
"""2025 版陕西医保药品目录入库脚本

数据源: 原始数据/基本医保药品目录.pdf (2026-07-06 维护, 202 页)

用法:
  python -m webapp.ingest_yp_sx_2025          # 增量入库 (幂等)
  python -m webapp.ingest_yp_sx_2025 --reset  # 重建表

预期规模 (5 类):
  西药       ~1979 (含 ★ 引用)
  中成药     ~1442 (含 ★ 引用)
  谈判西药   ~396
  谈判中成药 ~73
  中药饮片   ~892 + 1 不得支付
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from .parse_yp_2025 import Drug, parse_pdf, stats
from .db import DB_PATH


DDL = """
CREATE TABLE IF NOT EXISTS yp_catalog_sx_2025 (
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
    region       TEXT NOT NULL DEFAULT 'shaanxi',
    UNIQUE(category, list_class, list_no, name, dosage_form, region)
);
CREATE INDEX IF NOT EXISTS idx_yp25sx_cat   ON yp_catalog_sx_2025(category);
CREATE INDEX IF NOT EXISTS idx_yp25sx_code  ON yp_catalog_sx_2025(category_code);
CREATE INDEX IF NOT EXISTS idx_yp25sx_name  ON yp_catalog_sx_2025(name);

CREATE VIRTUAL TABLE IF NOT EXISTS yp_catalog_sx_2025_fts USING fts5(
    name, category_name, dosage_form, remark,
    content='yp_catalog_sx_2025', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS yp25sx_ai AFTER INSERT ON yp_catalog_sx_2025 BEGIN
    INSERT INTO yp_catalog_sx_2025_fts(rowid, name, category_name, dosage_form, remark)
    VALUES (new.id, new.name, new.category_name, new.dosage_form, new.remark);
END;
CREATE TRIGGER IF NOT EXISTS yp25sx_ad AFTER DELETE ON yp_catalog_sx_2025 BEGIN
    INSERT INTO yp_catalog_sx_2025_fts(yp_catalog_sx_2025_fts, rowid, name, category_name, dosage_form, remark)
    VALUES ('delete', old.id, old.name, old.category_name, old.dosage_form, old.remark);
END;
CREATE TRIGGER IF NOT EXISTS yp25sx_au AFTER UPDATE ON yp_catalog_sx_2025 BEGIN
    INSERT INTO yp_catalog_sx_2025_fts(yp_catalog_sx_2025_fts, rowid, name, category_name, dosage_form, remark)
    VALUES ('delete', old.id, old.name, old.category_name, old.dosage_form, old.remark);
    INSERT INTO yp_catalog_sx_2025_fts(rowid, name, category_name, dosage_form, remark)
    VALUES (new.id, new.name, new.category_name, new.dosage_form, new.remark);
END;

CREATE TABLE IF NOT EXISTS yp25sx_category_tree (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    level       INTEGER NOT NULL,
    parent_code TEXT,
    drug_count  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(category, code)
);
CREATE INDEX IF NOT EXISTS idx_yp25sx_tree_l1 ON yp25sx_category_tree(category, level);
CREATE INDEX IF NOT EXISTS idx_yp25sx_tree_p  ON yp25sx_category_tree(category, parent_code);
"""

BATCH_SOURCE = "yp_catalog_sx_2025"
BATCH_LABEL = "2025版陕西省医保药品目录 (基本医保药品目录 2026-07-06)"
BATCH_PDF_PATH = r"原始数据/基本医保药品目录.pdf"
BATCH_PUB_DATE = "2026-07-06"

RE_TOP_LIKE = re.compile(r"^([XZ][A-Z])")  # 顶层 2 字符: XA / ZA


def reset(conn: sqlite3.Connection):
    print("[reset] 删表 + FTS 影子表 ...")
    conn.executescript("""
        DROP TABLE IF EXISTS yp_catalog_sx_2025;
        DROP TABLE IF EXISTS yp_catalog_sx_2025_fts;
        DROP TABLE IF EXISTS yp_catalog_sx_2025_fts_config;
        DROP TABLE IF EXISTS yp_catalog_sx_2025_fts_data;
        DROP TABLE IF EXISTS yp_catalog_sx_2025_fts_docsize;
        DROP TABLE IF EXISTS yp_catalog_sx_2025_fts_idx;
        DROP TABLE IF EXISTS yp25sx_category_tree;
        DROP TRIGGER IF EXISTS yp25sx_ai;
        DROP TRIGGER IF EXISTS yp25sx_ad;
        DROP TRIGGER IF EXISTS yp25sx_au;
    """)
    conn.commit()
    print("[reset] 重建 DDL ...")
    conn.executescript(DDL)
    conn.commit()


def ensure_schema(conn: sqlite3.Connection):
    conn.executescript(DDL)
    conn.commit()


def upsert_batch(conn: sqlite3.Connection) -> str:
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
        (BATCH_SOURCE, BATCH_LABEL, BATCH_PUB_DATE, BATCH_PDF_PATH, 0,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return BATCH_SOURCE


def insert_drugs(conn: sqlite3.Connection, drugs):
    sql = """
        INSERT OR IGNORE INTO yp_catalog_sx_2025
            (list_no, name, category, list_class, category_code, category_name,
             dosage_form, payment_standard, payment_validity, remark,
             star_ref, page_no, version, region)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            d.list_no, d.name, d.category, d.list_class, d.category_code,
            d.category_name, d.dosage_form, d.payment_standard,
            d.payment_validity, d.remark, d.star_ref, d.page_no, "2025", "shaanxi",
        )
        for d in drugs
    ]
    cur = conn.executemany(sql, rows)
    conn.commit()
    return cur.rowcount, len(rows) - cur.rowcount


def rebuild_fts(conn: sqlite3.Connection):
    conn.execute("INSERT INTO yp_catalog_sx_2025_fts(yp_catalog_sx_2025_fts) VALUES('rebuild')")
    conn.commit()


def rebuild_category_tree(conn: sqlite3.Connection):
    """从 yp_catalog_sx_2025 重建 yp25sx_category_tree.

    顶层 code (XA / XB / ... / ZA / ZB / ...) 在 drug 行里不会直接出现,
    但可由 sub-code 的 2 字符前缀推断. 顶层名称优先从 yp25_category_tree (国家版同源) 复用,
    找不到时回退到内置映射.
    """
    # 清空旧树
    conn.execute("DELETE FROM yp25sx_category_tree")

    # 从数据里抽出 (category, category_code, category_name) 去重
    rows = conn.execute("""
        SELECT DISTINCT category, category_code, category_name
        FROM yp_catalog_sx_2025
        WHERE category_code <> ''
    """).fetchall()

    by_code: dict = {}
    for cat, code, name in rows:
        by_code.setdefault((cat, code), name)

    # 推断顶层 code 集合 (从 sub-code 提 2 字符前缀)
    inferred_tops = set()
    for (cat, code) in by_code.keys():
        if len(code) >= 2:
            inferred_tops.add((cat, code[:2]))

    # 顶层名称优先从 yp25_category_tree (国家版) 复用
    national_tops = {}
    for r in conn.execute(
        "SELECT category, code, name FROM yp25_category_tree WHERE level = 1"
    ).fetchall():
        national_tops[(r[0], r[1])] = r[2]

    # 内置兜底映射 (PDF 凡例 + 历年目录约定)
    BUILTIN_TOPS = {
        ("西药", "XA"): "消化道和代谢方面的药物",
        ("西药", "XB"): "血液和造血器官药",
        ("西药", "XC"): "心血管系统",
        ("西药", "XD"): "皮肤病用药",
        ("西药", "XF"): "肌肉-骨骼系统",
        ("西药", "XG"): "泌尿生殖系统药和性激素",
        ("西药", "XH"): "系统用激素类(不含性激素)",
        ("西药", "XJ"): "全身用抗感染药",
        ("西药", "XL"): "抗肿瘤药及免疫调节剂",
        ("西药", "XM"): "肌肉-骨骼系统",
        ("西药", "XN"): "神经系统药物",
        ("西药", "XR"): "呼吸系统",
        ("西药", "XS"): "感觉器官药物",
        ("西药", "XV"): "其他",
        ("中成药", "ZA"): "内科用药",
        ("中成药", "ZB"): "外科用药",
        ("中成药", "ZC"): "肿瘤用药",
        ("中成药", "ZD"): "妇科用药",
        ("中成药", "ZE"): "眼科用药",
        ("中成药", "ZF"): "耳鼻喉科用药",
        ("中成药", "ZG"): "骨伤科用药",
        ("中成药", "ZH"): "民族药",
        ("中成药", "ZI"): "其他",
        ("谈判西药", "XA"): "消化道和代谢方面的药物",
        ("谈判中成药", "ZA"): "内科用药",
    }

    inserted = 0
    # 1) 顶层
    for cat, code in sorted(inferred_tops):
        name = national_tops.get((cat, code)) or BUILTIN_TOPS.get((cat, code)) or code
        conn.execute(
            """INSERT OR IGNORE INTO yp25sx_category_tree
               (category, code, name, level, parent_code, drug_count)
               VALUES (?, ?, ?, 1, NULL, 0)""",
            (cat, code, name),
        )
        inserted += 1

    # 2) 子分类: 长度 > 2 且与任何顶层前缀匹配
    inferred_top_set = inferred_tops
    for (cat, code), name in sorted(by_code.items()):
        if (cat, code) in inferred_top_set:
            continue
        if len(code) <= 2:
            continue
        prefix = code[:2]
        if (cat, prefix) not in inferred_top_set:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO yp25sx_category_tree
               (category, code, name, level, parent_code, drug_count)
               VALUES (?, ?, ?, 2, ?, 0)""",
            (cat, code, name, prefix),
        )
        inserted += 1

    conn.commit()

    # 更新 drug_count
    conn.execute("""
        UPDATE yp25sx_category_tree SET drug_count = (
            SELECT COUNT(*) FROM yp_catalog_sx_2025 d
            WHERE d.category = yp25sx_category_tree.category
              AND d.category_code = yp25sx_category_tree.code
        )
    """)
    conn.commit()

    n_top = conn.execute("SELECT COUNT(*) FROM yp25sx_category_tree WHERE level = 1").fetchone()[0]
    n_sub = conn.execute("SELECT COUNT(*) FROM yp25sx_category_tree WHERE level = 2").fetchone()[0]
    print(f"[tree] 顶层 {n_top} + 子分类 {n_sub} = {inserted} 个节点")
    return inserted


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

        # 重建分类树 (每次都重建, 以保证 drug_count 与数据一致)
        rebuild_category_tree(conn)

        cnt = conn.execute("SELECT COUNT(*) FROM yp_catalog_sx_2025").fetchone()[0]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) FROM yp_catalog_sx_2025 GROUP BY category ORDER BY category"
        ).fetchall()
        print(f"[verify] yp_catalog_sx_2025 总行数: {cnt}")
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
