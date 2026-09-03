# -*- coding: utf-8 -*-
"""2025 版陕西省医保药品目录浏览页面.

数据源: yp_catalog_sx_2025 (4,783 条) + yp25sx_category_tree (顶层 + 子分类)

路由:
  GET /yp2025_sx                                  - 5 大类入口
  GET /yp2025_sx?cat=<category>                   - 单大类: 顶层分类列表
  GET /yp2025_sx?cat=<cat>&top=<code>             - 顶层: 子分类列表
  GET /yp2025_sx?cat=<cat>&top=<code>&sub=<code>  - 子分类: 药品列表
  GET /yp2025_sx?q=<keyword>                      - 搜索 (FTS5)
  GET /yp2025_sx/<list_no>                        - 单药品详情
  GET /api/yp2025_sx/search                       - FTS5 JSON
  GET /api/yp2025_sx/stats                        - 统计 JSON
  GET /api/yp2025_sx/tree                         - 分类树 JSON

查询结果表格列: 编码 / 甲乙类 / 名称 / 剂型 / 备注
"""
from __future__ import annotations

import re
from typing import Optional, List

from flask import render_template, request, jsonify, abort

import sqlite3
from . import db


PAGE_SIZE = 50
ALL_CATEGORIES = ["西药", "谈判西药", "中成药", "谈判中成药", "中药饮片"]
HERBAL_CATEGORY = "中药饮片"


def _page_size(default: int = PAGE_SIZE, max_: int = 200) -> int:
    try:
        n = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_))


def _safe_fts_query(q: str) -> str:
    """FTS5 prefix-match: each whitespace-separated token suffixed with *."""
    return " ".join(t + "*" for t in re.split(r"\s+", q.strip()) if t)



# ============= 价格保密脱敏 (defense in depth) =============
# 即便 DB 里残留价格保密内容,API 层也屏蔽掉. 与 parse_yp_2025.sanitize_price_confidential
# 保持一致逻辑.
_PRICE_CONF_KEYWORDS = (
    "价格保密", "阶梯价格", "阶梯单价", "计算举例",
    "支付阶梯价格方案", "企业申请价格保密",
)
_REDACTION_MARK = "[内容因企业申请价格保密已屏蔽]"


def _is_price_conf_row(row: dict) -> bool:
    r = row.get("remark") or ""
    return any(kw in r for kw in _PRICE_CONF_KEYWORDS)


def _scrub_row(row: dict) -> dict:
    """对价格保密药品行做脱敏: payment_standard='*', remark=屏蔽标记. payment_validity 保留."""
    if _is_price_conf_row(row):
        row["payment_standard"] = "*"
        row["remark"] = _REDACTION_MARK
    return row


def _scrub_rows(rows) -> list:
    return [_scrub_row(dict(r)) for r in rows]


