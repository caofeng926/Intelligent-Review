"""Flask web app for the 医保智审 knowledge base.

Endpoints
---------
GET  /                     home
GET  /search               result page (?q=, ?source=, ?page=)
GET  /rules                browse by batch -> rules
GET  /rules/<int:rid>      one rule's KP list
GET  /kp/<int:kp_id>       KP detail page
GET  /api/search           JSON search (?q=, ?mode=auto|name|initials|code)
GET  /api/kp/<int:kp_id>  single KP JSON
GET  /api/code/<code>      reverse-lookup by 医保编码
"""
from __future__ import annotations
import os
import re
import math
import html
import json
import sqlite3
from typing import Optional

from flask import Flask, render_template, request, jsonify, abort

from . import db
from . import nhsa_api
from . import nhsa_browse
from . import admin

app = Flask(__name__, static_folder="static", template_folder="templates")
nhsa_api.register(app)
nhsa_browse.register(app)
app.register_blueprint(admin.admin_bp)
app.config["JSON_AS_ASCII"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

PAGE_SIZE = 20

SOURCE_LABEL = {
    "nhsa_batch": "NHSA 公告",
    "pdf_2025": "2025 版主册",
}

CODE_RE = re.compile(r"^[A-Z0-9]{8,}$")
LETTERS_RE = re.compile(r"^[A-Za-z]+$")


def detect_mode(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return "name"
    upper = q.upper()
    if CODE_RE.match(upper):
        return "code"
    if LETTERS_RE.match(q) and len(q) >= 2:
        return "initials"
    return "name"


def jieba_query(q: str) -> str:
    """Build FTS5 MATCH expression for the query.

    FTS5 unicode61 tokenizes Chinese as single chars, so multi-char phrase
    matching (e.g. '"阿泰特韦"') does not work and silently returns 0 hits.
    Use prefix match (token*) instead.

    Strategy:
    - Pure ASCII/digits: append * for prefix match.
    - Chinese: prefix match on the first 2 chars of the query.
      Single-char query: prefix match that single char.
    """
    q = q.strip()
    if not q:
        return ""
    # if pure english/digits, just append *
    if re.match(r"^[A-Za-z0-9]+$", q):
        return q + "*"
    # Chinese: FTS5 phrase match fails (per-char tokenization), use prefix*
    if len(q) >= 2:
        return f'"{q[:2]}"*'
    return f'"{q}"*'


def parse_kp_partner(raw_row, object_type):
    """从 raw_row 解出 KP 配对项目。
    - pair:    {subject_name_b, codes_b}   → label=配对项目
    - service: row[1]=code, row[2]=name    → label=配对手术
    返回 {name, code, label} 或 None。"""
    if not raw_row:
        return None
    try:
        d = json.loads(raw_row)
    except Exception:
        return None
    if object_type == "pair":
        nb = (d.get("subject_name_b") or "").strip()
        cb = (d.get("codes_b") or "").strip()
        if nb or cb:
            return {"name": nb, "code": cb, "label": "配对项目"}
    elif object_type == "service":
        row = d.get("row")
        if isinstance(row, list) and len(row) >= 3:
            code = str(row[1] or "").strip()
            name = str(row[2] or "").strip()
            if code or name:
                return {"name": name, "code": code, "label": "配对手术"}
    return None


def _row_to_kp_dict(row) -> dict:
    raw = row[11] if len(row) > 11 else None
    obj = row[12] if len(row) > 12 else None
    return {
        "id": row[0],
        "subject_name": row[1],
        "pinyin_initials": row[2],
        "code_count": row[3],
        "detection_logic": row[4],
        "logic_basis": row[5],
        "codes_preview": row[6],
        "rule_subject": row[7],
        "source": row[8],
        "batch_label": row[9],
        "pub_date": row[10],
        "partner": parse_kp_partner(raw, obj),
    }


def search_name(conn, q: str, source: Optional[str], limit: int, offset: int):
    fts_q = jieba_query(q)
    if not fts_q:
        return [], 0
    sql = """
        SELECT kp.id, kp.subject_name, kp.pinyin_initials, kp.code_count,
               kp.detection_logic, kp.logic_basis, kp.codes,
               r.rule_subject, r.source, b.batch_label, b.pub_date,
               kp.raw_row, r.object_type,
               bm25(kp_fts) AS score
        FROM kp_fts
        JOIN knowledge_points kp ON kp.id = kp_fts.rowid
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kp_fts MATCH ?
    """
    params: list = [fts_q]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY score LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    # total
    cnt_sql = "SELECT COUNT(*) FROM kp_fts WHERE kp_fts MATCH ?"
    cnt_params: list = [fts_q]
    if source:
        cnt_sql = "SELECT COUNT(*) FROM kp_fts JOIN knowledge_points kp ON kp.id=kp_fts.rowid JOIN rules r ON r.id=kp.rule_id WHERE kp_fts MATCH ? AND r.source = ?"
        cnt_params.append(source)
    total = conn.execute(cnt_sql, cnt_params).fetchone()[0]
    return rows, total


def search_initials(conn, q: str, source: Optional[str], limit: int, offset: int):
    needle = q.lower()
    sql = """
        SELECT kp.id, kp.subject_name, kp.pinyin_initials, kp.code_count,
               kp.detection_logic, kp.logic_basis, kp.codes,
               r.rule_subject, r.source, b.batch_label, b.pub_date,
               kp.raw_row, r.object_type
        FROM knowledge_points kp
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kp.pinyin_initials LIKE ?
    """
    params: list = [needle + "%"]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY kp.subject_name LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    cnt_sql = "SELECT COUNT(*) FROM knowledge_points kp WHERE kp.pinyin_initials LIKE ?"
    cnt_params: list = [needle + "%"]
    if source:
        cnt_sql = "SELECT COUNT(*) FROM knowledge_points kp JOIN rules r ON r.id=kp.rule_id WHERE kp.pinyin_initials LIKE ? AND r.source = ?"
        cnt_params.append(source)
    total = conn.execute(cnt_sql, cnt_params).fetchone()[0]
    return [tuple(r) + (None, None) for r in rows], total


def search_code(conn, q: str, source: Optional[str], limit: int, offset: int):
    code = q.upper()
    sql = """
        SELECT kp.id, kp.subject_name, kp.pinyin_initials, kp.code_count,
               kp.detection_logic, kp.logic_basis, kp.codes,
               r.rule_subject, r.source, b.batch_label, b.pub_date,
               kp.raw_row, r.object_type
        FROM knowledge_point_codes kpc
        JOIN knowledge_points kp ON kp.id = kpc.kp_id
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kpc.code = ?
    """
    params: list = [code]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY kp.id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    total = len(rows) + offset if len(rows) == limit else (offset + len(rows))
    return [(r + (None,)) for r in rows], total


def do_search(conn, q: str, mode: str, source: Optional[str], limit: int, offset: int):
    if mode == "code":
        rows, total = search_code(conn, q, source, limit, offset)
    elif mode == "initials":
        rows, total = search_initials(conn, q, source, limit, offset)
    else:
        rows, total = search_name(conn, q, source, limit, offset)
    return rows, total


@app.get("/")
def home():
    with db.connect() as conn:
        stats = {
            "kp": conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0],
            "codes": conn.execute("SELECT COUNT(*) FROM knowledge_point_codes").fetchone()[0],
            "rules": conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0],
            "nhsa": conn.execute("SELECT COUNT(*) FROM rules WHERE source='nhsa_batch'").fetchone()[0],
            "pdf": conn.execute("SELECT COUNT(*) FROM rules WHERE source='pdf_2025'").fetchone()[0],
            "batches": conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
            "consumables": conn.execute("SELECT COUNT(*) FROM consumable_codes").fetchone()[0],
        }
        recent = conn.execute("""
            SELECT kp.id, kp.subject_name, r.rule_subject, b.batch_label, b.pub_date
            FROM knowledge_points kp
            JOIN rules r ON r.id = kp.rule_id
            JOIN batches b ON b.id = r.batch_id
            WHERE b.pub_date IS NOT NULL
            ORDER BY b.pub_date DESC, kp.id DESC
            LIMIT 8
        """).fetchall()
        code_samples = conn.execute("""
            SELECT kpc.code, kp.subject_name, kp.id AS kp_id
            FROM knowledge_point_codes kpc
            JOIN knowledge_points kp ON kp.id = kpc.kp_id
            WHERE kpc.code_seq = 1
              AND kp.subject_name IS NOT NULL AND kp.subject_name != ''
            GROUP BY kp.subject_name
            ORDER BY kp.id
            LIMIT 8
        """).fetchall()
        unique_subjects = conn.execute("""
            SELECT COUNT(DISTINCT subject_name) FROM knowledge_points
            WHERE subject_name IS NOT NULL AND subject_name != ''
        """).fetchone()[0]
    return render_template("home.html", stats=stats, recent=recent,
                           code_samples=code_samples, unique_subjects=unique_subjects)


