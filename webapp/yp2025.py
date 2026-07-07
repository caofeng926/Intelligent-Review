"""2025 版国家医保药品目录浏览页面.

数据源: yp_catalog_2025 表 (4783 条, 来自 原始数据/基本医保药品目录.pdf)

路由:
  /yp2025                - 浏览 (按 category 过滤, 分页)
  /yp2025/cat/<category> - 按分类过滤
  /yp2025/<list_no>      - 单药品详情
  /api/yp2025/search     - FTS5 搜索 API
  /api/yp2025/stats      - 统计 API
"""
from __future__ import annotations

import re
from typing import Optional, List

from flask import render_template, request, jsonify, abort

import sqlite3
from . import db


PAGE_SIZE = 50
ALL_CATEGORIES = ["西药", "中成药", "谈判西药", "谈判中成药", "中药饮片"]


def _page_size(default: int = PAGE_SIZE, max_: int = 200) -> int:
    try:
        n = int(request.args.get("limit", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_))


def _filter_clause(category: Optional[str]):
    if category and category in ALL_CATEGORIES:
        return ("WHERE category = ?", [category])
    return ("", [])


def register(app):
    @app.get("/yp2025/")
    @app.get("/yp2025")
    def yp2025_browse():
        category = request.args.get("cat") or None
        q = (request.args.get("q") or "").strip()
        page = max(1, int(request.args.get("page", 1) or 1))
        limit = _page_size()
        offset = (page - 1) * limit

        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            where_parts = []
            params: list = []
            if category and category in ALL_CATEGORIES:
                where_parts.append("category = ?")
                params.append(category)
            if q:
                # FTS5 前缀匹配 (unicode61 按字分词)
                where_parts.append(
                    "(name LIKE ? OR category_name LIKE ? OR dosage_form LIKE ? OR remark LIKE ?)"
                )
                like = f"%{q}%"
                params.extend([like, like, like, like])
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            total = conn.execute(
                f"SELECT COUNT(*) FROM yp_catalog_2025 {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT id, list_no, name, category, list_class,
                           category_code, category_name, dosage_form,
                           payment_standard, payment_validity, remark,
                           star_ref, page_no
                    FROM yp_catalog_2025 {where}
                    ORDER BY category, category_code, list_no, name, dosage_form
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()

            # 统计每个分类的条目数
            stats = {}
            for cat in ALL_CATEGORIES:
                n = conn.execute(
                    "SELECT COUNT(*) FROM yp_catalog_2025 WHERE category = ?",
                    (cat,),
                ).fetchone()[0]
                stats[cat] = n
            stats["总计"] = sum(stats.values())

            items = [dict(r) for r in rows]

        total_pages = max(1, (total + limit - 1) // limit)
        return render_template(
            "yp2025.html",
            items=items,
            total=total,
            stats=stats,
            categories=ALL_CATEGORIES,
            cur_category=category,
            cur_q=q,
            page=page,
            total_pages=total_pages,
            limit=limit,
        )

    @app.get("/yp2025/<list_no>")
    def yp2025_detail(list_no):
        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            # list_no 可能含 "★(N)", URL encode 后是 %E2%98%85(8)
            from urllib.parse import unquote
            list_no_decoded = unquote(list_no)
            rows = conn.execute(
                """SELECT * FROM yp_catalog_2025
                   WHERE list_no = ? ORDER BY category, dosage_form""",
                (list_no_decoded,),
            ).fetchall()
            if not rows:
                abort(404)
            item = dict(rows[0])
            # 同编号的其他剂型/规格
            variants = [dict(r) for r in rows[1:]] if len(rows) > 1 else []
            # 同一分类下的所有相关 (按 category_code 上下文)
            related = []
            if item.get("category_code"):
                related = [
                    dict(r) for r in conn.execute(
                        """SELECT list_no, name, dosage_form, list_class
                           FROM yp_catalog_2025
                           WHERE category = ? AND category_code = ?
                           ORDER BY list_no LIMIT 20""",
                        (item["category"], item["category_code"]),
                    ).fetchall()
                ]
        return render_template(
            "yp2025_detail.html",
            item=item,
            variants=variants,
            related=related,
        )

    @app.get("/api/yp2025/search")
    def api_yp2025_search():
        q = (request.args.get("q") or "").strip()
        limit = _page_size(default=20, max_=100)
        if not q:
            return jsonify({"items": [], "total": 0})
        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            # FTS5 前缀匹配 (中文用 unicode61 按字分词, 必须用 *)
            fts_q = " ".join(t + "*" for t in q.split() if t)
            try:
                rows = conn.execute(
                    """SELECT d.id, d.list_no, d.name, d.category, d.list_class,
                              d.dosage_form, d.payment_standard, d.remark
                       FROM yp_catalog_2025_fts f
                       JOIN yp_catalog_2025 d ON d.id = f.rowid
                       WHERE yp_catalog_2025_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (fts_q, limit),
                ).fetchall()
            except Exception:
                # FTS 失败 fallback LIKE
                like = f"%{q}%"
                rows = conn.execute(
                    """SELECT id, list_no, name, category, list_class,
                              dosage_form, payment_standard, remark
                       FROM yp_catalog_2025
                       WHERE name LIKE ? OR remark LIKE ?
                       ORDER BY name LIMIT ?""",
                    (like, like, limit),
                ).fetchall()
        return jsonify({
            "items": [dict(r) for r in rows],
            "total": len(rows),
            "q": q,
        })

    @app.get("/api/yp2025/stats")
    def api_yp2025_stats():
        with db.connect() as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) FROM yp_catalog_2025").fetchone()[0]
            by_cat = conn.execute(
                "SELECT category, COUNT(*) FROM yp_catalog_2025 GROUP BY category ORDER BY category"
            ).fetchall()
            by_class = conn.execute(
                """SELECT category, list_class, COUNT(*)
                   FROM yp_catalog_2025 GROUP BY category, list_class
                   ORDER BY category, list_class"""
            ).fetchall()
        return jsonify({
            "total": total,
            "by_category": {c: n for c, n in by_cat},
            "by_class": [{"category": c, "list_class": l, "count": n} for c, l, n in by_class],
        })