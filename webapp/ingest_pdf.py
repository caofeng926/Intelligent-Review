"""Ingest 2025-edition consolidated PDF into the unified database."""
from __future__ import annotations
import os
import re
import json
import argparse
from typing import Optional

import fitz
import pdfplumber

from . import db

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(PROJECT_ROOT, "医疗保障基金智能监管规则库、知识库（2025年版）.pdf")
SOURCE = "pdf_2025"
PDF_BATCH_LABEL = "2025版合并版(自PDF)"

RULE_HEADING_RE = re.compile(
    r"[“”]([^“”]+)[“”]\s*规则对应知识点明细(?:（表\d+）)?"
)
CJK_NUM = "一二二三四五六七八九十"

OBJECT_TYPE_MAP = [
    ("tcm_decoction", ["中药饮片"]),
    ("tcm", ["中药"]),
    ("consumable", ["耗材"]),
    ("service", ["医疗服务项目", "项目分解", "手术操作", "手术项目", "手术", "诊断"]),
    ("pair", ["重复收费", "分解收费"]),
]

# ---- category inference (from rule_subject + category prefix) ----

def infer_category(rule_subject: str) -> str:
    s = rule_subject
    # 政策类
    if any(k in s for k in ("限工伤", "限生育", "限二线", "限适应症", "限支付疗程", "限医疗机构级别", "限就医方式", "互联网医院", "中药饮片单复方", "中药饮片单方", "耗材限新生儿", "耗材限儿童")):
        if "中药" in s or "耗材" in s or any(k in s for k in ("工伤", "生育", "二线", "适应症", "支付疗程", "医疗机构级别", "就医方式", "互联网医院")):
            return "政策-药品" if ("耗材" not in s and "中药" not in s) or any(k in s for k in ("工伤","生育","二线","适应症","支付疗程","医疗机构级别","就医方式","互联网医院")) else None
        return "政策-服务"
    if any(k in s for k in ("手术项目", "重复收费", "分解收费", "限定频次", "限年龄", "周期超频次", "医疗服务项目")):
        return "政策-服务"
    if "耗材" in s and ("新生儿" in s or "儿童" in s):
        return "政策-耗材"
    # 管理类
    if any(k in s for k in ("编码与性别不符", "编码与手术操作编码不符", "诊断与患者", "诊断与手术", "手术操作编码")):
        return "管理-信息"
    if "围手术期" in s or "互联网医院" in s:
        return "管理-药品"
    if "诊断与患者" in s:
        return "管理-行为"
    # 医疗类
    if any(k in s for k in ("儿童专用", "儿童禁用", "区分性别", "超说明书", "禁忌症", "禁忌", "超量", "超大处方", "重复开药", "相互作用", "配伍", "老年人", "妊娠期")):
        return "医疗-药品"
    if any(k in s for k in ("无指征", "医疗服务项目儿童专用", "医疗服务项目区分性别", "医疗服务项目禁忌", "医疗服务项目超适应症")):
        return "医疗-服务"
    if "耗材" in s and ("性别不符" in s or "限疾病" in s):
        return "医疗-耗材"
    return "其他"


def infer_object_type(rule_subject: str) -> str:
    for otype, keys in OBJECT_TYPE_MAP:
        for k in keys:
            if k in rule_subject:
                return otype
    return "drug"


# ---- column-header fingerprint ----

def col_role(header_text: str) -> Optional[str]:
    if not header_text:
        return None
    h = re.sub(r"\s+", "", header_text)
    if h in ("序号", "对应知识点序号", "知识点序号"):
        return "seq"
    if h == "医疗服务项目B名称":
        return "subject_name_b"
    if h in ("药品通用名", "医疗服务项目名称", "中药饮片名称", "项目A名称", "项目B名称",
             "医疗服务项目A名称",
             "医用耗材的名称/产品名称", "医用耗材的名称产品名称",
             "耗材名称/产品名称", "耗材名称产品名称", "耗材名称", "产品名称",
             "医用耗材单件产品名称", "耗材单件产品名称", "耗材的类别/产品名称",
             "耗材的类别产品名称", "耗材的类别名称"):
        return "subject_name"
    if h in ("检出逻辑",):
        return "detection_logic"
    if h.startswith("逻辑依据"):
        return "logic_basis"
    if "知识点对应" in h and "数量" in h:
        return "code_count"
    if h in ("限定性别", "时间区间", "单日上限数量"):
        return "remark"
    if h.startswith("项目代码") or h.startswith("药品代码") or h.startswith("中药饮片代码") or h.startswith("医疗服务项目代码") or h == "药品代码":
        return "codes"
    # special: 手术操作编码/诊断编码 (ICD codes) — store in codes
    if h.startswith("手术操作编码") or h.startswith("诊断编码"):
        return "codes"
    if h.startswith("手术操作名称") or h.startswith("诊断名称"):
        return "subject_name"
    if h in ("备注",):
        return "remark"
    return None