@app.get("/search")
def search_view():
    q = (request.args.get("q") or "").strip()
    source = request.args.get("source") or None
    if source and source not in SOURCE_LABEL:
        source = None
    page = max(int(request.args.get("page", 1) or 1), 1)
    limit = PAGE_SIZE
    offset = (page - 1) * limit
    mode = detect_mode(q)
    with db.connect() as conn:
        rows, total = do_search(conn, q, mode, source, limit, offset)
        items = [_row_to_kp_dict(r) for r in rows]
        # 批量查询每个 KP 的代表厂家
        if items:
            kp_ids = [it["id"] for it in items]
            ph = ",".join("?" * len(kp_ids))
            mfg_rows = conn.execute(
                f"""SELECT kpc.kp_id, dd.manufacturer, dd.manufacturer_flag
                    FROM knowledge_point_codes kpc
                    JOIN drug_detail dd ON dd.goods_code = kpc.code
                    WHERE kpc.kp_id IN ({ph})
                      AND kpc.code_seq = 1
                      AND dd.manufacturer IS NOT NULL AND dd.manufacturer != ''
                      AND (dd.manufacturer_flag IS NULL
                           OR dd.manufacturer_flag NOT LIKE '%混入规格%')
                    ORDER BY kpc.kp_id
                    LIMIT 100""",
                kp_ids
            ).fetchall()
            # 每个 KP 取前 2 个厂家
            kp_mfgs = {}
            for kp_id, mfg, flag in mfg_rows:
                kp_mfgs.setdefault(kp_id, []).append((mfg, flag or ""))
            for it in items:
                it["manufacturers"] = kp_mfgs.get(it["id"], [])
    pages = max(1, math.ceil(total / limit)) if total else 0
    with db.connect() as _conn:
        _counts = _code_counts(_conn)
    return render_template(
        "search.html",
        q=q, mode=mode, source=source,
        items=items, total=total, page=page, pages=pages, limit=limit,
        active_tab="kp", tabs=CODE_SEARCH_TABS, code_counts=_counts,
    )