def register(app):
    @app.get("/yp2025_sx/")
    @app.get("/yp2025_sx")
    def yp2025_sx_browse():
        category = request.args.get("cat") or None
        top = (request.args.get("top") or "").strip() or None
        sub = (request.args.get("sub") or "").strip() or None
        q = (request.args.get("q") or "").strip()
        page = max(1, int(request.args.get("page", 1) or 1))
        limit = _page_size()
        offset = (page - 1) * limit

        with db.connect() as conn:
            conn.row_factory = sqlite3.Row

            # 5 大类总计数
            stats = {}
            for cat in ALL_CATEGORIES:
                n = conn.execute(
                    "SELECT COUNT(*) FROM yp_catalog_sx_2025 WHERE category = ?",
                    (cat,),
                ).fetchone()[0]
                stats[cat] = n
            stats["总计"] = sum(stats.values())

            # 视图选择: tree 模式 (cat+top+sub 路径), 全局搜索, 默认入口
            if category and category in ALL_CATEGORIES:
                if sub:
                    return _render_sub_drugs(conn, category, top, sub, q, page, limit, offset, stats)
                if top:
                    return _render_top_subs(conn, category, top, q, stats)
                return _render_category_tops(conn, category, q, stats)

            # 全局搜索: 有 q 无 cat -> 跨大类查询结果页
            if q and not category:
                return _render_search(conn, q, page, limit, offset, stats)

            # 默认入口
            return _render_entry(conn, q, stats)

    @app.get("/yp2025_sx/<list_no>")
    def yp2025_sx_detail(list_no):
        from urllib.parse import unquote
        list_no_decoded = unquote(list_no)
        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM yp_catalog_sx_2025
                   WHERE list_no = ? ORDER BY category, dosage_form""",
                (list_no_decoded,),
            ).fetchall()
            if not rows:
                abort(404)
            item = _scrub_row(dict(rows[0]))
            variants = [_scrub_row(dict(r)) for r in rows[1:]] if len(rows) > 1 else []
            related = []
            if item.get("category_code"):
                related = [_scrub_row(dict(r)) for r in conn.execute(
                        """SELECT list_no, name, dosage_form, list_class
                           FROM yp_catalog_sx_2025
                           WHERE category = ? AND category_code = ?
                           ORDER BY list_no LIMIT 20""",
                        (item["category"], item["category_code"]),
                    ).fetchall()
                ]
        return render_template(
            "yp2025_sx_detail.html",
            item=item,
            variants=variants,
            related=related,
        )

    @app.get("/api/yp2025_sx/search")
    def api_yp2025_sx_search():
        q = (request.args.get("q") or "").strip()
        limit = _page_size(default=20, max_=100)
        if not q:
            return jsonify({"items": [], "total": 0})
        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            fts_q = _safe_fts_query(q)
            try:
                rows = conn.execute(
                    """SELECT d.id, d.list_no, d.name, d.category, d.list_class,
                              d.category_code, d.category_name, d.dosage_form,
                              d.remark, d.payment_standard
                       FROM yp_catalog_sx_2025_fts f
                       JOIN yp_catalog_sx_2025 d ON d.id = f.rowid
                       WHERE yp_catalog_sx_2025_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (fts_q, limit),
                ).fetchall()
            except Exception:
                like = f"%{q}%"
                rows = conn.execute(
                    """SELECT id, list_no, name, category, list_class,
                              category_code, category_name, dosage_form,
                              remark, payment_standard
                       FROM yp_catalog_sx_2025
                       WHERE name LIKE ? OR remark LIKE ?
                       ORDER BY name LIMIT ?""",
                    (like, like, limit),
                ).fetchall()
        return jsonify({
            "items": [_scrub_row(dict(r)) for r in rows],
            "total": len(rows),
            "q": q,
        })

    @app.get("/api/yp2025_sx/stats")
    def api_yp2025_sx_stats():
        with db.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM yp_catalog_sx_2025").fetchone()[0]
            by_cat = conn.execute(
                "SELECT category, COUNT(*) FROM yp_catalog_sx_2025 GROUP BY category ORDER BY category"
            ).fetchall()
            by_class = conn.execute(
                """SELECT category, list_class, COUNT(*)
                   FROM yp_catalog_sx_2025 GROUP BY category, list_class
                   ORDER BY category, list_class"""
            ).fetchall()
            tree = conn.execute(
                """SELECT category, code, name, level, parent_code, drug_count
                   FROM yp25sx_category_tree ORDER BY category, level, code"""
            ).fetchall()
        return jsonify({
            "total": total,
            "by_category": {c: n for c, n in by_cat},
            "by_class": [{"category": c, "list_class": l, "count": n} for c, l, n in by_class],
            "tree": [{"category": r[0], "code": r[1], "name": r[2],
                      "level": r[3], "parent_code": r[4], "drug_count": r[5]}
                     for r in tree],
        })

    @app.get("/api/yp2025_sx/tree")
    def api_yp2025_sx_tree():
        cat = (request.args.get("cat") or "").strip()
        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            if cat:
                rows = conn.execute(
                    """SELECT code, name, level, parent_code, drug_count
                       FROM yp25sx_category_tree WHERE category = ?
                       ORDER BY level, code""", (cat,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT category, code, name, level, parent_code, drug_count
                       FROM yp25sx_category_tree ORDER BY category, level, code"""
                ).fetchall()
        return jsonify({"nodes": [_scrub_row(dict(r)) for r in rows]})


# ---- view helpers ----

def _render_entry(conn, q, stats):
    """默认入口: 5 大类卡片."""
    return render_template(
        "yp2025_sx_entry.html",
        stats=stats,
        categories=ALL_CATEGORIES,
        cur_q=q,
    )


def _render_category_tops(conn, category, q, stats):
    """单大类: 顶层分类列表."""
    tops = conn.execute(
        """SELECT code, name, drug_count
           FROM yp25sx_category_tree
           WHERE category = ? AND level = 1
           ORDER BY code""", (category,)
    ).fetchall()
    return render_template(
        "yp2025_sx_top.html",
        stats=stats,
        categories=ALL_CATEGORIES,
        cur_category=category,
        tops=[_scrub_row(dict(r)) for r in tops],
        cur_q=q,
    )


def _render_top_subs(conn, category, top, q, stats):
    """顶层: 子分类列表."""
    top_node = conn.execute(
        """SELECT code, name, drug_count FROM yp25sx_category_tree
           WHERE category = ? AND level = 1 AND code = ?""",
        (category, top),
    ).fetchone()
    if not top_node:
        abort(404)
    subs = conn.execute(
        """SELECT code, name, drug_count
           FROM yp25sx_category_tree
           WHERE category = ? AND level = 2 AND parent_code = ?
           ORDER BY code""", (category, top)
    ).fetchall()
    return render_template(
        "yp2025_sx_sub.html",
        stats=stats,
        categories=ALL_CATEGORIES,
        cur_category=category,
        cur_top=dict(top_node),
        subs=[_scrub_row(dict(r)) for r in subs],
        cur_q=q,
    )


def _render_sub_drugs(conn, category, top, sub, q, page, limit, offset, stats):
    """子分类: 药品列表 (表格: 编码 / 甲乙类 / 名称 / 剂型 / 备注)."""
    sub_node = conn.execute(
        """SELECT code, name FROM yp25sx_category_tree
           WHERE category = ? AND level = 2 AND parent_code = ? AND code = ?""",
        (category, top, sub),
    ).fetchone()
    if not sub_node:
        abort(404)
    # 构建 WHERE
    where_parts = ["category = ?", "category_code = ?"]
    params: list = [category, sub]
    if q:
        where_parts.append(
            "(name LIKE ? OR dosage_form LIKE ? OR remark LIKE ? OR category_name LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])
    where = " AND ".join(where_parts)

    total = conn.execute(
        f"SELECT COUNT(*) FROM yp_catalog_sx_2025 WHERE {where}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT category_code, list_class, name, dosage_form, remark,
                   list_no, payment_standard, payment_validity, category
            FROM yp_catalog_sx_2025
            WHERE {where}
            ORDER BY list_no, name, dosage_form
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    total_pages = max(1, (total + limit - 1) // limit)
    return render_template(
        "yp2025_sx_drugs.html",
        stats=stats,
        categories=ALL_CATEGORIES,
        cur_category=category,
        cur_top_code=top,
        cur_sub=dict(sub_node),
        drugs=[_scrub_row(dict(r)) for r in rows],
        total=total,
        page=page,
        total_pages=total_pages,
        limit=limit,
        cur_q=q,
    )

def _render_search(conn, q, page, limit, offset, stats):
    """全局搜索结果页: 跨 5 大类, 表格 5 列."""
    fts_q = _safe_fts_query(q)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM yp_catalog_sx_2025_fts WHERE yp_catalog_sx_2025_fts MATCH ?",
            (fts_q,),
        ).fetchone()[0]
    except Exception:
        total = 0
    if total:
        rows = conn.execute(
            """SELECT d.category_code, d.list_class, d.name, d.dosage_form, d.remark,
                      d.list_no, d.payment_standard, d.payment_validity, d.category
               FROM yp_catalog_sx_2025_fts f
               JOIN yp_catalog_sx_2025 d ON d.id = f.rowid
               WHERE yp_catalog_sx_2025_fts MATCH ?
               ORDER BY rank LIMIT ? OFFSET ?""",
            (fts_q, limit, offset),
        ).fetchall()
        drugs = [_scrub_row(dict(r)) for r in rows]
    else:
        # fallback: LIKE
        like = f"%{q}%"
        total = conn.execute(
            """SELECT COUNT(*) FROM yp_catalog_sx_2025
               WHERE name LIKE ? OR dosage_form LIKE ? OR remark LIKE ? OR category_name LIKE ?""",
            (like, like, like, like),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT category_code, list_class, name, dosage_form, remark,
                      list_no, payment_standard, payment_validity, category
               FROM yp_catalog_sx_2025
               WHERE name LIKE ? OR dosage_form LIKE ? OR remark LIKE ? OR category_name LIKE ?
               ORDER BY list_no, name LIMIT ? OFFSET ?""",
            (like, like, like, like, limit, offset),
        ).fetchall()
        drugs = [_scrub_row(dict(r)) for r in rows]

    total_pages = max(1, (total + limit - 1) // limit)
    return render_template(
        "yp2025_sx_drugs.html",
        stats=stats,
        categories=ALL_CATEGORIES,
        cur_category=None,
        cur_top_code=None,
        cur_sub={"code": "全局搜索", "name": f"搜索: {q}"},
        drugs=drugs,
        total=total,
        page=page,
        total_pages=total_pages,
        limit=limit,
        cur_q=q,
        search_mode=True,
    )
