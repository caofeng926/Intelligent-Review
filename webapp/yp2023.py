"""2023 版药品目录查询页面 + API。
挂载: app.py 里 from . import yp2023; yp2023.register(app)
"""
from __future__ import annotations
import re
from typing import Optional, List, Dict, Any

from flask import render_template, request, jsonify, redirect, url_for, abort

from . import db


CATEGORIES = [("西药", "西药"), ("中成药", "中成药"), ("谈判西药", "谈判西药"), ("谈判中成药", "谈判中成药"), ("中药饮片", "中药饮片")]
CATEGORY_SET = {c for c, _ in CATEGORIES}

PAGE_SIZE = 50


def _limit(default: int = PAGE_SIZE, max_: int = 200) -> int:
    try:
        n = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_))


def _fts_query(q: str) -> Optional[str]:
    q = (q or "").strip()
    if not q:
        return None
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", " ", q).strip()
    if not safe:
        return None
    if re.match(r"^[A-Za-z0-9]+$", safe):
        return safe + "*"
    if len(safe) >= 2:
        return safe[:2] + "*"
    return safe + "*"


def _catalog_stats(conn):
    rows = conn.execute("""
        SELECT category, tcm_payment, COUNT(*) FROM yp_catalog_2023
        GROUP BY category, tcm_payment ORDER BY category
    """).fetchall()
    by_category = {}
    for cat, tcm, n in rows:
        if cat == "中药饮片":
            key = f"{cat}-{'支付' if (tcm or 0)==1 else '不支付'}"
        else:
            key = cat
        by_category[key] = n
    total = conn.execute("SELECT COUNT(*) FROM yp_catalog_2023").fetchone()[0]
    listing_count = conn.execute("SELECT COUNT(*) FROM yp_catalog_listing").fetchone()[0]
    adj_count = conn.execute("SELECT COUNT(*) FROM yp_catalog_adjustments").fetchone()[0]
    return {"by_category": by_category, "total": total, "listing_count": listing_count, "adj_count": adj_count}


def find_specs_via_listing(conn, drug_name):
    rows = conn.execute("""
        SELECT l.yp_code, l.manufacturer, l.spec, l.dosage_form, l.packaging,
               l.access_type, l.source_list, l.min_pkg_qty, l.min_pkg_unit,
               y.reg_name, y.spec AS yp_spec, y.dosage_form AS yp_form, y.manufacturer AS yp_man
        FROM yp_catalog_listing l
        LEFT JOIN yp_codes y ON y.code = l.yp_code
        WHERE l.drug_name = ? AND l.yp_code IS NOT NULL AND l.yp_code != ''
    """, [drug_name]).fetchall()
    return [{
        "yp_code": r[0], "manufacturer": r[1] or r[12], "spec": r[2] or r[10],
        "dosage_form": r[3] or r[11], "packaging": r[4],
        "access_type": r[5], "source_list": r[6],
        "min_pkg_qty": r[7], "min_pkg_unit": r[9],
    } for r in rows]


def find_specs_via_name(conn, name, limit=50):
    norm = name.replace(" ", "").replace("　", "")
    if not norm or len(norm) < 2:
        return []
    rows = conn.execute("""
        SELECT code, reg_name, spec, dosage_form, manufacturer, list_class
        FROM yp_codes
        WHERE REPLACE(REPLACE(IFNULL(reg_name,''),' ',''),'　','') LIKE ?
        LIMIT ?
    """, [f"%{norm}%", limit]).fetchall()
    return [{"code": r[0], "reg_name": r[1], "spec": r[2],
             "dosage_form": r[3], "manufacturer": r[4], "list_class": r[5]} for r in rows]