# ---------------- 代码表搜索（5 种） ----------------
CODE_SEARCH_CONFIG = [
    ("yp",   "医保药品",  "yp_codes",                  "yp_codes_fts",
     ["code","reg_name","product_name","manufacturer","approval_no","spec","list_class"],
     "reg_name", "code", "/nhsa/yp",   "yp_browse"),
    ("hc",   "医用耗材",  "consumable_codes",          "consumable_codes_fts",
     ["code","cat_l1_name","cat_l2_name","cat_l3_name","generic_name","manufacturer","spec","material"],
     "generic_name", "code", "/nhsa/hc", "consumables_index"),
    ("tcm",  "中医病证",  "tcm_codes",                 "tcm_codes_fts",
     ["code","name","class_name","part_code","apply_explain","remark"],
     "name", "code", "/nhsa/tcm", "tcm_browse"),
    ("icd",  "ICD-10",   "icd_codes",                 "icd_codes_fts",
     ["code","diagnosis_name","chapter_name","section_name","category_name","subcategory_name"],
     "diagnosis_name", "code", "/nhsa/icd", "icd_browse"),
    ("ivd",  "诊断试剂",  "ivd_codes",                 "ivd_codes_fts",
     ["code","catalog_full_name","testing_index","testing_category","company_name","cat_l1_name","cat_l2_name","cat_l3_name"],
     "catalog_full_name", "code", "/nhsa/ivd", "ivd_browse"),
    ("ms",   "医疗服务",  "medical_service_codes",     "medical_service_codes_fts",
     ["code","name","explain","contains_content","charge_unit","level"],
     "name", "code", "/nhsa/ms", "ms_browse"),
]

CODE_SEARCH_TABS = [
    ("kp",  "审核规则", "/search", "search_view"),
] + [(c[0], c[1], f"/search/{c[0]}", f"code_search_{c[0]}") for c in CODE_SEARCH_CONFIG]


def _code_counts(conn):
    """每个代码表的总行数，用于 tab 显示。"""
    out = {"kp": conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]}
    for cfg in CODE_SEARCH_CONFIG:
        out[cfg[0]] = conn.execute(f"SELECT COUNT(*) FROM {cfg[2]}").fetchone()[0]
    return out


def _code_search(conn, q, fts_table, table, fields, name_field, code_field, limit=50):
    """FTS5 + LIKE fallback 搜索，返回 (rows, total)。"""
    q = (q or "").strip()
    if not q:
        return [], 0
    # unicode61 在实际数据上把整个中文短语当作一个 token
    # 所以 q + "*" 是最稳的写法：长 query 自然变成 "阿莫西林*" 也能匹配
    # ASCII/数字 / 短 q 都用同一规则
    fts = q + "*"
    cols = ", ".join(f"t.{f}" for f in fields)
    try:
        rows = conn.execute(
            f"SELECT t.rowid AS __rid__, {cols} FROM {table} t "
            f"WHERE t.rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?) "
            f"ORDER BY t.{code_field} LIMIT ?",
            (fts, limit)
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {table} t "
            f"WHERE t.rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?)",
            (fts,)
        ).fetchone()[0]
    except Exception:
        like_pat = f"%{q}%"
        wheres = " OR ".join(f"t.{f} LIKE ?" for f in fields)
        params = [like_pat] * len(fields)
        rows = conn.execute(
            f"SELECT t.rowid AS __rid__, {cols} FROM {table} t WHERE {wheres} "
            f"ORDER BY t.{code_field} LIMIT ?",
            (*params, limit)
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {table} t WHERE {wheres}", params
        ).fetchone()[0]
    return rows, total


@app.get("/search/yp")
def code_search_yp():
    return _code_route("yp")


@app.get("/search/hc")
def code_search_hc():
    return _code_route("hc")


@app.get("/search/tcm")
def code_search_tcm():
    return _code_route("tcm")


@app.get("/search/icd")
def code_search_icd():
    return _code_route("icd")


@app.get("/search/ivd")
def code_search_ivd():
    return _code_route("ivd")


@app.get("/search/ms")
def code_search_ms():
    return _code_route("ms")


