"""规则浏览与按规则查找路由(/rules/* + /api/rule-categories).

Extracted from app.py (TD-08 第二期).
注册方式: app.py 中 `from . import rules` + `rules.register(app)`.
"""
from __future__ import annotations

import math
import sqlite3

from flask import abort, jsonify, redirect, render_template, request, url_for

from . import db
from .helpers import SOURCE_LABEL
from .query_utils import _safe_int
from .query_utils import fts_query as jieba_query
from .search_backend import detect_mode

# ---- 规则主题分类 ------------------------------------------------------
# 按 rule_subject 前缀归类(覆盖现有 47 条规则)。
CATEGORY_PREFIXES = (
    ("药品", ("药品",)),
    ("医疗服务项目", ("医疗服务项目",)),
    ("中药饮片", ("中药饮片",)),
    ("医用耗材", ("医用耗材", "耗材")),
    ("诊断", ("诊断", "无指征", "妊娠期", "老年人", "超说明书", "重复开药")),
    ("手术", ("手术", "围手术期")),
)
CATEGORY_ORDER = [c[0] for c in CATEGORY_PREFIXES] + ["其他"]
DEFAULT_CATEGORY = "其他"


def _categorize_subject(subject: str) -> str:
    """根据 rule_subject 前缀返回类别名。"""
    if not subject:
        return DEFAULT_CATEGORY
    for name, prefixes in CATEGORY_PREFIXES:
        for p in prefixes:
            if subject.startswith(p):
                return name
    return DEFAULT_CATEGORY


# ---- /rules 路由 -------------------------------------------------------
def register(app):
    """挂载规则路由到 app。"""

    @app.get("/rules")
    def rules_index():
        """默认进入"按知识点查询"。直接重定向到 /rules/find。"""
        return redirect(url_for("rules_find"))

    @app.get("/rules/category")
    def rules_category():
        """按规则分类查询：按主题(药品/医疗服务项目/中药饮片/医用耗材/诊断/手术/其他)聚合展示。"""
        with db.connect() as conn:
            rows = conn.execute("""
                SELECT r.id, r.rule_subject, r.source, b.batch_label,
                       COUNT(kp.id) AS kp_count
                FROM rules r
                JOIN batches b ON b.id = r.batch_id
                LEFT JOIN knowledge_points kp ON kp.rule_id = r.id
                GROUP BY r.id
                ORDER BY r.rule_subject
            """).fetchall()

        category_map: dict = {}
        for r in rows:
            cat = _categorize_subject(r[1])
            bucket = category_map.setdefault(cat, {
                "name": cat, "rules": [], "total_kp": 0, "rule_count": 0,
            })
            bucket["rules"].append({
                "id": r[0], "subject": r[1], "source": r[2],
                "batch_label": r[3], "kp_count": r[4],
            })
            bucket["total_kp"] += r[4]
            bucket["rule_count"] += 1

        categories = [category_map[c] for c in CATEGORY_ORDER if c in category_map]
        return render_template("rules_category.html",
                               categories=categories, source_label=SOURCE_LABEL)

    @app.get("/rules/list")
    def rules_list():
        """列出所有规则，按名称去重合并。支持 ?q= 按名称/分类关键字过滤。"""
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
                    SUM((SELECT COUNT(*) FROM knowledge_points kp
                         WHERE kp.rule_id = rules.id)) AS kp_cnt
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
                by_rule: dict = {}
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
                # NHSA 优先,然后按规则名排序
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

    @app.get("/rules/<int:rid>")
    def rule_detail(rid: int):
        page = _safe_int(request.args.get("page", 1), default=1, min_=1)
        limit = 20
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
            total = conn.execute(
                "SELECT COUNT(*) FROM knowledge_points WHERE rule_id = ?", (rid,)
            ).fetchone()[0]
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

    @app.get("/api/rule-categories")
    def api_rule_categories():
        """返回按规则类型分类的数据,用于小程序规则浏览页。"""
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

        category_map: dict = {}
        for r in rules:
            category = _categorize_subject(r[1])
            bucket = category_map.setdefault(category, {
                "name": category, "rules": [], "total_kp": 0, "rule_count": 0,
            })
            bucket["rules"].append({
                "id": r[0], "subject": r[1], "source": r[2],
                "batch_label": r[3], "kp_count": r[4],
            })
            bucket["total_kp"] += r[4]
            bucket["rule_count"] += 1

        categories = [category_map[c] for c in CATEGORY_ORDER if c in category_map]
        return jsonify({"categories": categories})


def _search_kps_grouped_by_rule(conn, q: str, mode: str, source, limit: int = 300):
    """为 /rules/find 搜索 KPs,附带 rule_id 等列,便于分组。"""
    if not q:
        return [], 0

    if mode == "code":
        kp_ids = _search_by_code(conn, q, source, limit)
        if not kp_ids:
            return [], 0
        # total = LIKE-未精确;用实际命中数即可(分页按 limit 截断)
        return _enrich_kps_with_rule(conn, kp_ids, len(kp_ids)), len(kp_ids)

    if mode == "initials":
        kp_ids = _search_by_initials(conn, q, source, limit)
        if not kp_ids:
            return [], 0
        return _enrich_kps_with_rule(conn, kp_ids, len(kp_ids)), len(kp_ids)

    # name mode: FTS5
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
    total = conn.execute(
        "SELECT COUNT(*) FROM kp_fts WHERE kp_fts MATCH ?", [fts_q]
    ).fetchone()[0]
    return rows, total


def _search_by_code(conn, code: str, source, limit: int) -> list[int]:
    """医保编码精确匹配,返回 kp.id 列表(去重、保序)。"""
    code = code.upper()
    sql = """
        SELECT DISTINCT kp.id
        FROM knowledge_point_codes kpc
        JOIN knowledge_points kp ON kp.id = kpc.kp_id
        JOIN rules r ON r.id = kp.rule_id
        WHERE kpc.code = ?
    """
    params: list = [code]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY kp.id LIMIT ?"
    params.append(limit)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def _search_by_initials(conn, q: str, source, limit: int) -> list[int]:
    """拼音首字母前缀匹配,返回 kp.id 列表。"""
    needle = q.lower() + "%"
    sql = """
        SELECT kp.id
        FROM knowledge_points kp
        JOIN rules r ON r.id = kp.rule_id
        WHERE kp.pinyin_initials LIKE ?
    """
    params: list = [needle]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY kp.subject_name LIMIT ?"
    params.append(limit)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def _enrich_kps_with_rule(conn, kp_ids, total):
    """对一串 KP id,附带 rule 信息返回。结果保持 kp_ids 顺序。"""
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
