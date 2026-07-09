"""NHSA reference database browse pages.

Mounted by app.py via:
    from . import nhsa_browse
    nhsa_browse.register(app)
"""
from __future__ import annotations
import re
from typing import Optional, List, Dict, Any

from flask import render_template, request, jsonify, redirect, url_for, abort

from . import db
from .query_utils import fts_query as _fts_query
from .query_utils import row_to_dict


PAGE_SIZE = 50


def _limit(default: int = PAGE_SIZE, max_: int = 200) -> int:
    try:
        n = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_))


def _rules_for_codes(conn, codes):
    if not codes:
        return []
    qmarks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT DISTINCT r.id, r.rule_subject, b.batch_label, b.pub_date "
        f"FROM knowledge_point_codes kpc "
        f"JOIN knowledge_points kp ON kp.id = kpc.kp_id "
        f"JOIN rules r ON r.id = kp.rule_id "
        f"JOIN batches b ON b.id = r.batch_id "
        f"WHERE kpc.code IN ({qmarks}) "
        f"ORDER BY b.id DESC LIMIT 20",
        codes,
    ).fetchall()
    return [
        {"rule_id": r[0], "rule_subject": r[1], "batch_label": r[2], "pub_date": r[3]}
        for r in rows
    ]


def _nhsa_counts(conn):
    out = {}
    for tbl in ["consumable_codes", "drug_detail", "yp_codes", "ivd_codes",
                "consumable7_codes", "icd_codes", "medical_service_codes",
                "tcm_codes", "nhsa_batches"]:
        try:
            out[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception:
            out[tbl] = 0
    return out

def _kps_for_codes(conn, code):
    """Return KPs (knowledge points) that reference the given code.
    Used to show bidirectional link: code detail -> KPs -> rules.
    """
    if not code:
        return []
    rows = conn.execute(
        "SELECT DISTINCT kp.id, kp.subject_name, kp.code_count, "
        "       r.id, r.rule_subject, b.batch_label, b.pub_date "
        "FROM knowledge_point_codes kpc "
        "JOIN knowledge_points kp ON kp.id = kpc.kp_id "
        "JOIN rules r ON r.id = kp.rule_id "
        "JOIN batches b ON b.id = r.batch_id "
        "WHERE kpc.code = ? "
        "ORDER BY b.id DESC LIMIT 30",
        (code,),
    ).fetchall()
    return [
        {
            "kp_id": r[0],
            "kp_name": r[1],
            "kp_code_count": r[2],
            "rule_id": r[3],
            "rule_subject": r[4],
            "batch_label": r[5],
            "pub_date": r[6],
        }
        for r in rows
    ]




# ============================================================
# Shaanxi Medical Service 2021 helpers
# ============================================================
def _sn_ms_search(conn, q, limit):
    """FTS5 + LIKE fallback search for SN-MS code/name/content."""
    from .query_utils import fts_query as _q_fts
    fts = _q_fts(q)
    if not fts:
        return [], 0
    try:
        rows = conn.execute(
            "SELECT code, p_code, name, level, sheet_name, fin_class, unit, "
            "       price_l1, price_l2, price_l3 "
            "FROM sn_ms_codes "
            "WHERE id IN (SELECT rowid FROM sn_ms_codes_fts WHERE sn_ms_codes_fts MATCH ?) "
            "ORDER BY sheet_name, code LIMIT ?",
            (fts, limit),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM sn_ms_codes "
            "WHERE id IN (SELECT rowid FROM sn_ms_codes_fts WHERE sn_ms_codes_fts MATCH ?)",
            (fts,),
        ).fetchone()[0]
        keys = ["code", "p_code", "name", "level", "sheet_name", "fin_class",
                "unit", "price_l1", "price_l2", "price_l3"]
        return [row_to_dict(r, keys) for r in rows], total
    except Exception:
        like = "%" + q.strip() + "%"
        rows = conn.execute(
            "SELECT code, p_code, name, level, sheet_name, fin_class, unit, "
            "       price_l1, price_l2, price_l3 "
            "FROM sn_ms_codes "
            "WHERE name LIKE ? OR code LIKE ? OR content LIKE ? "
            "ORDER BY sheet_name, code LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        keys = ["code", "p_code", "name", "level", "sheet_name", "fin_class",
                "unit", "price_l1", "price_l2", "price_l3"]
        return [row_to_dict(r, keys) for r in rows], len(rows)


def _sn_ms_ancestors(conn, sheet, parent_digits):
    """Build breadcrumb (sheet, ancestors at L2/L4/L6) for a given parent code."""
    items = []
    if not parent_digits:
        return items
    n = len(parent_digits)
    cuts = [2, 4, 6]
    for c in cuts:
        if c > n:
            break
        d = parent_digits[:c]
        row = conn.execute(
            "SELECT code, name FROM sn_ms_codes WHERE sheet_name=? AND code=?",
            (sheet, d),
        ).fetchone()
        if row:
            items.append({"code": row[0], "name": row[1]})
    return items


def _has_l4(conn, sheet):
    return conn.execute(
        "SELECT 1 FROM sn_ms_codes WHERE sheet_name=? AND level=4 LIMIT 1",
        (sheet,),
    ).fetchone() is not None


# ============================================================
# registration
# ============================================================
def register(app):

    # ---------------- /nhsa index ----------------
    @app.get("/nhsa/")
    @app.get("/nhsa")
    def nhsa_index():
        with db.connect() as conn:
            counts = _nhsa_counts(conn)
            total = sum(v for k, v in counts.items() if k != "nhsa_batches")
        return render_template("nhsa_index.html", counts=counts, total_codes=total)

    # ==================== IVD ====================
    @app.get("/nhsa/ivd/")
    @app.get("/nhsa/ivd")
    def ivd_browse():
        q = (request.args.get("q") or "").strip()
        testing_category = request.args.get("testing_category") or ""
        limit = _limit()
        with db.connect() as conn:
            total_all = conn.execute("SELECT COUNT(*) FROM ivd_codes").fetchone()[0]
            if testing_category:
                rows = conn.execute(
                    "SELECT code, catalog_full_name, testing_index, testing_category, company_name "
                    "FROM ivd_codes WHERE testing_category=? ORDER BY code LIMIT ?",
                    (testing_category, limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM ivd_codes WHERE testing_category=?",
                    (testing_category,),
                ).fetchone()[0]
                return render_template(
                    "ivd.html",
                    groups=[], total_codes=total_all,
                    testing_category=testing_category, query=q,
                    rows=[row_to_dict(r, ["code", "catalog_full_name", "testing_index", "testing_category", "company_name"])
                        for r in rows],
                    total=total)
            if q:
                fts = _fts_query(q)
                if fts:
                    try:
                        rows = conn.execute(
                            "SELECT code, catalog_full_name, testing_index, testing_category, company_name "
                            "FROM ivd_codes "
                            "WHERE id IN (SELECT rowid FROM ivd_codes_fts WHERE ivd_codes_fts MATCH ?) "
                            "ORDER BY code LIMIT ?",
                            (fts, limit),
                        ).fetchall()
                        total = len(rows)
                    except Exception:
                        rows, total = [], 0
                else:
                    rows, total = [], 0
                return render_template(
                    "ivd.html",
                    groups=[], total_codes=total_all,
                    testing_category="", query=q,
                    rows=[row_to_dict(r, ["code", "catalog_full_name", "testing_index", "testing_category", "company_name"])
                        for r in rows],
                    total=total)
            groups = conn.execute(
                "SELECT testing_category, COUNT(*) AS code_count "
                "FROM ivd_codes "
                "WHERE testing_category IS NOT NULL AND testing_category != '' "
                "GROUP BY testing_category ORDER BY code_count DESC"
            ).fetchall()
            return render_template(
                "ivd.html",
                groups=[{"testing_category": g[0], "code_count": g[1]} for g in groups],
                total_codes=total_all, testing_category="", query="",
                rows=[], total=total_all)

    @app.get("/nhsa/ivd/code/<code>")
    def ivd_detail(code):
        with db.connect() as conn:
            r = conn.execute(
                "SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name, "
                "testing_category, testing_index, use_type, check_type, "
                "company_name, business_license, spec_code, catalog_full_name "
                "FROM ivd_codes WHERE code=?",
                (code,),
            ).fetchone()
            keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name", "cat_l3", "cat_l3_name",
                    "testing_category", "testing_index", "use_type", "check_type",
                    "company_name", "business_license", "spec_code", "catalog_full_name"]
            data = row_to_dict(r, keys) if r else None
            rules = _rules_for_codes(conn, [code]) if data else []
            kps = _kps_for_codes(conn, code) if data else []
        return render_template(
            "nhsa_detail.html",
            code_kind="ivd",
            code=code, data=data, name=(data or {}).get("catalog_full_name") or "体外诊断试剂",
            title="体外诊断试剂", index_url=url_for("ivd_browse"),
            code_field="code", name_field="catalog_full_name", kps=kps, rules=rules,
            labels={
                "cat_l1": "一级分类", "cat_l1_name": "一级名称",
                "cat_l2": "二级分类", "cat_l2_name": "二级名称",
                "cat_l3": "三级分类", "cat_l3_name": "三级名称",
                "testing_category": "检测类别",
                "testing_index": "检测项目",
                "use_type": "使用类型",
                "check_type": "检验类型",
                "company_name": "生产企业",
                "business_license": "营业执照",
                "spec_code": "规格代码",
                "catalog_full_name": "产品目录名称",
            })

    # ==================== YP ====================
    @app.get("/nhsa/yp/")
    @app.get("/nhsa/yp")
    def yp_browse():
        q = (request.args.get("q") or "").strip()
        list_class = (request.args.get("list_class") or "").strip()
        limit = _limit()
        with db.connect() as conn:
            total_all = conn.execute("SELECT COUNT(*) FROM yp_codes").fetchone()[0]
            counts_raw = conn.execute(
                "SELECT CASE WHEN list_class IS NULL OR list_class = '' THEN '' "
                "ELSE list_class END, COUNT(*) FROM yp_codes GROUP BY 1"
            ).fetchall()
            counts = {row[0]: row[1] for row in counts_raw}
            where, params = [], []
            if list_class and list_class != "全部":
                if list_class == "未分类":
                    where.append("(list_class IS NULL OR list_class = '')")
                else:
                    where.append("list_class = ?")
                    params.append(list_class)
            if q:
                fts = _fts_query(q)
                if fts:
                    try:
                        where.append("id IN (SELECT rowid FROM yp_codes_fts WHERE yp_codes_fts MATCH ?)")
                        params.append(fts)
                    except Exception:
                        pass
                else:
                    wild = "%" + q + "%"
                    where.append("(reg_name LIKE ? OR product_name LIKE ? OR approval_no LIKE ? OR code LIKE ?)")
                    params.extend([wild, wild, wild, wild])
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            total = conn.execute(
                f"SELECT COUNT(*) FROM yp_codes {where_sql}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT code, reg_name, product_name, dosage_form, spec, manufacturer, list_class "
                f"FROM yp_codes {where_sql} ORDER BY code LIMIT ?",
                params + [limit],
            ).fetchall()
            keys = ["code", "reg_name", "product_name", "dosage_form", "spec", "manufacturer", "list_class"]
            rows = [row_to_dict(r, keys) for r in rows]
        return render_template(
            "yp.html", total_codes=total_all,
            rows=rows, total=total, query=q,
            list_class=(list_class if list_class else "全部"), counts=counts)

    @app.get("/nhsa/yp/code/<code>")
    def yp_detail(code):
        with db.connect() as conn:
            r = conn.execute(
                "SELECT code, reg_name, reg_dosage_form, reg_spec, product_name, "
                "dosage_form, spec, packaging, min_pkg_qty, min_prep_unit, "
                "min_pkg_unit, manufacturer, approval_no, base_code, list_class "
                "FROM yp_codes WHERE code=?",
                (code,),
            ).fetchone()
            keys = ["code", "reg_name", "reg_dosage_form", "reg_spec", "product_name",
                    "dosage_form", "spec", "packaging", "min_pkg_qty", "min_prep_unit",
                    "min_pkg_unit", "manufacturer", "approval_no", "base_code", "list_class"]
            data = row_to_dict(r, keys) if r else None
            rules = _rules_for_codes(conn, [code]) if data else []
            kps = _kps_for_codes(conn, code) if data else []
        name = (data or {}).get("reg_name") or (data or {}).get("product_name") or "医保药品"
        return render_template(
            "nhsa_detail.html",
            code_kind="yp",
            code=code, data=data, name=name,
            title="医保药品", index_url=url_for("yp_browse"),
            code_field="code", name_field="reg_name", kps=kps, rules=rules,
            labels={
                "reg_name": "注册名称",
                "reg_dosage_form": "注册剂型",
                "reg_spec": "注册规格",
                "product_name": "产品名称",
                "dosage_form": "实际剂型",
                "spec": "实际规格",
                "packaging": "包装",
                "min_pkg_qty": "最小包装数量",
                "min_prep_unit": "最小制剂单位",
                "min_pkg_unit": "最小包装单位",
                "manufacturer": "生产企业",
                "approval_no": "批准文号",
                "base_code": "基础码",
                "list_class": "目录类别",
            })

    # ==================== ICD ====================
    @app.get("/nhsa/icd/")
    @app.get("/nhsa/icd")
    @app.get("/nhsa/icd/cat/<chapter_no>")
    def icd_browse(chapter_no=None):
        q = (request.args.get("q") or "").strip()
        if chapter_no is None:
            chapter_no = request.args.get("chapter_no") or ""
        limit = _limit()
        with db.connect() as conn:
            total_all = conn.execute("SELECT COUNT(*) FROM icd_codes").fetchone()[0]
            if chapter_no:
                ch = conn.execute(
                    "SELECT chapter_name FROM icd_codes WHERE chapter_no=? LIMIT 1",
                    (chapter_no,),
                ).fetchone()
                ch_name = ch[0] if ch else ""
                rows = conn.execute(
                    "SELECT code, diagnosis_code, diagnosis_name, category_name, section_name "
                    "FROM icd_codes WHERE chapter_no=? ORDER BY code LIMIT ?",
                    (chapter_no, limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM icd_codes WHERE chapter_no=?",
                    (chapter_no,),
                ).fetchone()[0]
                return render_template(
                    "icd.html",
                    groups=[], total_codes=total_all,
                    chapter_no=chapter_no, chapter_name=ch_name, query=q,
                    rows=[row_to_dict(r, ["code", "diagnosis_code", "diagnosis_name", "category_name", "section_name"])
                        for r in rows],
                    total=total)
            if q:
                fts = _fts_query(q)
                if fts:
                    try:
                        rows = conn.execute(
                            "SELECT code, diagnosis_code, diagnosis_name, category_name, section_name "
                            "FROM icd_codes "
                            "WHERE id IN (SELECT rowid FROM icd_codes_fts WHERE icd_codes_fts MATCH ?) "
                            "ORDER BY code LIMIT ?",
                            (fts, limit),
                        ).fetchall()
                        total = len(rows)
                    except Exception:
                        rows, total = [], 0
                else:
                    rows, total = [], 0
                return render_template(
                    "icd.html",
                    groups=[], total_codes=total_all,
                    chapter_no="", chapter_name="", query=q,
                    rows=[row_to_dict(r, ["code", "diagnosis_code", "diagnosis_name", "category_name", "section_name"])
                        for r in rows],
                    total=total)
            groups = conn.execute(
                "SELECT chapter_no, chapter_name, COUNT(*) AS code_count "
                "FROM icd_codes "
                "WHERE chapter_no IS NOT NULL AND chapter_no != '' "
                "GROUP BY chapter_no, chapter_name "
                "ORDER BY CAST(chapter_no AS INT)"
            ).fetchall()
            return render_template(
                "icd.html",
                groups=[{"chapter_no": g[0], "chapter_name": g[1], "code_count": g[2]} for g in groups],
                total_codes=total_all, chapter_no="", chapter_name="", query="",
                rows=[], total=total_all)

    @app.get("/nhsa/icd/code/<code>")
    def icd_detail(code):
        with db.connect() as conn:
            # 按精确度分层级匹配:
            # 1. code=?           (亚目/扩展码/类目如果直接存为 code)
            # 2. diagnosis_code=? (扩展码)
            # 3. category_code=?  (类目 A00)
            # 4. subcategory_code=?  (亚目 A00.0)
            # SELECT 末尾加一列 "_match" 标识命中层级, 让 name/diagnosis_name 字段可分级呈现
            sql = (
                # 1. code 直接匹配 -> name = diagnosis_name (or category_name)
                "SELECT code, chapter_no, chapter_range, chapter_name, section_range, section_name, "
                "category_code, category_name, subcategory_code, subcategory_name, "
                "diagnosis_code, diagnosis_name, COALESCE(diagnosis_name, category_name) AS _name, 1 AS _match "
                "FROM icd_codes WHERE code=? "
                # 2. diagnosis_code 匹配 -> name = diagnosis_name
                "UNION ALL SELECT code, chapter_no, chapter_range, chapter_name, section_range, section_name, "
                "category_code, category_name, subcategory_code, subcategory_name, "
                "diagnosis_code, diagnosis_name, diagnosis_name AS _name, 2 AS _match "
                "FROM icd_codes WHERE diagnosis_code=? AND code<>? "
                # 3. category_code 匹配 -> name = category_name
                "UNION ALL SELECT code, chapter_no, chapter_range, chapter_name, section_range, section_name, "
                "category_code, category_name, subcategory_code, subcategory_name, "
                "diagnosis_code, diagnosis_name, category_name AS _name, 3 AS _match "
                "FROM icd_codes WHERE category_code=? AND code<>? AND diagnosis_code<>? "
                # 4. subcategory_code 匹配 -> name = subcategory_name
                "UNION ALL SELECT code, chapter_no, chapter_range, chapter_name, section_range, section_name, "
                "category_code, category_name, subcategory_code, subcategory_name, "
                "diagnosis_code, diagnosis_name, subcategory_name AS _name, 4 AS _match "
                "FROM icd_codes WHERE subcategory_code=? AND code<>? AND diagnosis_code<>? AND category_code<>? "
                "LIMIT 1"
            )
            r = conn.execute(sql, (code, code, code, code, code, code, code, code, code, code)).fetchone()
            keys = ["code", "chapter_no", "chapter_range", "chapter_name",
                    "section_range", "section_name", "category_code", "category_name",
                    "subcategory_code", "subcategory_name", "diagnosis_code", "diagnosis_name",
                    "_name", "_match"]
            data = row_to_dict(r, keys) if r else None
            if data:
                # 显示匹配的层级名 (4 个 SELECT 各自返回该层级的名字)
                data["display_name"] = data.pop("_name")
                data.pop("_match", None)
            rules = _rules_for_codes(conn, [code]) if data else []
            kps = _kps_for_codes(conn, code) if data else []
        name = (data or {}).get("display_name") or "ICD 诊断"
        return render_template(
            "nhsa_detail.html",
            code_kind="icd",
            code=code, data=data, name=name,
            title="ICD-10 诊断编码", index_url=url_for("icd_browse"),
            code_field="code", name_field="diagnosis_name", kps=kps, rules=rules,
            labels={
                "chapter_no": "章节号",
                "chapter_range": "章节范围",
                "chapter_name": "章节名称",
                "section_range": "节范围",
                "section_name": "节名称",
                "category_code": "类目编码",
                "category_name": "类目名称",
                "subcategory_code": "亚目编码",
                "subcategory_name": "亚目名称",
                "diagnosis_code": "诊断扩展码",
                "diagnosis_name": "诊断名称",
            })

    # ==================== MS ====================
    @app.get("/nhsa/ms/")
    @app.get("/nhsa/ms")
    def ms_browse():
        q = (request.args.get("q") or "").strip()
        level = request.args.get("level") or ""
        limit = _limit()
        with db.connect() as conn:
            total_all = conn.execute("SELECT COUNT(*) FROM medical_service_codes").fetchone()[0]
            if q:
                fts = _fts_query(q)
                if fts:
                    try:
                        rows = conn.execute(
                            "SELECT code, p_code, level, name, charge_unit, explain "
                            "FROM medical_service_codes "
                            "WHERE id IN (SELECT rowid FROM medical_service_codes_fts "
                            "WHERE medical_service_codes_fts MATCH ?) "
                            "ORDER BY code LIMIT ?",
                            (fts, limit),
                        ).fetchall()
                        total = len(rows)
                    except Exception:
                        rows, total = [], 0
                else:
                    rows, total = [], 0
                return render_template(
                    "ms.html",
                    groups=[], total_codes=total_all,
                    query=q, level="",
                    rows=[row_to_dict(r, ["code", "p_code", "level", "name", "charge_unit", "explain"])
                        for r in rows],
                    total=total)
            if level:
                rows = conn.execute(
                    "SELECT code, p_code, level, name, charge_unit, explain "
                    "FROM medical_service_codes WHERE level=? ORDER BY code LIMIT ?",
                    (int(level), limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM medical_service_codes WHERE level=?",
                    (int(level),),
                ).fetchone()[0]
                return render_template(
                    "ms.html",
                    groups=[], total_codes=total_all,
                    query="", level=level,
                    rows=[row_to_dict(r, ["code", "p_code", "level", "name", "charge_unit", "explain"])
                        for r in rows],
                    total=total)
            groups = conn.execute(
                "SELECT level, COUNT(*) AS code_count, MIN(p_code) AS p_code, "
                "CASE WHEN level=0 THEN '顶级分类' "
                "WHEN level=1 THEN '大类' "
                "WHEN level=2 THEN '中类' "
                "ELSE '项目' END AS p_name "
                "FROM medical_service_codes GROUP BY level ORDER BY level"
            ).fetchall()
            return render_template(
                "ms.html",
                groups=[{"level": g[0], "code_count": g[1], "p_code": g[2], "p_name": g[3]}
                        for g in groups],
                total_codes=total_all, query="", level="",
                rows=[], total=total_all)

    @app.get("/nhsa/ms/code/<code>")
    def ms_detail(code):
        with db.connect() as conn:
            r = conn.execute(
                "SELECT code, p_code, name, level, level_path, pinyin_code, "
                "contains_content, excluded_content, charge_unit, explain, "
                "area, is_using "
                "FROM medical_service_codes WHERE code=?",
                (code,),
            ).fetchone()
            keys = ["code", "p_code", "name", "level", "level_path", "pinyin_code",
                    "contains_content", "excluded_content", "charge_unit", "explain",
                    "area", "is_using"]
            data = row_to_dict(r, keys) if r else None
            rules = _rules_for_codes(conn, [code]) if data else []
            kps = _kps_for_codes(conn, code) if data else []
        return render_template(
            "nhsa_detail.html",
            code_kind="ms",
            code=code, data=data, name=(data or {}).get("name") or "医疗服务项目",
            title="医疗服务项目", index_url=url_for("ms_browse"),
            code_field="code", name_field="name", kps=kps, rules=rules,
            labels={
                "p_code": "父编码",
                "level": "层级",
                "level_path": "层级路径",
                "pinyin_code": "拼音首字母",
                "contains_content": "服务内容",
                "excluded_content": "除外内容",
                "charge_unit": "计价单位",
                "explain": "说明",
                "area": "适用范围",
                "is_using": "是否在用",
            })

    # ==================== TCM ====================
    @app.get("/nhsa/tcm/")
    @app.get("/nhsa/tcm")
    def tcm_browse():
        q = (request.args.get("q") or "").strip()
        part = (request.args.get("part") or "").strip().upper()
        level = request.args.get("level") or ""
        limit = _limit()
        with db.connect() as conn:
            total_all = conn.execute("SELECT COUNT(*) FROM tcm_codes").fetchone()[0]
            if q:
                fts = _fts_query(q)
                if fts:
                    try:
                        rows = conn.execute(
                            "SELECT code, p_code, level, name, class_name, apply_explain "
                            "FROM tcm_codes "
                            "WHERE id IN (SELECT rowid FROM tcm_codes_fts WHERE tcm_codes_fts MATCH ?) "
                            "ORDER BY code LIMIT ?",
                            (fts, limit),
                        ).fetchall()
                        total = len(rows)
                    except Exception:
                        rows, total = [], 0
                else:
                    rows, total = [], 0
                return render_template(
                    "tcm.html",
                    total_codes=total_all, query=q,
                    parts=[], levels=[],
                    rows=[row_to_dict(r, ["code", "p_code", "level", "name", "class_name", "apply_explain"])
                        for r in rows],
                    total=total, part="", level="")
            if part in ("B", "Z"):
                rows = conn.execute(
                    "SELECT code, p_code, level, name, class_name, apply_explain "
                    "FROM tcm_codes WHERE part_code=? ORDER BY code LIMIT ?",
                    (part, limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM tcm_codes WHERE part_code=?", (part,)
                ).fetchone()[0]
                return render_template(
                    "tcm.html",
                    total_codes=total_all, query="",
                    parts=[], levels=[],
                    rows=[row_to_dict(r, ["code", "p_code", "level", "name", "class_name", "apply_explain"])
                        for r in rows],
                    total=total, part=part, level="")
            if level.isdigit():
                lv = int(level)
                rows = conn.execute(
                    "SELECT code, p_code, level, name, class_name, apply_explain "
                    "FROM tcm_codes WHERE level=? ORDER BY code LIMIT ?",
                    (lv, limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM tcm_codes WHERE level=?", (lv,)
                ).fetchone()[0]
                return render_template(
                    "tcm.html",
                    total_codes=total_all, query="",
                    parts=[], levels=[],
                    rows=[row_to_dict(r, ["code", "p_code", "level", "name", "class_name", "apply_explain"])
                        for r in rows],
                    total=total, part="", level=str(lv))
            parts = conn.execute(
                "SELECT part_code, COUNT(*) AS c FROM tcm_codes "
                "GROUP BY part_code ORDER BY part_code"
            ).fetchall()
            levels = conn.execute(
                "SELECT level, COUNT(*) AS c FROM tcm_codes GROUP BY level ORDER BY level"
            ).fetchall()
            return render_template(
                "tcm.html", total_codes=total_all, query="",
                parts=[{"part_code": p[0], "count": p[1]} for p in parts],
                levels=[{"level": p[0], "count": p[1]} for p in levels],
                rows=[], total=total_all, part="", level="")

    @app.get("/nhsa/tcm/code/<code>")
    def tcm_detail(code):
        with db.connect() as conn:
            r = conn.execute(
                "SELECT code, p_code, name, part_code, code_length, level, "
                "apply_explain, remark, class_code, class_name "
                "FROM tcm_codes WHERE code=?",
                (code,),
            ).fetchone()
            keys = ["code", "p_code", "name", "part_code", "code_length", "level",
                    "apply_explain", "remark", "class_code", "class_name"]
            data = row_to_dict(r, keys) if r else None
            rules = _rules_for_codes(conn, [code]) if data else []
            kps = _kps_for_codes(conn, code) if data else []
        return render_template(
            "nhsa_detail.html",
            code_kind="tcm",
            code=code, data=data, name=(data or {}).get("name") or "中药饮片",
            title="中药饮片", index_url=url_for("tcm_browse"),
            code_field="code", name_field="name", kps=kps, rules=rules,
            labels={
                "p_code": "父编码",
                "part_code": "部位编码",
                "code_length": "编码长度",
                "level": "层级",
                "apply_explain": "应用说明",
                "remark": "备注",
                "class_code": "分类编码",
                "class_name": "分类名称",
            })

    # ==================== HC7 ====================
    @app.get("/nhsa/hc7/")
    @app.get("/nhsa/hc7")
    def hc7_index():
        q = (request.args.get("q") or "").strip()
        limit = _limit()
        with db.connect() as conn:
            total_all = conn.execute("SELECT COUNT(*) FROM consumable7_codes").fetchone()[0]
            if q:
                wild = f"%{q}%"
                rows = conn.execute(
                    "SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name, "
                    "generic_category, material, spec, generic_no, generic_name, manufacturer "
                    "FROM consumable7_codes "
                    "WHERE code LIKE ? OR generic_name LIKE ? OR manufacturer LIKE ? "
                    "OR cat_l1_name LIKE ? OR cat_l3_name LIKE ? "
                    "ORDER BY code LIMIT ?",
                    (wild, wild, wild, wild, wild, limit),
                ).fetchall()
                total = len(rows)
            else:
                rows = conn.execute(
                    "SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name, "
                    "generic_category, material, spec, generic_no, generic_name, manufacturer "
                    "FROM consumable7_codes ORDER BY code LIMIT ?",
                    (limit,),
                ).fetchall()
                total = total_all
            keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
                    "cat_l3", "cat_l3_name", "generic_category", "material",
                    "spec", "generic_no", "generic_name", "manufacturer"]
            rows = [row_to_dict(r, keys) for r in rows]
        return render_template(
            "hc7.html",
            total_codes=total_all, query=q,
            rows=rows, total=total)

    @app.get("/nhsa/hc7/code/<code>")
    def hc7_detail(code):
        with db.connect() as conn:
            r = conn.execute(
                "SELECT code, cat_l1, cat_l1_name, cat_l2, cat_l2_name, cat_l3, cat_l3_name, "
                "generic_category, material, spec, generic_no, generic_name, manufacturer "
                "FROM consumable7_codes WHERE code=?",
                (code,),
            ).fetchone()
            keys = ["code", "cat_l1", "cat_l1_name", "cat_l2", "cat_l2_name",
                    "cat_l3", "cat_l3_name", "generic_category", "material",
                    "spec", "generic_no", "generic_name", "manufacturer"]
            data = row_to_dict(r, keys) if r else None
            rules = _rules_for_codes(conn, [code]) if data else []
            kps = _kps_for_codes(conn, code) if data else []
        return render_template(
            "nhsa_detail.html",
            code_kind="hc",
            code=code, data=data, name=(data or {}).get("generic_name") or "7 类医用耗材",
            title="7 类医用耗材", index_url=url_for("hc7_index"),
            code_field="code", name_field="generic_name", kps=kps, rules=rules,
            labels={
                "cat_l1": "一级分类", "cat_l1_name": "一级名称",
                "cat_l2": "二级分类", "cat_l2_name": "二级名称",
                "cat_l3": "三级分类", "cat_l3_name": "三级名称",
                "generic_category": "通用名分类",
                "material": "材质",
                "spec": "规格",
                "generic_no": "通用名编号",
                "generic_name": "通用名",
                "manufacturer": "生产企业",
            })


    # ==================== Shaanxi Medical Service Pricing 2021 ====================
    # 数据源: xlsx with 8 sheets. Levels: L1=sheet, L2=2-digit, L3=4-digit,
    # L4=6-digit, L5=9-digit +/- alpha suffix.
    # =============================================================================

    @app.get("/nhsa/sn_ms/")
    @app.get("/nhsa/sn_ms")
    def sn_ms_index():
        """入口: 列出 8 个 sheet 卡片 + 总数 + 简易搜索."""
        q = (request.args.get("q") or "").strip()
        limit = _limit()
        with db.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sn_ms_codes").fetchone()[0]
            sheets_raw = conn.execute(
                "SELECT sheet_name, sheet_title, COUNT(*) AS cnt, "
                "       SUM(CASE WHEN level=2 THEN 1 ELSE 0 END) AS l2, "
                "       SUM(CASE WHEN level=3 THEN 1 ELSE 0 END) AS l3, "
                "       SUM(CASE WHEN level=4 THEN 1 ELSE 0 END) AS l4, "
                "       SUM(CASE WHEN level=5 THEN 1 ELSE 0 END) AS l5 "
                "FROM sn_ms_codes GROUP BY sheet_name, sheet_title ORDER BY sheet_name"
            ).fetchall()
            sheet_stats = [
                {
                    "sheet_name": s[0], "sheet_title": s[1], "total": s[2],
                    "l2": s[3] or 0, "l3": s[4] or 0, "l4": s[5] or 0, "l5": s[6] or 0,
                }
                for s in sheets_raw
            ]
            if q:
                rows, total_q = _sn_ms_search(conn, q, limit)
                return render_template(
                    "sn_ms.html", mode="search",
                    query=q, total_codes=total,
                    sheets=sheet_stats, rows=rows, total=total_q,
                )
        return render_template(
            "sn_ms.html", mode="index",
            query="", total_codes=total,
            sheets=sheet_stats, rows=[], total=0,
        )

    @app.get("/nhsa/sn_ms/sheet/<sheet>")
    @app.get("/nhsa/sn_ms/sheet/<sheet>/<parent_code>")
    def sn_ms_browse(sheet, parent_code=""):
        """4 级下钻: 一级 → 二级(L2) → 三级(L3/L4) → 四级(L4/L5) → 五级(L5 明细)."""
        limit = _limit()
        import re as _re
        m = _re.match(r"(\d+)", parent_code or "")
        parent_digits = m.group(1) if m else ""
        with db.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM sn_ms_codes").fetchone()[0]
            ancestors = _sn_ms_ancestors(conn, sheet, parent_digits)
            title_row = conn.execute(
                "SELECT sheet_title FROM sn_ms_codes WHERE sheet_name=? LIMIT 1",
                (sheet,),
            ).fetchone()
            sheet_title = title_row[0] if title_row else sheet

            if not parent_digits:
                current_level = 2
                where = "sheet_name=? AND level=2"
                params = [sheet]
            else:
                L = len(parent_digits)
                if L == 2:
                    child_level = 3
                elif L == 4:
                    child_level = 4 if _has_l4(conn, sheet) else 5
                elif L == 6:
                    child_level = 5
                else:
                    child_level = 5
                current_level = child_level
                where = "sheet_name=? AND level=? AND code LIKE ?"
                params = [sheet, child_level, parent_digits + "%"]

            rows = conn.execute(
                "SELECT code, p_code, name, level, fin_class, unit, "
                "       price_l1, price_l2, price_l3 "
                f"FROM sn_ms_codes WHERE {where} ORDER BY code LIMIT ?",
                (*params, limit),
            ).fetchall()
            keys = ["code", "p_code", "name", "level", "fin_class",
                    "unit", "price_l1", "price_l2", "price_l3"]
            items = [row_to_dict(r, keys) for r in rows]
            count_total = conn.execute(
                f"SELECT COUNT(*) FROM sn_ms_codes WHERE {where}",
                params,
            ).fetchone()[0]
        return render_template(
            "sn_ms.html", mode="browse",
            sheet_name=sheet, sheet_title=sheet_title,
            parent_code=parent_digits, parents=ancestors,
            current_level=current_level,
            items=items, total=count_total,
            query="", total_codes=total,
            sheets=[], rows=[],
        )

    @app.get("/nhsa/sn_ms/code/<code>")
    def sn_ms_detail(code):
        import re as _re
        with db.connect() as conn:
            r = conn.execute(
                "SELECT code, p_code, name, level, sheet_name, sheet_title, "
                "       level_path, fin_class, unit, "
                "       price_l1, price_l2, price_l3, "
                "       content, exclude, remark "
                "FROM sn_ms_codes WHERE code=?",
                (code,),
            ).fetchone()
            keys = ["code", "p_code", "name", "level", "sheet_name", "sheet_title",
                    "level_path", "fin_class", "unit",
                    "price_l1", "price_l2", "price_l3",
                    "content", "exclude", "remark"]
            d = row_to_dict(r, keys) if r else None
            if not d:
                abort(404)
            ancestors = []
            cur = d.get("p_code")
            for _ in range(8):
                if not cur:
                    break
                row = conn.execute(
                    "SELECT name, p_code FROM sn_ms_codes WHERE code=? AND sheet_name=?",
                    (cur, d["sheet_name"]),
                ).fetchone()
                if not row:
                    break
                ancestors.insert(0, {"code": cur, "name": row[0]})
                cur = row[1]
            siblings = []
            if d.get("p_code"):
                rows = conn.execute(
                    "SELECT code, name FROM sn_ms_codes "
                    "WHERE sheet_name=? AND p_code=? AND code<>? "
                    "ORDER BY code LIMIT 50",
                    (d["sheet_name"], d["p_code"], d["code"]),
                ).fetchall()
                siblings = [row_to_dict(x, ["code", "name"]) for x in rows]
        return render_template(
            "sn_ms_detail.html",
            d=d, ancestors=ancestors, siblings=siblings,
            title="陕西版医疗服务",
            index_url=url_for("sn_ms_index"),
        )

    # ==================== Cross-table reverse lookup ====================
    @app.get("/api/code2/<code>")
    def api_code_dispatch(code: str):
        """Auto-dispatch by code prefix to the right NHSA table."""
        c = code.strip()
        hits = []
        with db.connect() as conn:
            if re.match(r"^C\d{17}$", c, re.IGNORECASE):
                rs = conn.execute(
                    "SELECT 'hc' AS src, code, generic_name AS name, cat_l3_name AS desc "
                    "FROM consumable_codes WHERE code=? "
                    "UNION ALL "
                    "SELECT 'hc7', code, generic_name, cat_l3_name "
                    "FROM consumable7_codes WHERE code=? LIMIT 5",
                    (c, c),
                ).fetchall()
                hits = [row_to_dict(x, ["src", "code", "name", "desc"]) for x in rs]
            elif c.upper().startswith("CJ"):
                rs = conn.execute(
                    "SELECT code, catalog_full_name, testing_category, company_name "
                    "FROM ivd_codes WHERE code=? LIMIT 5",
                    (c,),
                ).fetchall()
                hits = [{"src": "ivd", "code": x[0], "name": x[1], "desc": x[2]}
                        for x in rs]
            elif re.match(r"^C[A-Z0-9]+", c, re.IGNORECASE):
                rs = conn.execute(
                    "SELECT code, generic_name, cat_l3_name, manufacturer "
                    "FROM consumable_codes WHERE code=? OR generic_no=? LIMIT 5",
                    (c, c),
                ).fetchall()
                hits = [{"src": "hc", "code": x[0], "name": x[1], "desc": x[2]}
                        for x in rs]
            elif re.match(r"^X[A-Z0-9]+", c, re.IGNORECASE) or re.match(r"^Z[A-Z0-9]+", c, re.IGNORECASE):
                rs = conn.execute(
                    "SELECT code, reg_name, spec, manufacturer FROM yp_codes "
                    "WHERE code=? OR base_code=? OR approval_no=? LIMIT 5",
                    (c, c, c),
                ).fetchall()
                hits = [{"src": "yp", "code": x[0], "name": x[1], "desc": x[2]}
                        for x in rs]
            elif re.match(r"^[A-Z]?\d{2,3}", c):
                rs = conn.execute(
                    "SELECT code, diagnosis_name, chapter_name FROM icd_codes "
                    "WHERE code=? OR diagnosis_code=? LIMIT 5",
                    (c, c),
                ).fetchall()
                hits = [{"src": "icd", "code": x[0], "name": x[1], "desc": x[2]}
                        for x in rs]
            else:
                for tbl, label, fld in [
                    ("consumable_codes", "hc", "generic_name"),
                    ("yp_codes", "yp", "reg_name"),
                    ("ivd_codes", "ivd", "catalog_full_name"),
                    ("icd_codes", "icd", "diagnosis_name"),
                    ("consumable7_codes", "hc7", "generic_name"),
                ]:
                    rs = conn.execute(
                        f"SELECT code, {fld} FROM {tbl} WHERE code=? LIMIT 2",
                        (c,),
                    ).fetchall()
                    for x in rs:
                        hits.append({"src": label, "code": x[0], "name": x[1], "desc": ""})
        if not hits:
            return jsonify({"code": code, "found": False, "hits": []}), 404
        return jsonify({"code": code, "found": True, "hits": hits})