def _code_route(type_id):
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    limit = 20
    cfg = next((c for c in CODE_SEARCH_CONFIG if c[0] == type_id), None)
    if not cfg:
        abort(404)
    type_id, label, table, fts_table, fields, name_field, code_field, index_url, browse_endpoint = cfg
    with db.connect() as conn:
        rows, total = _code_search(conn, q, fts_table, table, fields, name_field, code_field, limit)
        counts = _code_counts(conn)
    items = [dict(zip(fields, r)) for r in rows]
    code_result = {
        "items": items, "total": total, "type_id": type_id, "label": label,
        "table": table, "name_field": name_field, "code_field": code_field,
        "index_url": index_url, "browse_endpoint": browse_endpoint,
        "fields": fields,
    }
    pages = max(1, math.ceil(total / limit)) if total else 0
    return render_template(
        "search.html",
        q=q, mode="code", source=None,
        items=[], total=total, page=page, pages=pages, limit=limit,
        active_tab=type_id, tabs=CODE_SEARCH_TABS, code_counts=counts,
        code_result=code_result,
    )




@app.get("/rules")
def rules_index():
    with db.connect() as conn:
        groups = conn.execute("""
            SELECT b.id, b.source, b.batch_label, b.pub_date,
                   COUNT(DISTINCT r.id) rule_cnt, COUNT(kp.id) kp_cnt
            FROM batches b
            LEFT JOIN rules r ON r.batch_id = b.id
            LEFT JOIN knowledge_points kp ON kp.rule_id = r.id
            GROUP BY b.id
            ORDER BY b.source, b.pub_date DESC, b.id
        """).fetchall()
    return render_template("rules.html", groups=groups, source_label=SOURCE_LABEL)


@app.get("/rules/list")
def rules_list():
    """列出所有规则(按名称去重聚合)。同名规则会合并,展示总 KP 数与所有 rule_id。
    支持 ?q= 按名称/分类关键字过滤。"""
    q = (request.args.get("q") or "").strip()
    with db.connect() as conn:
        base_sql = """
            SELECT
                rules.rule_subject,
                COUNT(*) AS rule_count,
                GROUP_CONCAT(rules.id) AS rule_ids,
                GROUP_CONCAT(DISTINCT b.batch_label) AS batches,
                GROUP_CONCAT(DISTINCT rules.category) AS categories,
                GROUP_CONCAT(DISTINCT rules.object_type) AS object_types,
                MIN(rules.id) AS first_id,
                SUM((SELECT COUNT(*) FROM knowledge_points kp WHERE kp.rule_id = rules.id)) AS kp_cnt
            FROM rules
            LEFT JOIN batches b ON b.id = rules.batch_id
        """
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                base_sql + " WHERE rules.rule_subject LIKE ? OR rules.category LIKE ? "
                "GROUP BY rules.rule_subject ORDER BY rules.rule_subject",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                base_sql + " GROUP BY rules.rule_subject ORDER BY rules.rule_subject"
            ).fetchall()
    return render_template("rules_list.html", rules=rows, q=q, source_label=SOURCE_LABEL)




@app.get("/rules/find")
def rules_find():
    """按知识点查询：录入具体药品/项目，列出所有涉及的规则。"""
    q = (request.args.get("q") or "").strip()
    src = (request.args.get("source") or "").strip() or None
    if src and src not in SOURCE_LABEL:
        src = None

    groups = []        # 每条规则一组
    total_kp = 0
    total_rule = 0
    mode = None

    if q:
        mode = detect_mode(q)
        with db.connect() as conn:
            rows, total_kp = _search_kps_grouped_by_rule(conn, q, mode, src, limit=300)
            by_rule = {}
            for r in rows:
                rid = r["rule_id"]
                if rid not in by_rule:
                    by_rule[rid] = {
                        "rule_id": rid,
                        "rule_subject": r["rule_subject"],
                        "source": r["source"],
                        "category": r["category"],
                        "object_type": r["object_type"],
                        "batch_label": r["batch_label"],
                        "pub_date": r["pub_date"],
                        "kps": [],
                    }
                by_rule[rid]["kps"].append({
                    "id": r["kp_id"],
                    "seq": r["kp_seq"],
                    "subject_name": r["subject_name"],
                    "pinyin_initials": r["pinyin_initials"],
                    "code_count": r["code_count"],
                    "codes": r["codes"],
                    "detection_logic": r["detection_logic"],
                })
            # NHSA 优先，然后按规则名排序
            groups = sorted(
                by_rule.values(),
                key=lambda x: (x["source"] != "nhsa_batch", x["rule_subject"], x["rule_id"]),
            )
            total_rule = len(groups)
    return render_template(
        "rules_find.html",
        q=q, source=src, mode=mode,
        groups=groups, total_kp=total_kp, total_rule=total_rule,
        source_label=SOURCE_LABEL,
    )