def to_int(v) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None


def is_banner_table(table) -> bool:
    """The first table on a page is usually a 1-row banner with the running header text.
    Identify it by having no '序号' in its first non-empty row."""
    if not table or len(table) < 2:
        return True
    for r in table[:2]:
        for c in r:
            if c and "序号" in str(c):
                return False
    return True


def collect_rule_pages(pdf: pdfplumber.PDF) -> list[tuple[str, int, int]]:
    """Scan the PDF body to find each rule's first page and (start, end) page range."""
    # Step 1: collect all heading occurrences from p63 onward
    occurrences: list[tuple[int, str]] = []
    for i in range(62, pdf.pages.__len__()):
        txt = pdf.pages[i].extract_text() or ""
        for m in RULE_HEADING_RE.finditer(txt):
            occurrences.append((i + 1, m.group(1)))  # 1-based
    # Step 2: dedupe by (page, subject); keep first page per subject
    first_page: dict[str, int] = {}
    for p, s in occurrences:
        if s not in first_page:
            first_page[s] = p
    # Step 3: sort by start page; page_end = next start - 1 (or last page)
    items = sorted(first_page.items(), key=lambda x: x[1])
    total = len(pdf.pages)
    result = []
    for idx, (subj, start) in enumerate(items):
        end = items[idx + 1][1] - 1 if idx + 1 < len(items) else total
        result.append((subj, start, end))
    return result


def header_map_from_table(table) -> dict[int, str]:
    """Return {col_index: role} for the first row that contains role-identifiable cells."""
    if not table:
        return {}
    for row in table[:3]:
        m = {}
        for i, c in enumerate(row):
            role = col_role(str(c) if c else "")
            if role:
                m[i] = role
        if m:
            return m
    return {}


