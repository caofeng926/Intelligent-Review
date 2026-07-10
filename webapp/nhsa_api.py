"""NHSA reference database API endpoints.

Mounted by app.py via:
    from . import nhsa_api
    nhsa_api.register(app)

Endpoints
---------
GET /api/nhsa/stats                     - row counts for all NHSA tables
GET /api/nhsa/batches                   - batch metadata (source, label, date, count)
GET /api/nhsa/ivd/search?q=&limit=      - search IVD reagents (FTS5)
GET /api/nhsa/ivd/code/<code>           - lookup IVD by code
GET /api/nhsa/yp/search?q=&limit=       - search drugs (FTS5)
GET /api/nhsa/yp/code/<code>            - lookup drug by goods code
GET /api/nhsa/yp/approval/<no>          - lookup drug by approval number
GET /api/nhsa/icd/search?q=&limit=      - search ICD codes
GET /api/nhsa/icd/code/<code>           - lookup ICD by diagnosis code
GET /api/nhsa/ms/search?q=&limit=       - search medical services
GET /api/nhsa/ms/code/<code>            - lookup MS by code
GET /api/nhsa/tcm/search?q=&limit=      - search TCM codes
GET /api/nhsa/tcm/code/<code>           - lookup TCM by code
GET /api/nhsa/hc7/code/<code>           - lookup 7-class consumable by code
"""
from __future__ import annotations
import re
from typing import Optional

from flask import jsonify, request

from . import db
from .query_utils import fts_query as _fts_query, row_to_dict


# ============================================================
# helpers
# ============================================================


def _row_to_dict(row, keys):
    return row_to_dict(row, keys) if row else None


def _limit(default: int = 50, max_: int = 500) -> int:
    try:
        n = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_))