def _search_kps_grouped_by_rule(conn, q: str, mode: str, source, limit: int = 300):
    """为 /rules/find 搜索 KPs，附带 rule_id 等列，便于分组。"""
    if not q:
        return [], 0
    if mode == "code":
        kp_rows, total = search_code(conn, q, source, limit, 0)
        if not kp_rows:
            return [], 0
        return _enrich_kps_with_rule(conn, [r[0] for r in kp_rows], total), total
    if mode == "initials":
        kp_rows, total = search_initials(conn, q, source, limit, 0)
        if not kp_rows:
            return [], 0
        return _enrich_kps_with_rule(conn, [r[0] for r in kp_rows], total), total
    # name mode
    fts_q = jieba_query(q)
    if not fts_q:
        return [], 0
    sql = """
        SELECT kp.id AS kp_id, kp.seq AS kp_seq, kp.subject_name, kp.pinyin_initials,
               kp.code_count, kp.codes, kp.detection_logic,
               r.id AS rule_id, r.rule_subject, r.source, r.category, r.object_type,
               b.batch_label, b.pub_date
        FROM kp_fts
        JOIN knowledge_points kp ON kp.id = kp_fts.rowid
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kp_fts MATCH ?
    """
    params = [fts_q]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY bm25(kp_fts), r.source, r.rule_subject, kp.seq IS NULL, kp.seq, kp.id LIMIT ?"
    params.append(limit)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.row_factory = None
    total = conn.execute("SELECT COUNT(*) FROM kp_fts WHERE kp_fts MATCH ?", [fts_q]).fetchone()[0]
    return rows, total


