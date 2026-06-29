"""Ingest the NHSA reference databases (downloaded CSVs / JSONs) into kp.db.

Usage:
  python -m webapp.ingest_nhsa_dbs
"""
from __future__ import annotations
import csv
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Iterable

from . import db

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "原始数据")


def _csv_iter(path: str) -> Iterable[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {k: (v if v is not None else "") for k, v in row.items()}


def _split_code_name(v: str) -> tuple[str, str]:
    """'01-呼吸介入材料' -> ('01', '呼吸介入材料')."""
    if not v:
        return "", ""
    m = re.match(r"^(\d{2})[-－—](.*)$", v.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", v.strip()


# -------------------- IVD --------------------
def ingest_ivd(conn: sqlite3.Connection, csv_path: str, sysflag: str, batch_label: str, pub_date: str) -> int:
    rows = []
    for r in _csv_iter(csv_path):
        c1, n1 = _split_code_name(r.get("一级分类（方法学、专业）", ""))
        c2, n2 = _split_code_name(r.get("二级分类（原理、路径）", ""))
        c3, n3 = _split_code_name(r.get("三级分类（用途、品种）", ""))
        rows.append((
            r.get("体外诊断试剂代码", "").strip(),
            c1, n1, c2, n2, c3, n3,
            r.get("检测类别", "").strip(),
            r.get("检测指标", "").strip(),
            r.get("应用方式", "").strip(),
            r.get("检测类型", "").strip(),
            r.get("企业名称", "").strip(),
            "",  # business_license (not in PDF)
            "",  # spec_code
            f"{n1}/{n2}/{n3}" if (n1 or n2 or n3) else "",
        ))
    conn.execute("DELETE FROM ivd_codes")
    conn.executemany(
        """INSERT OR REPLACE INTO ivd_codes(
            code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name,
            testing_category, testing_index, use_type, check_type,
            company_name, business_license, spec_code, catalog_full_name)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    n = len(rows)
    conn.execute(
        """INSERT OR REPLACE INTO nhsa_batches(source, batch_label, pub_date, csv_path, record_count, sysflag, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("ivd_codes", batch_label, pub_date, csv_path, n, sysflag, datetime.utcnow().isoformat()),
    )
    return n


# -------------------- HC7 (7 类医用耗材) --------------------
def ingest_hc7(conn: sqlite3.Connection, csv_path: str, sysflag: str, batch_label: str, pub_date: str) -> int:
    rows = []
    for r in _csv_iter(csv_path):
        c1, n1 = _split_code_name(r.get("一级分类", ""))
        c2, n2 = _split_code_name(r.get("二级分类", ""))
        c3, n3 = _split_code_name(r.get("三级分类", ""))
        rows.append((
            r.get("耗材代码", "").strip(),
            c1, n1, c2, n2, c3, n3,
            r.get("医保通用名分类", "").strip(),
            r.get("耗材材质", "").strip(),
            r.get("规格（特征、参数）", "").strip(),
            r.get("医保通用名编号", "").strip(),
            r.get("医保通用名", "").strip(),
            r.get("耗材企业", "").strip(),
        ))
    conn.execute("DELETE FROM consumable7_codes")
    conn.executemany(
        """INSERT OR REPLACE INTO consumable7_codes(
            code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name,
            generic_category, material, spec, generic_no, generic_name, manufacturer)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    n = len(rows)
    conn.execute(
        """INSERT OR REPLACE INTO nhsa_batches(source, batch_label, pub_date, csv_path, record_count, sysflag, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("consumable7_codes", batch_label, pub_date, csv_path, n, sysflag, datetime.utcnow().isoformat()),
    )
    return n


# -------------------- ICD --------------------
def ingest_icd(conn: sqlite3.Connection, csv_path: str, sysflag: str, batch_label: str, pub_date: str) -> int:
    rows = []
    for r in _csv_iter(csv_path):
        diag_code = r.get("诊断代码", "").strip()
        if not diag_code:
            continue
        rows.append((
            diag_code,
            r.get("章", "").strip(),
            r.get("章代码范围", "").strip(),
            r.get("章的名称", "").strip(),
            r.get("节代码范围", "").strip(),
            r.get("节名称", "").strip(),
            r.get("类目代码", "").strip(),
            r.get("类目名称", "").strip(),
            r.get("亚目代码", "").strip(),
            r.get("亚目名称", "").strip(),
            diag_code,
            r.get("诊断名称", "").strip(),
        ))
    conn.execute("DELETE FROM icd_codes")
    conn.executemany(
        """INSERT OR REPLACE INTO icd_codes(
            code, chapter_no, chapter_range, chapter_name,
            section_range, section_name, category_code, category_name,
            subcategory_code, subcategory_name, diagnosis_code, diagnosis_name)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    n = len(rows)
    conn.execute(
        """INSERT OR REPLACE INTO nhsa_batches(source, batch_label, pub_date, csv_path, record_count, sysflag, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("icd_codes", batch_label, pub_date, csv_path, n, sysflag, datetime.utcnow().isoformat()),
    )
    return n


# -------------------- MS (医疗服务项目) --------------------
def ingest_ms(conn: sqlite3.Connection, json_path: str, sysflag: str, batch_label: str, pub_date: str) -> int:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for item in data:
        rows.append((
            item.get("msCode", "").strip() if isinstance(item.get("msCode"), str) else str(item.get("msCode", "")),
            item.get("msPid", "") if item.get("msPid") else "",
            item.get("msName", ""),
            int(item.get("level", 0) or 0),
            item.get("levelPath", ""),
            "",
            item.get("containsContent", ""),
            item.get("excludedContent", ""),
            item.get("chargeUnit", ""),
            item.get("explain", ""),
            item.get("area", ""),
            int(item.get("isusing", 0) or 0),
        ))
    conn.execute("DELETE FROM medical_service_codes")
    conn.executemany(
        """INSERT OR REPLACE INTO medical_service_codes(
            code, p_code, name, level, level_path, pinyin_code,
            contains_content, excluded_content, charge_unit, explain, area, is_using)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    n = len(rows)
    conn.execute(
        """INSERT OR REPLACE INTO nhsa_batches(source, batch_label, pub_date, json_path, record_count, sysflag, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("medical_service_codes", batch_label, pub_date, json_path, n, sysflag, datetime.utcnow().isoformat()),
    )
    return n


# -------------------- TCM (中医) --------------------
def ingest_tcm(conn: sqlite3.Connection, json_path: str, sysflag: str, batch_label: str, pub_date: str) -> int:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("B") if isinstance(data, dict) else data
    rows = []
    for item in (items or []):
        rows.append((
            item.get("tcmCode", "").strip(),
            item.get("tcmPid", ""),
            item.get("tcmName", ""),
            item.get("partcode", ""),
            int(item.get("codelength", 0) or 0),
            int(item.get("level", 0) or 0),
            item.get("applyExplain", ""),
            item.get("remark", ""),
            item.get("classCode", ""),
            item.get("className", ""),
        ))
    conn.execute("DELETE FROM tcm_codes")
    conn.executemany(
        """INSERT OR REPLACE INTO tcm_codes(
            code, p_code, name, part_code, code_length, level,
            apply_explain, remark, class_code, class_name)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    n = len(rows)
    conn.execute(
        """INSERT OR REPLACE INTO nhsa_batches(source, batch_label, pub_date, json_path, record_count, sysflag, ingested_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("tcm_codes", batch_label, pub_date, json_path, n, sysflag, datetime.utcnow().isoformat()),
    )
    return n


# -------------------- MAIN --------------------
def main():
    specs = [
        ("IVD", "ivd_codes", "1371", "医保体外诊断试剂分类与代码 2026-06-11", "2026-06-11",
         os.path.join(DATA_DIR, "IVD", "体外诊断试剂_20260611.csv")),
        ("HC7", "consumable7_codes", "1309", "血管介入支架等7类医保医用耗材 2025-09-01", "2025-09-01",
         os.path.join(DATA_DIR, "HC7", "7类医用耗材_20250901.csv")),
        ("ICD", "icd_codes", "80", "ICD-10/ICD-9-CM3 医保2.0版 2021-01-14", "2021-01-14",
         os.path.join(DATA_DIR, "ICD", "ICD_20210114.csv")),
        ("MS", "medical_service_codes", "81", "全国医疗服务项目", "2019-06-27",
         os.path.join(DATA_DIR, "MS", "all.json")),
        ("TCM", "tcm_codes", "1057", "中医疾病/证候医保2.0版 2022-01-01", "2022-01-01",
         os.path.join(DATA_DIR, "TCM", "all.json")),
    ]

    with db.connect() as conn:
        # Ensure schema is up to date (init_db runs EXTRA_SCHEMA)
        db.init_db()

        for short, src, sysflag, batch_label, pub_date, path in specs:
            if not os.path.exists(path):
                print(f"[{short}] MISSING: {path}")
                continue
            print(f"[{short}] ingesting from {path}")
            if src == "ivd_codes":
                n = ingest_ivd(conn, path, sysflag, batch_label, pub_date)
            elif src == "consumable7_codes":
                n = ingest_hc7(conn, path, sysflag, batch_label, pub_date)
            elif src == "icd_codes":
                n = ingest_icd(conn, path, sysflag, batch_label, pub_date)
            elif src == "medical_service_codes":
                n = ingest_ms(conn, path, sysflag, batch_label, pub_date)
            elif src == "tcm_codes":
                n = ingest_tcm(conn, path, sysflag, batch_label, pub_date)
            print(f"[{short}] inserted {n} rows")

        print("\n=== Final row counts ===")
        for t in ["ivd_codes", "consumable7_codes", "icd_codes",
                  "medical_service_codes", "tcm_codes", "nhsa_batches"]:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {cnt} rows")


if __name__ == "__main__":
    main()