def process_table(rule_subject: str, table, page_no: int, conn) -> int:
    """Insert a single table's rows as KPs; return rows inserted."""
    if not table or len(table) < 2:
        return 0
    # find the header row (first row with 序号)
    header_idx = -1
    header_map: dict[int, str] = {}
    for ri, row in enumerate(table[:3]):
        m = header_map_from_table([row])
        if m and "seq" in m.values():
            header_idx = ri
            header_map = m
            break
    if header_idx < 0:
        return 0

    # find rule_id (must exist; create if missing)
    batch_id = db.get_or_create_batch(
        conn, SOURCE, PDF_BATCH_LABEL,
        pub_date="2025", ann_url=None, pdf_path=PDF_PATH, xlsx_path=None,
    )
    rule_id = db.get_or_create_rule(
        conn, SOURCE, rule_subject, batch_id,
        category=infer_category(rule_subject),
        object_type=infer_object_type(rule_subject),
        page_start=page_no, page_end=page_no,
    )

    n = 0
    for row in table[header_idx + 1:]:
        cells = {}
        for i, role in header_map.items():
            if i < len(row):
                cells[role] = row[i]
        subj = cells.get("subject_name")
        if not subj or "合计" in str(subj):
            continue
        seq = to_int(cells.get("seq"))
        subj_b = cells.get("subject_name_b")
        a = db.normalize_text(subj)
        b = db.normalize_text(subj_b)
        if a and b:
            subject_name = f"{a} vs {b}"
        else:
            subject_name = a
        code_count = to_int(cells.get("code_count"))
        detection_logic = db.normalize_text(cells.get("detection_logic"))
        logic_basis = db.normalize_text(cells.get("logic_basis"))
        codes = db.normalize_text(cells.get("codes"))
        remark = db.normalize_text(cells.get("remark"))
        raw = db.normalize_text(json.dumps({"page": page_no, "row": [str(c) if c is not None else "" for c in row]}, ensure_ascii=False))
        db.insert_kp(
            conn, rule_id,
            seq=seq, subject_name=subject_name, code_count=code_count,
            detection_logic=detection_logic,
            logic_basis=logic_basis,
            codes=codes,
            remark=remark,
            raw_row=raw,
        )
        n += 1
    if n:
        db.update_rule_row_count(conn, rule_id)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-pdf", action="store_true", help="Clear only pdf_2025 data before ingest")
    ap.add_argument("--from-page", type=int, default=63, help="First body page to scan (1-based)")
    args = ap.parse_args()

    db.init_db()
    if args.reset_pdf:
        with db.connect() as conn:
            conn.execute("DELETE FROM rules WHERE source = ?", (SOURCE,))
            conn.execute("DELETE FROM batches WHERE source = ?", (SOURCE,))
            # knowledge_points for this source are cascaded via rules ON DELETE CASCADE

    if not os.path.exists(PDF_PATH):
        print(f"PDF not found: {PDF_PATH}")
        return

    print(f"Opening {PDF_PATH} ({os.path.getsize(PDF_PATH)/1024/1024:.1f} MB) ...")
    with pdfplumber.open(PDF_PATH) as pdf:
        # step 1: collect rule -> (start, end) page ranges
        rules = collect_rule_pages(pdf)
        print(f"Found {len(rules)} rules in body (p{args.from_page}+).")
        # step 2: per-page heading-aware processing
        # state: most recent heading on the current/previous page
        current_subj = None
        current_first_page: dict[str, int] = {}
        current_last_page: dict[str, int] = {}
        current_count: dict[str, int] = {}

        def flush_rule_stats(conn):
            for s_, cnt in current_count.items():
                if cnt:
                    conn.execute(
                        "UPDATE rules SET page_end = ? WHERE source = ? AND rule_subject = ?",
                        (current_last_page.get(s_, current_first_page.get(s_, 0)), SOURCE, s_),
                    )

        with db.connect() as conn:
            for pn in range(62, pdf.pages.__len__()):
                page = pdf.pages[pn]
                tables = page.extract_tables()
                txt = page.extract_text() or ""
                # find all headings on this page, with their text positions
                heading_matches = list(RULE_HEADING_RE.finditer(txt))
                # filter banner table(s) at the very top
                data_tables = [t for t in tables if not is_banner_table(t)]
                if not heading_matches and not data_tables:
                    continue
                # Build a sequence: walk through tables; if a heading precedes a table, switch rule
                # Simple model: split data_tables by headings. The first heading on the page applies
                # to all tables until the next heading, or end of page. Continuation from prev page
                # also applies until a new heading appears.
                # Heuristic: number of headings <= number of data_tables on the page; pair them
                # by position (first heading -> first table, etc).
                if not heading_matches:
                    # continuation page: all tables go to current_subj
                    for t in data_tables:
                        n = process_table(current_subj, t, pn + 1, conn)
                        if n and current_subj:
                            current_count[current_subj] = current_count.get(current_subj, 0) + n
                            current_last_page[current_subj] = pn + 1
                else:
                    # headings on this page; each gets its first data table, remaining tables
                    # continue with the LAST heading on the page
                    last_h_subj = None
                    used = 0
                    for hi, hm in enumerate(heading_matches):
                        new_subj = hm.group(1)
                        current_subj = new_subj
                        if new_subj not in current_first_page:
                            current_first_page[new_subj] = pn + 1
                        # assign the next un-used data table to this heading
                        if used < len(data_tables):
                            t = data_tables[used]
                            n = process_table(new_subj, t, pn + 1, conn)
                            if n:
                                current_count[new_subj] = current_count.get(new_subj, 0) + n
                                current_last_page[new_subj] = pn + 1
                            used += 1
                        last_h_subj = new_subj
                    # remaining tables go to the last heading
                    for t in data_tables[used:]:
                        n = process_table(last_h_subj, t, pn + 1, conn)
                        if n and last_h_subj:
                            current_count[last_h_subj] = current_count.get(last_h_subj, 0) + n
                            current_last_page[last_h_subj] = pn + 1
            flush_rule_stats(conn)

        # final summary
        total_rules = sum(1 for c in current_count.values() if c > 0)
        total_kp = sum(current_count.values())
        for s_, cnt in current_count.items():
            if cnt:
                p1 = current_first_page.get(s_, '?')
                p2 = current_last_page.get(s_, '?')
                print(f"  p{p1}-{p2}  {s_}  ->  {cnt} KPs")
    print(f"\n=== PDF ingest done: {total_rules} rules, {total_kp} knowledge points ===")
    print(f"DB: {db.DB_PATH}")


if __name__ == "__main__":
    main()