def _enrich_kps_with_rule(conn, kp_ids, total):
    """对一组 KP id，附带 rule 信息返回。结果保持 kp_ids 顺序。"""
    if not kp_ids:
        return [], 0
    ph = ",".join("?" * len(kp_ids))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT kp.id AS kp_id, kp.seq AS kp_seq, kp.subject_name, kp.pinyin_initials,
               kp.code_count, kp.codes, kp.detection_logic,
               r.id AS rule_id, r.rule_subject, r.source, r.category, r.object_type,
               b.batch_label, b.pub_date
        FROM knowledge_points kp
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kp.id IN ({ph})
        """,
        kp_ids,
    ).fetchall()
    conn.row_factory = None
    pos = {kid: i for i, kid in enumerate(kp_ids)}
    rows = sorted(rows, key=lambda r: pos[r["kp_id"]])
    return rows


@app.get("/rules/<int:rid>")
def rule_detail(rid: int):
    page = max(int(request.args.get("page", 1) or 1), 1)
    limit = PAGE_SIZE
    offset = (page - 1) * limit
    with db.connect() as conn:
        rule = conn.execute("""
            SELECT r.id, r.rule_subject, r.source, r.category, r.object_type,
                   r.page_start, r.page_end, r.row_count, b.batch_label, b.pub_date
            FROM rules r JOIN batches b ON b.id = r.batch_id
            WHERE r.id = ?
        """, (rid,)).fetchone()
        if not rule:
            abort(404)
        total = conn.execute("SELECT COUNT(*) FROM knowledge_points WHERE rule_id = ?", (rid,)).fetchone()[0]
        rows = conn.execute("""
            SELECT id, seq, subject_name, pinyin_initials, code_count, codes
            FROM knowledge_points
            WHERE rule_id = ?
            ORDER BY seq IS NULL, seq, id
            LIMIT ? OFFSET ?
        """, (rid, limit, offset)).fetchall()
    pages = max(1, math.ceil(total / limit)) if total else 0
    return render_template(
        "rule_detail.html", rule=rule, items=rows,
        total=total, page=page, pages=pages, limit=limit,
        source_label=SOURCE_LABEL,
    )


@app.get("/kp/<int:kp_id>")
def kp_detail(kp_id: int):
    with db.connect() as conn:
        conn.row_factory = sqlite3.Row
        kp = conn.execute("""
            SELECT kp.id, kp.seq, kp.subject_name, kp.pinyin_initials, kp.code_count,
                   kp.detection_logic, kp.logic_basis, kp.remark, kp.codes, kp.raw_row,
                   r.rule_subject, r.source, r.category, r.object_type, r.id AS rule_id,
                   b.batch_label, b.pub_date
            FROM knowledge_points kp
            JOIN rules r ON r.id = kp.rule_id
            JOIN batches b ON b.id = r.batch_id
            WHERE kp.id = ?
        """, (kp_id,)).fetchone()
        if not kp:
            abort(404)
        codes = db.get_kp_codes(conn, kp_id)
        # 查询 drug_detail 获取每个 code 对应的厂家
        if codes:
            ph = ",".join("?" * len(codes))
            drug_rows = conn.execute(
                f"SELECT goods_code, manufacturer, manufacturer_flag, "
                f"       approval_no, base_code, dosage_form, spec, packaging, product_name "
                f"FROM drug_detail WHERE goods_code IN ({ph})",
                codes
            ).fetchall()
            drug_details = {r[0]: r for r in drug_rows}
        else:
            drug_details = {}
    partner = parse_kp_partner(kp["raw_row"], kp["object_type"])
    return render_template("kp.html", kp=kp, codes=codes,
                           drug_details=drug_details, source_label=SOURCE_LABEL,
                           partner=partner)


@app.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    source = request.args.get("source") or None
    mode = request.args.get("mode") or "auto"
    if mode == "auto":
        mode = detect_mode(q)
    if source and source not in SOURCE_LABEL:
        source = None
    page = max(int(request.args.get("page", 1) or 1), 1)
    limit = min(int(request.args.get("limit", PAGE_SIZE) or PAGE_SIZE), 50)
    offset = (page - 1) * limit
    with db.connect() as conn:
        rows, total = do_search(conn, q, mode, source, limit, offset)
        items = [_row_to_kp_dict(r) for r in rows]
        if items:
            kp_ids = [it["id"] for it in items]
            ph = ",".join("?" * len(kp_ids))
            mfg_rows = conn.execute(
                f"""SELECT kpc.kp_id, dd.manufacturer, dd.manufacturer_flag
                    FROM knowledge_point_codes kpc
                    JOIN drug_detail dd ON dd.goods_code = kpc.code
                    WHERE kpc.kp_id IN ({ph})
                      AND kpc.code_seq = 1
                      AND dd.manufacturer IS NOT NULL AND dd.manufacturer != ''
                      AND (dd.manufacturer_flag IS NULL
                           OR dd.manufacturer_flag NOT LIKE '%混入规格%')
                    ORDER BY kpc.kp_id
                    LIMIT 100""",
                kp_ids
            ).fetchall()
            kp_mfgs = {}
            for kp_id, mfg, flag in mfg_rows:
                kp_mfgs.setdefault(kp_id, []).append({"manufacturer": mfg, "manufacturer_flag": flag or ""})
            for it in items:
                it["manufacturers"] = kp_mfgs.get(it["id"], [])
    return jsonify({"q": q, "mode": mode, "source": source, "total": total,
                    "page": page, "limit": limit, "items": items})


@app.get("/api/kp/<int:kp_id>")
def api_kp(kp_id: int):
    with db.connect() as conn:
        kp = conn.execute("""
            SELECT kp.id, kp.seq, kp.subject_name, kp.pinyin_initials, kp.code_count,
                   kp.detection_logic, kp.logic_basis, kp.remark,
                   r.rule_subject, r.source, r.category, r.object_type, r.id AS rule_id,
                   b.batch_label, b.pub_date
            FROM knowledge_points kp
            JOIN rules r ON r.id = kp.rule_id
            JOIN batches b ON b.id = r.batch_id
            WHERE kp.id = ?
        """, (kp_id,)).fetchone()
        if not kp:
            abort(404)
        codes = db.get_kp_codes(conn, kp_id)
    return jsonify({
        "id": kp[0], "seq": kp[1], "subject_name": kp[2], "pinyin_initials": kp[3],
        "code_count": kp[4], "detection_logic": kp[5], "logic_basis": kp[6],
        "remark": kp[7], "rule_subject": kp[8], "source": kp[9], "category": kp[10],
        "object_type": kp[11], "rule_id": kp[12], "batch_label": kp[13], "pub_date": kp[14],
        "codes": codes,
    })


@app.get("/api/code/<code>")
def api_code(code: str):
    code = code.upper()
    with db.connect() as conn:
        # 1. Check if it's a consumable code (C + 18-19 digits, length >= 17)
        if code.startswith("C") and len(code) >= 17 and code[1:].isdigit():
            row = conn.execute("""
                SELECT code, generic_name FROM consumable7_codes WHERE code=?
            """, (code,)).fetchone()
            if row:
                return jsonify({"code": code, "kind": "consumable7", "data": {"code": row[0], "generic_name": row[1]}})
            row = conn.execute("""
                SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name,
                       cat_l3, cat_l3_name, generic_category, material,
                       spec, generic_no, generic_name, manufacturer
                FROM consumable_codes
                WHERE code = ?
            """, (code,)).fetchone()
            if row:
                keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
                        "cat_l3", "cat_l3_name", "generic_category", "material",
                        "spec", "generic_no", "generic_name", "manufacturer"]
                return jsonify({"code": code, "kind": "consumable", "data": dict(zip(keys, row))})
            # not found in consumable_codes, fall through to KP search

        # 2. Look up in KP codes (drugs / services / TCM)
        rows = conn.execute("""
            SELECT kp.id, kp.subject_name, kp.code_count,
                   r.rule_subject, r.source, b.batch_label, b.pub_date,
                   kpc.code
            FROM knowledge_point_codes kpc
            JOIN knowledge_points kp ON kp.id = kpc.kp_id
            JOIN rules r ON r.id = kp.rule_id
            JOIN batches b ON b.id = r.batch_id
            WHERE kpc.code = ?
            LIMIT 50
        """, (code,)).fetchall()
        # 查询 drug_detail 厂家信息
        items = []
        for r in rows:
            d = conn.execute(
                "SELECT manufacturer, manufacturer_flag, approval_no, base_code, "
                "product_name, dosage_form, spec FROM drug_detail WHERE goods_code = ?",
                (r[7],)
            ).fetchone()
            item = dict(zip(
                ["kp_id", "subject_name", "code_count", "rule_subject",
                 "source", "batch_label", "pub_date", "code"], r
            ))
            if d:
                item["drug_detail"] = {
                    "manufacturer": d[0] or "",
                    "manufacturer_flag": d[1] or "",
                    "approval_no": d[2] or "",
                    "base_code": d[3] or "",
                    "product_name": d[4] or "",
                    "dosage_form": d[5] or "",
                    "spec": d[6] or "",
                }
            items.append(item)
    return jsonify({"code": code, "kind": "rule_code", "count": len(items), "items": items})


@app.get("/api/consumable/<code>")
def api_consumable(code: str):
    """Direct lookup in the consumable_codes table."""
    code = code.upper()
    with db.connect() as conn:
        row = conn.execute("""
            SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name,
                   cat_l3, cat_l3_name, generic_category, material,
                   spec, generic_no, generic_name, manufacturer
            FROM consumable_codes WHERE code = ?
        """, (code,)).fetchone()
    if not row:
        return jsonify({"code": code, "found": False}), 404
    keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
            "cat_l3", "cat_l3_name", "generic_category", "material",
            "spec", "generic_no", "generic_name", "manufacturer"]
    return jsonify({"found": True, "data": dict(zip(keys, row))})


@app.get("/api/consumable-categories")
def api_consumable_categories():
    """Aggregate consumable code counts by 一级/二级/三级 classification."""
    cat_l1 = request.args.get("l1")
    cat_l2 = request.args.get("l2")
    with db.connect() as conn:
        if cat_l1 and cat_l2:
            groups = conn.execute("""
                SELECT cat_l3, cat_l3_name, COUNT(*) AS code_count
                FROM consumable_codes
                WHERE cat_l1 = ? AND cat_l2 = ?
                GROUP BY cat_l3 ORDER BY code_count DESC
            """, (cat_l1, cat_l2)).fetchall()
        elif cat_l1:
            groups = conn.execute("""
                SELECT cat_l2, cat_l2_name, COUNT(*) AS code_count
                FROM consumable_codes
                WHERE cat_l1 = ?
                GROUP BY cat_l2 ORDER BY code_count DESC
            """, (cat_l1,)).fetchall()
        else:
            groups = conn.execute("""
                SELECT cat_l1, cat_l1_name, COUNT(*) AS code_count
                FROM consumable_codes
                GROUP BY cat_l1 ORDER BY code_count DESC
            """).fetchall()
    return jsonify({"groups": [dict(zip(["key", "name", "code_count"], r)) for r in groups]})


@app.get("/consumables", strict_slashes=False)
@app.get("/consumables/", strict_slashes=False)
def consumables_index():
    """Browse consumable codes by 一级 classification."""
    with db.connect() as conn:
        groups = conn.execute("""
            SELECT cat_l1 AS l1, cat_l1_name AS l1_name, COUNT(*) AS code_count
            FROM consumable_codes
            WHERE cat_l1 IS NOT NULL
            GROUP BY cat_l1 ORDER BY cat_l1
        """).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM consumable_codes").fetchone()[0]
    return render_template(
        "consumables.html",
        groups=[dict(zip(["l1", "l1_name", "code_count"], g)) for g in groups],
        l1=None, l2=None, l1_name=None, l2_name=None, total_codes=total,
    )



@app.get("/consumables/cat/<l1>/<l2>/<l3>", strict_slashes=False)
def consumables_l3(l1, l2, l3):
    """Show all codes under (cat_l1, cat_l2, cat_l3). Sample-first-200 of N rows."""
    l1 = l1.upper(); l2 = l2.upper(); l3 = l3.upper()
    with db.connect() as conn:
        names = conn.execute("""
            SELECT cat_l1_name, cat_l2_name, cat_l3_name
            FROM consumable_codes
            WHERE cat_l1=? AND cat_l2=? AND cat_l3=?
            LIMIT 1
        """, (l1, l2, l3)).fetchone()
        if not names:
            return render_template("consumables_l3.html",
                                   sample=[], total=0,
                                   l1=l1, l2=l2, l3=l3,
                                   l1_name=None, l2_name=None, l3_name=None), 404
        l1_name, l2_name, l3_name = names
        sample_rows = conn.execute("""
            SELECT code, generic_name, spec, manufacturer, material
            FROM consumable_codes
            WHERE cat_l1=? AND cat_l2=? AND cat_l3=? AND code IS NOT NULL
            ORDER BY code LIMIT 200
        """, (l1, l2, l3)).fetchall()
        total = conn.execute("""
            SELECT COUNT(*) FROM consumable_codes
            WHERE cat_l1=? AND cat_l2=? AND cat_l3=? AND code IS NOT NULL
        """, (l1, l2, l3)).fetchone()[0]
        keys = ["code","generic_name","spec","manufacturer","material"]
        sample = [dict(zip(keys, r)) for r in sample_rows]
    return render_template("consumables_l3.html",
                           sample=sample, total=total,
                           l1=l1, l2=l2, l3=l3,
                           l1_name=l1_name, l2_name=l2_name, l3_name=l3_name)
@app.get("/consumables/cat/<l1>", strict_slashes=False)
@app.get("/consumables/cat/<l1>/<l2>", strict_slashes=False)
def consumables_browse(l1, l2=None):
    """Drill into 二级 (with l1) or 三级 (with l1+l2)."""
    with db.connect() as conn:
        l1_name = conn.execute("SELECT cat_l1_name FROM consumable_codes WHERE cat_l1=? LIMIT 1", (l1,)).fetchone()
        if not l1_name:
            return render_template("consumables.html", groups=[], l1=None, l2=None,
                                   l1_name=None, l2_name=None, total_codes=0)
        l1_name = l1_name[0]
        if l2 is None:
            # show 二级
            rows = conn.execute("""
                SELECT cat_l2 AS l2, cat_l2_name AS l2_name, COUNT(*) AS code_count
                FROM consumable_codes
                WHERE cat_l1=? AND cat_l2 IS NOT NULL
                GROUP BY cat_l2 ORDER BY cat_l2
            """, (l1,)).fetchall()
            return render_template(
                "consumables.html",
                groups=[dict(zip(["l1", "l1_name", "l2", "l2_name", "code_count"],
                                 (l1, l1_name, g[0], g[1], g[2]))) for g in rows],
                l1=l1, l2=None, l1_name=l1_name, l2_name=None,
                total_codes=sum(g[2] for g in rows),
            )
        else:
            # show 三级 + sample codes
            l2_name = conn.execute(
                "SELECT cat_l2_name FROM consumable_codes WHERE cat_l1=? AND cat_l2=? LIMIT 1",
                (l1, l2)).fetchone()
            if not l2_name:
                return render_template("consumables.html", groups=[], l1=l1, l2=l2,
                                       l1_name=l1_name, l2_name=None, total_codes=0)
            l2_name = l2_name[0]
            rows = conn.execute("""
                SELECT cat_l3 AS l3, cat_l3_name AS l3_name, COUNT(*) AS code_count
                FROM consumable_codes
                WHERE cat_l1=? AND cat_l2=? AND cat_l3 IS NOT NULL
                GROUP BY cat_l3 ORDER BY cat_l3
            """, (l1, l2)).fetchall()
            return render_template(
                "consumables.html",
                groups=[dict(zip(["l1", "l1_name", "l2", "l2_name", "l3", "l3_name", "code_count"],
                                 (l1, l1_name, l2, l2_name, g[0], g[1], g[2]))) for g in rows],
                l1=l1, l2=l2, l1_name=l1_name, l2_name=l2_name,
                total_codes=sum(g[2] for g in rows),
            )


@app.get("/consumables/code/<code>", strict_slashes=False)
def consumable_detail(code):
    """Show detail for a specific consumable code."""
    code = code.upper()
    with db.connect() as conn:
        c = conn.execute("""
            SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name,
                   cat_l3, cat_l3_name, generic_category, material,
                   spec, generic_no, generic_name, manufacturer
            FROM consumable_codes WHERE code=?
        """, (code,)).fetchone()
        rules = []
        if c:
            rules = conn.execute("""
                SELECT r.id, r.rule_subject, r.category, b.batch_label, b.pub_date
                FROM knowledge_point_codes kpc
                JOIN knowledge_points kp ON kp.id = kpc.kp_id
                JOIN rules r ON r.id = kp.rule_id
                JOIN batches b ON b.id = r.batch_id
                WHERE kpc.code = ?
                ORDER BY b.id DESC LIMIT 20
            """, (code,)).fetchall()
        keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
                "cat_l3", "cat_l3_name", "generic_category", "material",
                "spec", "generic_no", "generic_name", "manufacturer"]
        cd = dict(zip(keys, c)) if c else None
    return render_template("consumable_detail.html", c=cd, code=code, rules=rules)


@app.get("/api/rule-categories")
def api_rule_categories():
    """返回按规则类型分类的数据，用于小程序规则浏览页"""
    with db.connect() as conn:
        rules = conn.execute("""
            SELECT r.id, r.rule_subject, r.source, b.batch_label,
                   COUNT(kp.id) as kp_count
            FROM rules r
            JOIN batches b ON b.id = r.batch_id
            LEFT JOIN knowledge_points kp ON kp.rule_id = r.id
            GROUP BY r.id
            ORDER BY r.rule_subject
        """).fetchall()

    category_map = {}
    for r in rules:
        rule_subject = r[1]
        if rule_subject.startswith("药品"):
            category = "药品"
        elif rule_subject.startswith("医疗服务项目"):
            category = "医疗服务项目"
        elif rule_subject.startswith("中药饮片"):
            category = "中药饮片"
        elif rule_subject.startswith("医用耗材"):
            category = "医用耗材"
        elif rule_subject.startswith("诊断"):
            category = "诊断"
        elif rule_subject.startswith("手术"):
            category = "手术操作"
        else:
            category = "其他"

        if category not in category_map:
            category_map[category] = {"name": category, "rules": [], "total_kp": 0, "rule_count": 0}
        category_map[category]["rules"].append({
            "id": r[0], "subject": r[1], "source": r[2],
            "batch_label": r[3], "kp_count": r[4],
        })
        category_map[category]["total_kp"] += r[4]
        category_map[category]["rule_count"] += 1

    category_order = ["药品", "医疗服务项目", "中药饮片", "医用耗材", "诊断", "手术操作", "其他"]
    categories = [category_map[c] for c in category_order if c in category_map]

    return jsonify({"categories": categories})


@app.template_filter("h")
def h(s):
    if s is None:
        return ""
    return html.escape(str(s))


@app.template_filter("truncate2")
def truncate2(s, n=80):
    if not s:
        return ""
    s = str(s)
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
