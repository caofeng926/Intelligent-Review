# -*- coding: utf-8 -*-
"""
backfill_sn_ms_levels: 补齐 sn_ms_codes 缺失的中间层级行 (L2 / L3 / L4).

为什么需要:
  * `ingest_shanxi_ms.py` 假定所有 sheet 的数据从第 4 行开始, 但 临床介入 / 临床手术 /
    临床康复 这 3 个 sheet 的 L2 行 (32 / 33 / 34) 实际在第 0-3 行, 被 ingest 跳过.
  * 临床诊疗 的 L2 行 (31) 也在被跳过的范围内.
  * 中医类 / 部分医技类 行的 p_code 指向的 L3 (4 位) / L4 (6 位) 在 xlsx 中并不存在
    (xlsx 结构直接 L2 -> L5), 导致 `code LIKE 'xx%' AND level=3` 查不到任何行.

策略:
  1. 找出所有 L5 行引用了不存在的 L3 (4 位) p_code, 反查同 sheet 内 L3 名字 (用第一
     个 L5 子项的名字) 插入.
  2. 找出所有 L3 行引用了不存在的 L2 (2 位) p_code, 用 xlsx 里的原 sheet 标题行附近
     的 L2 名称 (若不可得则从 L3 名字派生) 插入.
  3. 对 L4 (6 位) 引用不存在 L3 的情况也补一遍 (当前数据里没有, 但保留逻辑).

幂等: 全部使用 INSERT OR IGNORE, 可重复执行.

用法 (在 webapp 所在目录下):
    python -m webapp.backfill_sn_ms_levels
    python -m webapp.backfill_sn_ms_levels --dry-run
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "kp.db",
)
XLSX = r"D:\Workspace\医保智审规则库\《陕西省医疗服务项目价格（2021版）》.xlsx"

# 临床四件套的 L2 行 (在 xlsx 里位于第 0-2 行, 被 ingest 跳过). 从 xlsx 抓到的原名.
CLINICAL_L2 = {
    ("临床诊疗", "31"): "(一)临床各系统诊疗",
    ("临床介入", "32"): "(二)经血管介入诊疗",
    ("临床手术", "33"): "（三） 手术治疗",
    ("临床康复", "34"): "(四)物理治疗与康复",
}


def _first_child_name(conn: sqlite3.Connection, sheet: str, parent_code: str,
                      child_level: int) -> str:
    """Return the name of the first child row by code order, or empty string."""
    row = conn.execute(
        "SELECT name FROM sn_ms_codes "
        "WHERE sheet_name=? AND level=? AND p_code=? "
        "ORDER BY code LIMIT 1",
        (sheet, child_level, parent_code),
    ).fetchone()
    return (row[0] or "") if row else ""


def _sheet_title(conn: sqlite3.Connection, sheet: str) -> str:
    row = conn.execute(
        "SELECT sheet_title FROM sn_ms_codes WHERE sheet_name=? LIMIT 1",
        (sheet,),
    ).fetchone()
    return row[0] if row else sheet


def _level_path(sheet: str, level: int, digits: str) -> str:
    parts = [sheet]
    if level >= 2:
        parts.append(digits[:2])
    if level >= 3:
        parts.append(digits[:4])
    if level >= 4:
        parts.append(digits[:6])
    return "|".join(parts)


def _missing_p_codes(conn: sqlite3.Connection, child_level: int,
                     want_level: int) -> list:
    """Return distinct (sheet_name, code) where child_level rows reference a
    want_level p_code that has no row in the table."""
    return list(conn.execute(
        f"""
        SELECT DISTINCT s.sheet_name, s.p_code
        FROM sn_ms_codes s
        WHERE s.level=?
          AND s.p_code IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM sn_ms_codes p
            WHERE p.code=s.p_code AND p.sheet_name=s.sheet_name AND p.level=?
          )
        ORDER BY s.sheet_name, s.p_code
        """,
        (child_level, want_level),
    ))


def backfill_l3_l4(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Insert synthetic L3 / L4 rows for dangling p_code references."""
    inserted = 0
    # L3 from L5 references
    for child_level, want_level, want_digits_len in (
        (5, 3, 4),
        (5, 4, 6),
        (4, 3, 4),
    ):
        for sheet, p_code in _missing_p_codes(conn, child_level, want_level):
            if not p_code or len(p_code) != want_digits_len:
                continue
            name = _first_child_name(conn, sheet, p_code, child_level)
            parent = p_code[:2]
            sheet_title = _sheet_title(conn, sheet)
            level_path = _level_path(sheet, want_level, p_code)
            if dry_run:
                print(f"  [dry-run] L{want_level} {sheet}/{p_code} <- \"{name}\"")
                continue
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO sn_ms_codes
                    (code, p_code, name, level, sheet_name, sheet_title,
                     level_path, fin_class, unit, price_l1, price_l2, price_l3,
                     content, exclude, remark)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL,
                        NULL, NULL, NULL)
                """,
                (p_code, parent, name, want_level, sheet, sheet_title,
                 level_path),
            )
            if cur.rowcount > 0:
                inserted += 1
                print(f"  + L{want_level} {sheet}/{p_code} ({name!r})")
    return inserted


def backfill_l2(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Insert L2 rows for the 4 clinical sheets + any other dangling L2 refs."""
    inserted = 0
    # First: known clinical sheets
    for (sheet, code), name in CLINICAL_L2.items():
        exists = conn.execute(
            "SELECT 1 FROM sn_ms_codes WHERE code=? AND sheet_name=? AND level=2",
            (code, sheet),
        ).fetchone()
        if exists:
            continue
        sheet_title = _sheet_title(conn, sheet)
        level_path = _level_path(sheet, 2, code)
        if dry_run:
            print(f"  [dry-run] L2 {sheet}/{code} <- \"{name}\"")
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO sn_ms_codes
                (code, p_code, name, level, sheet_name, sheet_title,
                 level_path, fin_class, unit, price_l1, price_l2, price_l3,
                 content, exclude, remark)
            VALUES (?, NULL, ?, 2, ?, ?, ?, NULL, NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL)
            """,
            (code, name, sheet, sheet_title, level_path),
        )
        if cur.rowcount > 0:
            inserted += 1
            print(f"  + L2 {sheet}/{code} ({name!r})")
    # Then: any other L3 row whose p_code (2-digit) has no L2 row
    for sheet, p_code in _missing_p_codes(conn, 3, 2):
        # Skip if we just added it in CLINICAL_L2 above (would re-insert OR IGNORE)
        if (sheet, p_code) in CLINICAL_L2:
            continue
        # Try to derive name from any L3 child
        name = _first_child_name(conn, sheet, p_code, 3)
        sheet_title = _sheet_title(conn, sheet)
        level_path = _level_path(sheet, 2, p_code)
        if dry_run:
            print(f"  [dry-run] L2 {sheet}/{p_code} <- \"{name}\"")
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO sn_ms_codes
                (code, p_code, name, level, sheet_name, sheet_title,
                 level_path, fin_class, unit, price_l1, price_l2, price_l3,
                 content, exclude, remark)
            VALUES (?, NULL, ?, 2, ?, ?, ?, NULL, NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL)
            """,
            (p_code, name, sheet, sheet_title, level_path),
        )
        if cur.rowcount > 0:
            inserted += 1
            print(f"  + L2 {sheet}/{p_code} ({name!r})")
    return inserted


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--dry-run", action="store_true",
                   help="只打印要补的行, 不写 DB")
    args = p.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"db not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = OFF")

    print("=== L3 / L4 backfill ===")
    n1 = backfill_l3_l4(conn, dry_run=args.dry_run)
    print(f"  inserted: {n1}")

    print("=== L2 backfill ===")
    n2 = backfill_l2(conn, dry_run=args.dry_run)
    print(f"  inserted: {n2}")

    if not args.dry_run:
        conn.commit()
    conn.close()

    total = n1 + n2
    print(f"\ntotal inserted: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())