def register(app):
    @app.get("/yp2023")
    @app.get("/yp2023/")
    def yp2023_browse():
        q = (request.args.get("q") or "").strip()
        cat = request.args.get("cat") or "西药"
        list_class = request.args.get("list_class") or None
        try:
            page = max(1, int(request.args.get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        limit = PAGE_SIZE
        offset = (page - 1) * limit
        with db.connect() as conn:
            stats = _catalog_stats(conn)
            where = ["category = ?"]
            params = [cat]
            if cat == "中药饮片":
                tcm = request.args.get("tcm")
                if tcm == "0":
                    where.append("tcm_payment = 0")
                else:
                    where.append("tcm_payment = 1")
            if list_class in ("甲", "乙", "商保"):
                where.append("list_class = ?")
                params.append(list_class)
            if q:
                fts = _fts_query(q)
                if fts:
                    where.append("id IN (SELECT rowid FROM yp_catalog_fts WHERE yp_catalog_fts MATCH ?)")
                    params.append(fts)
                else:
                    where.append("name LIKE ?")
                    params.append(f"%{q}%")
            where_sql = " WHERE " + " AND ".join(where)
            total = conn.execute(f"SELECT COUNT(*) FROM yp_catalog_2023{where_sql}", params).fetchone()[0]
            rows = conn.execute(f"""
                SELECT id, code, name, category, list_class, payment_standard,
                       subcategory, dosage_form, spec_count, manufacturer_count, remark
                FROM yp_catalog_2023{where_sql}
                ORDER BY category, CAST(code AS INTEGER), code
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0], "code": r[1], "name": r[2], "category": r[3],
                "list_class": r[4], "payment_standard": r[5],
                "subcategory": r[6], "dosage_form": r[7],
                "spec_count": r[8], "manufacturer_count": r[9], "remark": r[10],
            })
        return render_template(
            "yp2023.html",
            q=q, cat=cat, list_class=list_class, page=page, total=total,
            results=result, stats=stats, categories=CATEGORIES,
            page_size=limit,
        )

    @app.get("/yp2023/<code>")
    def yp2023_detail(code):
        # 兼容非数字 code(如 "★(1005)")
        code_str = str(code)
        with db.connect() as conn:
            row = conn.execute("""
                SELECT id, code, name, category, tcm_payment, list_class, payment_standard,
                       payment_validity, dosage_form, subcategory, remark,
                       spec_count, manufacturer_count, category_code, sheet_source
                FROM yp_catalog_2023 WHERE code = ? LIMIT 1
            """, [code_str]).fetchone()
            if not row:
                abort(404)
            catalog = {
                "id": row[0], "code": row[1], "name": row[2], "category": row[3],
                "tcm_payment": row[4], "list_class": row[5],
                "payment_standard": row[6], "payment_validity": row[7],
                "dosage_form": row[8], "subcategory": row[9], "remark": row[10],
                "spec_count": row[11], "manufacturer_count": row[12],
                "category_code": row[13], "sheet_source": row[14],
            }
            adj_rows = conn.execute("""
                SELECT change_type, drug_category, change_detail, list_no, source_sheet
                FROM yp_catalog_adjustments WHERE drug_name = ?
                ORDER BY id
            """, [row[2]]).fetchall()
            adjustments = [{"change_type": a[0], "drug_category": a[1], "change_detail": a[2],
                            "list_no": a[3], "source_sheet": a[4]} for a in adj_rows]
            listings = find_specs_via_listing(conn, row[2])
            specs_via_name = []
            if not listings:
                specs_via_name = find_specs_via_name(conn, row[2], limit=30)
            cross_cats = conn.execute("""
                SELECT code, category, list_class FROM yp_catalog_2023 WHERE name = ? ORDER BY category
            """, [row[2]]).fetchall()
            cross = [{"code": c[0], "category": c[1], "list_class": c[2]} for c in cross_cats]
        return render_template(
            "yp2023_detail.html",
            catalog=catalog, adjustments=adjustments, listings=listings,
            specs_via_name=specs_via_name, cross=cross,
        )

    @app.get("/api/yp2023/search")
    def api_yp2023_search():
        q = (request.args.get("q") or "").strip()
        cat = request.args.get("cat")
        limit = _limit(default=20, max_=100)
        if not q:
            return jsonify({"error": "q is required"}), 400
        with db.connect() as conn:
            fts = _fts_query(q)
            params = []
            where = []
            if fts:
                where.append("id IN (SELECT rowid FROM yp_catalog_fts WHERE yp_catalog_fts MATCH ?)")
                params.append(fts)
            else:
                where.append("name LIKE ?")
                params.append(f"%{q}%")
            if cat and cat in CATEGORY_SET:
                where.append("category = ?")
                params.append(cat)
            where_sql = " WHERE " + " AND ".join(where)
            rows = conn.execute(f"""
                SELECT code, name, category, list_class, payment_standard,
                       spec_count, manufacturer_count
                FROM yp_catalog_2023{where_sql}
                ORDER BY category, CAST(code AS INTEGER)
                LIMIT ?
            """, params + [limit]).fetchall()
            return jsonify({"q": q, "cat": cat, "total": len(rows), "results": [
                {"code": r[0], "name": r[1], "category": r[2],
                 "list_class": r[3], "payment_standard": r[4],
                 "spec_count": r[5], "manufacturer_count": r[6]} for r in rows
            ]})

    @app.get("/api/yp2023/stats")
    def api_yp2023_stats():
        with db.connect() as conn:
            return jsonify(_catalog_stats(conn))
