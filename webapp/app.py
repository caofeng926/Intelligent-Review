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

import html
import math
import os
import sys

from flask import Flask, abort, jsonify, render_template, request

from . import admin, db, nhsa_api, nhsa_browse, yp2023
from .helpers import PAGE_SIZE, SOURCE_LABEL
from .query_utils import row_to_dict
from .search_backend import _row_to_kp_dict, detect_mode, do_search

app = Flask(__name__, static_folder="static", template_folder="templates")
nhsa_api.register(app)
from . import consumables  # noqa: E402, F401

consumables.register(app)
from . import kp  # noqa: E402, F401

kp.register(app)
from . import rules  # noqa: E402, F401

rules.register(app)
nhsa_browse.register(app)
yp2023.register(app)
app.register_blueprint(admin.admin_bp)
app.config["JSON_AS_ASCII"] = False
# 静态资源缓存: 本地开发可即时刷新, 生产可走 CDN/反向代理缓存
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0 if app.debug else 3600  # dev=0 / prod=1h


# ---- Inject global stats into all templates ----
@app.context_processor
def inject_stats():
    try:
        with db.connect() as conn:
            stats = {
                "kp": conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0],
                "codes": conn.execute("SELECT COUNT(*) FROM knowledge_point_codes").fetchone()[0],
                "rules": conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0],
            }
    except Exception:
        stats = {"kp": 0, "codes": 0, "rules": 0}
    return {"nav_stats": stats}


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
    limit = PAGE_SIZE  # noqa: F821 (Flask closure)
    offset = (page - 1) * limit
    mode = detect_mode(q)
    with db.connect() as conn:
        rows, total = do_search(conn, q, mode, source, limit, offset)
        items = [_row_to_kp_dict(r) for r in rows]
        # 批量查询每个 KP 的代表厂家
        if items:
            kp_ids = [it["id"] for it in items]
            ph = ", ".join("?" * len(kp_ids))
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
     ["code", "reg_name", "product_name", "manufacturer", "approval_no", "spec", "list_class"],
     "reg_name", "code", "/nhsa/yp",   "yp_browse"),
    ("hc",   "医用耗材",  "consumable_codes",          "consumable_codes_fts",
     ["code", "cat_l1_name", "cat_l2_name", "cat_l3_name", "generic_name", "manufacturer", "spec", "material"],
     "generic_name", "code", "/nhsa/hc", "consumables_index"),
    ("tcm",  "中医病证",  "tcm_codes",                 "tcm_codes_fts",
     ["code", "name", "class_name", "part_code", "apply_explain", "remark"],
     "name", "code", "/nhsa/tcm", "tcm_browse"),
    ("icd",  "ICD-10",   "icd_codes",                 "icd_codes_fts",
     ["code", "diagnosis_name", "chapter_name", "section_name", "category_name", "subcategory_name"],
     "diagnosis_name", "code", "/nhsa/icd", "icd_browse"),
    ("ivd",  "诊断试剂",  "ivd_codes",                 "ivd_codes_fts",
     ["code", "catalog_full_name", "testing_index", "testing_category",
      "company_name", "cat_l1_name", "cat_l2_name", "cat_l3_name"],
     "catalog_full_name", "code", "/nhsa/ivd", "ivd_browse"),
    ("ms",   "医疗服务",  "medical_service_codes",     "medical_service_codes_fts",
     ["code", "name", "explain", "contains_content", "charge_unit", "level"],
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
    items = [row_to_dict(r, fields) for r in rows]
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
                return jsonify({"code": code, "kind": "consumable", "data": row_to_dict(row, keys)})
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
            item = row_to_dict(r, [
                "kp_id", "subject_name", "code_count", "rule_subject",
                "source", "batch_label", "pub_date", "code",
            ])
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
    ap.add_argument("--debug", action="store_true",
                    help="启用 Flask debug (生产环境会被拒绝)")
    args = ap.parse_args()
    # 安全闸: FLASK_ENV=production 时要禁 --debug
    if args.debug and os.environ.get("FLASK_ENV") == "production":
        sys.stderr.write("错误: --debug 与 FLASK_ENV=production 互斥。请直接 gunicorn webapp.app:app。\n")
        sys.exit(2)
    app.run(host=args.host, port=args.port, debug=args.debug)