# ============================================================
# endpoints
# ============================================================
def register(app):
    @app.get("/api/nhsa/stats")
    def _stats():
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT source, batch_label, pub_date, record_count, sysflag,
                       csv_path, json_path, datetime(ingested_at) AS ingested_at
                FROM nhsa_batches
                ORDER BY source
            """).fetchall()
            live = {}
            for tbl in ["consumable_codes", "drug_detail", "yp_codes",
                        "ivd_codes", "consumable7_codes", "icd_codes",
                        "medical_service_codes", "tcm_codes"]:
                try:
                    live[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                except Exception:
                    live[tbl] = 0
        return jsonify({
            "live_counts": live,
            "batches": [row_to_dict(r, ["source", "batch_label", "pub_date", "record_count", "sysflag",
                 "csv_path", "json_path", "ingested_at"]) for r in rows],
        })

    @app.get("/api/nhsa/batches")
    def _batches():
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT source, batch_label, pub_date, record_count, sysflag,
                       datetime(ingested_at) AS ingested_at
                FROM nhsa_batches ORDER BY pub_date DESC, source
            """).fetchall()
        return jsonify({
            "batches": [row_to_dict(r, ["source", "batch_label", "pub_date", "record_count",
                 "sysflag", "ingested_at"]) for r in rows],
        })

    # ============== IVD ==============
    @app.get("/api/nhsa/ivd/search")
    def _ivd_search():
        q = (request.args.get("q") or "").strip()
        limit = _limit(50, 500)
        if not q:
            return jsonify({"q": q, "count": 0, "results": []})
        fts = _fts_query(q)
        if not fts:
            return jsonify({"q": q, "count": 0, "results": []})
        with db.connect() as conn:
            try:
                rows = conn.execute("""
                    SELECT code, cat_l1_name, cat_l2_name, cat_l3_name,
                           testing_category, testing_index, use_type, check_type,
                           company_name
                    FROM ivd_codes
                    WHERE id IN (SELECT rowid FROM ivd_codes_fts WHERE ivd_codes_fts MATCH ?)
                    LIMIT ?
                """, (fts, limit)).fetchall()
            except Exception:
                rows = []
        keys = ["code", "cat_l1_name", "cat_l2_name", "cat_l3_name",
                "testing_category", "testing_index", "use_type", "check_type",
                "company_name"]
        return jsonify({
            "q": q, "count": len(rows),
            "results": [row_to_dict(r, keys) for r in rows],
        })

    @app.get("/api/nhsa/ivd/code/<code>")
    def _ivd_by_code(code):
        with db.connect() as conn:
            r = conn.execute("""
                SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name,
                       cat_l3, cat_l3_name, testing_category, testing_index,
                       use_type, check_type, company_name, catalog_full_name
                FROM ivd_codes WHERE code=?
            """, (code,)).fetchone()
        keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
                "cat_l3", "cat_l3_name", "testing_category", "testing_index",
                "use_type", "check_type", "company_name", "catalog_full_name"]
        d = _row_to_dict(r, keys)
        if not d:
            return jsonify({"code": code, "found": False}), 404
        return jsonify({"code": code, "found": True, "data": d})

    # ============== YP (drugs) ==============
    @app.get("/api/nhsa/yp/search")
    def _yp_search():
        q = (request.args.get("q") or "").strip()
        limit = _limit(50, 500)
        if not q:
            return jsonify({"q": q, "count": 0, "results": []})
        fts = _fts_query(q)
        if not fts:
            return jsonify({"q": q, "count": 0, "results": []})
        with db.connect() as conn:
            try:
                rows = conn.execute("""
                    SELECT code, reg_name, product_name, dosage_form, spec,
                           manufacturer, approval_no
                    FROM yp_codes
                    WHERE id IN (SELECT rowid FROM yp_codes_fts WHERE yp_codes_fts MATCH ?)
                    LIMIT ?
                """, (fts, limit)).fetchall()
            except Exception:
                rows = []
        keys = ["code", "reg_name", "product_name", "dosage_form", "spec",
                "manufacturer", "approval_no"]
        return jsonify({
            "q": q, "count": len(rows),
            "results": [row_to_dict(r, keys) for r in rows],
        })

    @app.get("/api/nhsa/yp/code/<code>")
    def _yp_by_code(code):
        with db.connect() as conn:
            r = conn.execute("""
                SELECT code, reg_name, reg_dosage_form, reg_spec, product_name,
                       dosage_form, spec, packaging, min_pkg_qty, min_prep_unit,
                       min_pkg_unit, manufacturer, approval_no, base_code, list_class
                FROM yp_codes WHERE code=?
            """, (code,)).fetchone()
        keys = ["code", "reg_name", "reg_dosage_form", "reg_spec", "product_name",
                "dosage_form", "spec", "packaging", "min_pkg_qty", "min_prep_unit",
                "min_pkg_unit", "manufacturer", "approval_no", "base_code", "list_class"]
        d = _row_to_dict(r, keys)
        if not d:
            return jsonify({"code": code, "found": False}), 404
        return jsonify({"code": code, "found": True, "data": d})

    @app.get("/api/nhsa/yp/approval/<no>")
    def _yp_by_approval(no):
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT code, reg_name, dosage_form, spec, manufacturer,
                       approval_no, list_class
                FROM yp_codes WHERE approval_no=? LIMIT 50
            """, (no,)).fetchall()
        keys = ["code", "reg_name", "dosage_form", "spec", "manufacturer",
                "approval_no", "list_class"]
        if not rows:
            return jsonify({"approval_no": no, "count": 0, "results": []})
        return jsonify({
            "approval_no": no, "count": len(rows),
            "results": [row_to_dict(r, keys) for r in rows],
        })

    # ============== ICD ==============
    @app.get("/api/nhsa/icd/search")
    def _icd_search():
        q = (request.args.get("q") or "").strip()
        limit = _limit(50, 500)
        if not q:
            return jsonify({"q": q, "count": 0, "results": []})
        fts = _fts_query(q)
        if not fts:
            return jsonify({"q": q, "count": 0, "results": []})
        with db.connect() as conn:
            try:
                rows = conn.execute("""
                    SELECT code, chapter_no, chapter_name, section_name,
                           category_code, category_name, subcategory_code,
                           subcategory_name, diagnosis_name
                    FROM icd_codes
                    WHERE id IN (SELECT rowid FROM icd_codes_fts WHERE icd_codes_fts MATCH ?)
                    LIMIT ?
                """, (fts, limit)).fetchall()
            except Exception:
                rows = []
        keys = ["code", "chapter_no", "chapter_name", "section_name",
                "category_code", "category_name", "subcategory_code",
                "subcategory_name", "diagnosis_name"]
        return jsonify({
            "q": q, "count": len(rows),
            "results": [row_to_dict(r, keys) for r in rows],
        })

    @app.get("/api/nhsa/icd/code/<code>")
    def _icd_by_code(code):
        with db.connect() as conn:
            r = conn.execute("""
                SELECT code, chapter_no, chapter_range, chapter_name,
                       section_range, section_name, category_code, category_name,
                       subcategory_code, subcategory_name, diagnosis_name
                FROM icd_codes WHERE code=? OR diagnosis_code=?
                LIMIT 1
            """, (code, code)).fetchone()
        keys = ["code", "chapter_no", "chapter_range", "chapter_name",
                "section_range", "section_name", "category_code", "category_name",
                "subcategory_code", "subcategory_name", "diagnosis_name"]
        d = _row_to_dict(r, keys)
        if not d:
            return jsonify({"code": code, "found": False}), 404
        return jsonify({"code": code, "found": True, "data": d})

    # ============== MS (medical services) ==============
    @app.get("/api/nhsa/ms/search")
    def _ms_search():
        q = (request.args.get("q") or "").strip()
        limit = _limit(50, 500)
        if not q:
            return jsonify({"q": q, "count": 0, "results": []})
        fts = _fts_query(q)
        if not fts:
            return jsonify({"q": q, "count": 0, "results": []})
        with db.connect() as conn:
            try:
                rows = conn.execute("""
                    SELECT code, name, level, is_using, explain
                    FROM medical_service_codes
                    WHERE id IN (SELECT rowid FROM medical_service_codes_fts
                                 WHERE medical_service_codes_fts MATCH ?)
                    LIMIT ?
                """, (fts, limit)).fetchall()
            except Exception:
                rows = []
        keys = ["code", "name", "level", "is_using", "explain"]
        return jsonify({
            "q": q, "count": len(rows),
            "results": [row_to_dict(r, keys) for r in rows],
        })

    @app.get("/api/nhsa/ms/code/<code>")
    def _ms_by_code(code):
        with db.connect() as conn:
            r = conn.execute("""
                SELECT code, p_code, name, level, level_path,
                       contains_content, excluded_content, charge_unit,
                       explain, area, is_using
                FROM medical_service_codes WHERE code=? LIMIT 1
            """, (code,)).fetchone()
        keys = ["code", "p_code", "name", "level", "level_path",
                "contains_content", "excluded_content", "charge_unit",
                "explain", "area", "is_using"]
        d = _row_to_dict(r, keys)
        if not d:
            return jsonify({"code": code, "found": False}), 404
        return jsonify({"code": code, "found": True, "data": d})

    # ============== TCM ==============
    @app.get("/api/nhsa/tcm/search")
    def _tcm_search():
        q = (request.args.get("q") or "").strip()
        limit = _limit(50, 500)
        if not q:
            return jsonify({"q": q, "count": 0, "results": []})
        fts = _fts_query(q)
        if not fts:
            return jsonify({"q": q, "count": 0, "results": []})
        with db.connect() as conn:
            try:
                rows = conn.execute("""
                    SELECT code, name, level, class_name, apply_explain
                    FROM tcm_codes
                    WHERE id IN (SELECT rowid FROM tcm_codes_fts
                                 WHERE tcm_codes_fts MATCH ?)
                    LIMIT ?
                """, (fts, limit)).fetchall()
            except Exception:
                rows = []
        keys = ["code", "name", "level", "class_name", "apply_explain"]
        return jsonify({
            "q": q, "count": len(rows),
            "results": [row_to_dict(r, keys) for r in rows],
        })

    @app.get("/api/nhsa/tcm/code/<code>")
    def _tcm_by_code(code):
        with db.connect() as conn:
            r = conn.execute("""
                SELECT code, p_code, name, part_code, code_length, level,
                       apply_explain, remark, class_code, class_name
                FROM tcm_codes WHERE code=? LIMIT 1
            """, (code,)).fetchone()
        keys = ["code", "p_code", "name", "part_code", "code_length", "level",
                "apply_explain", "remark", "class_code", "class_name"]
        d = _row_to_dict(r, keys)
        if not d:
            return jsonify({"code": code, "found": False}), 404
        return jsonify({"code": code, "found": True, "data": d})

    # ============== HC7 ==============
    @app.get("/api/nhsa/hc7/code/<code>")
    def _hc7_by_code(code):
        with db.connect() as conn:
            r = conn.execute("""
                SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name,
                       cat_l3, cat_l3_name, generic_category, material,
                       spec, generic_no, generic_name, manufacturer
                FROM consumable7_codes WHERE code=? LIMIT 1
            """, (code,)).fetchone()
        keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
                "cat_l3", "cat_l3_name", "generic_category", "material",
                "spec", "generic_no", "generic_name", "manufacturer"]
        d = _row_to_dict(r, keys)
        if not d:
            return jsonify({"code": code, "found": False}), 404
        return jsonify({"code": code, "found": True, "data": d})
