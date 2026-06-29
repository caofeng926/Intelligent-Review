"""Ingest the NHSA consumables classification PDF into consumable_codes table.

Source: "医保医用耗材分类与代码_截至2026年5月.pdf"
Format: Each row is exactly 10 consecutive lines in the PDF reading order:
    0: code              (19-digit, starts with C)
    1: cat_l1 + name     (e.g. "01-非血管介入治疗类材料")
    2: cat_l2 + name
    3: cat_l3 + name
    4: generic_category  (e.g. "002-球囊类")
    5: material          (e.g. "15-聚合物")
    6: spec              (e.g. "021-单级")
    7: generic_no        (e.g. "002001")
    8: generic_name      (e.g. "气道球囊扩张导管")
    9: manufacturer      (e.g. "江苏常美医疗器械有限公司")

Page header (skipped):
    Line 0: document title (only on page 1)
    Lines 1-10: column headers (every page)
"""
from __future__ import annotations
import os
import re
import time
from typing import Iterable

from . import db


PDF_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "consumables_db_2026-05.pdf",
)

# Lines that begin with C followed by 18-19 digits are data rows
CODE_RE = re.compile(r"^C\d{18,19}$")
# A "code-name" line like "01-非血管介入治疗类材料"
CAT_RE = re.compile(r"^(\d{2})-")

BATCH = 1000


def split_code_and_name(line: str) -> tuple[str, str]:
    """Split '01-非血管介入治疗类材料' into ('01', '非血管介入治疗类材料')."""
    m = re.match(r"^(\d{2})[-－](.*)$", line.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return "", line.strip()


PAGE_FOOTER_RE = re.compile(r"^第\s*\d+\s*页[\s\S]*$")
GENERIC_NO_RE = re.compile(r"^\d{6}$")


def _strip_footer(row: list[str]) -> list[str]:
    while row and PAGE_FOOTER_RE.match(row[-1].strip()):
        row.pop()
    return row


def _parse_row(raw_row: list[str]):
    """Parse a raw row (list of stripped strings) into structured fields.

    Handles variable-length rows:
      - Strip trailing page footer lines ("第 N 页...").
      - Spec field may span multiple lines; concatenate until we hit a
        6-digit generic_no (or end of row).
      - generic_no / generic_name may be absent for short rows.
    Returns a 13-tuple or None if row is malformed.
    """
    row = _strip_footer(list(raw_row))
    if len(row) < 7:
        return None
    code = row[0]
    l1 = split_code_and_name(row[1])
    l2 = split_code_and_name(row[2])
    l3 = split_code_and_name(row[3])
    generic_category = row[4]
    material = row[5]
    # Scan forward from index 7 to find generic_no (6-digit number).
    idx = 7
    while idx < len(row) and not GENERIC_NO_RE.match(row[idx]):
        idx += 1
    if idx < len(row):
        # Found generic_no at idx: spec is rows[6:idx], possibly multi-line
        spec = " ".join(row[6:idx]).strip()
        generic_no = row[idx]
        idx += 1
        generic_name = row[idx] if idx < len(row) else ""
        idx += 1
        manufacturer = " ".join(row[idx:]).strip() if idx < len(row) else ""
    else:
        # No generic_no found: short row, spec is just row[6], rest is manufacturer
        spec = row[6]
        manufacturer = " ".join(row[7:]).strip() if len(row) > 7 else ""
        generic_no = ""
        generic_name = ""
    return (
        code,
        l1[0], l1[1],
        l2[0], l2[1],
        l3[0], l3[1],
        generic_category, material, spec,
        generic_no, generic_name, manufacturer,
    )


def iter_rows(pdf_path: str) -> Iterable[tuple]:
    """Yield consumable code rows from the PDF.

    PDF row formats observed:
      Full (10 lines): code, l1, l2, l3, generic_category, material, spec,
                       generic_no, generic_name, manufacturer
      Short (8 lines): code, l1, l2, l3, generic_category, material, spec,
                       manufacturer   (generic_no + generic_name omitted)

    Strategy:
    - Read each page, split into non-empty lines.
    - Skip header (anything before the first CODE_RE line).
    - Walk forward: each CODE_RE starts a new row; collect subsequent
      non-CODE_RE lines until the next CODE_RE (or end of page).
    - Map collected fields to (l1, l2, l3, generic_category, material, spec,
      generic_no, generic_name, manufacturer) based on row length.
    """
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        i = 0
        # Skip page header: scan forward to first code line
        while i < len(lines) and not CODE_RE.match(lines[i]):
            i += 1
        while i < len(lines):
            if not CODE_RE.match(lines[i]):
                i += 1
                continue
            # Collect non-CODE_RE lines until next code (or end of page)
            raw = [lines[i]]
            j = i + 1
            while j < len(lines) and not CODE_RE.match(lines[j]):
                raw.append(lines[j])
                j += 1
            i = j
            parsed = _parse_row(raw)
            if parsed is not None:
                yield parsed
    doc.close()


def upsert_many(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    cur = conn.executemany(
        """INSERT OR IGNORE INTO consumable_codes
           (code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name,
            generic_category, material, spec, generic_no, generic_name, manufacturer)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    return cur.rowcount


def main():
    if not os.path.exists(PDF_PATH):
        raise SystemExit(f"PDF not found: {PDF_PATH}")
    print(f"PDF: {PDF_PATH}  ({os.path.getsize(PDF_PATH):,} bytes)")
    print("Parsing...")
    t0 = time.time()
    db.init_db()

    inserted_total = 0
    skipped_total = 0
    batch: list[tuple] = []
    pages_done = 0
    with db.connect() as conn:
        for row in iter_rows(PDF_PATH):
            batch.append(row)
            if len(batch) >= BATCH:
                n = upsert_many(conn, batch)
                inserted_total += n
                skipped_total += len(batch) - n
                batch = []
                if (inserted_total // BATCH) % 10 == 0 and inserted_total > 0:
                    print(f"  inserted={inserted_total:,}  skipped={skipped_total:,}  t={time.time()-t0:.1f}s")
        if batch:
            n = upsert_many(conn, batch)
            inserted_total += n
            skipped_total += len(batch) - n

        # Force FTS index finalize
        conn.execute("INSERT INTO consumable_codes_fts(consumable_codes_fts) VALUES('optimize')")

    print(f"=== Done: inserted={inserted_total:,}  skipped={skipped_total:,}  t={time.time()-t0:.1f}s ===")


if __name__ == "__main__":
    main()
