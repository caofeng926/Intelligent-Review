"""耗材 API + 路由(/consumables, /api/consumable).

Extracted from app.py to reduce app.py size (TD-08).
注册方式: app.py 中 `from . import consumables` + `consumables.register(app)`。
"""

from __future__ import annotations


from flask import jsonify, render_template, request


from . import db
from .query_utils import row_to_dict


def register(app):
    """挂载耗材相关路由到 app (Blueprint-ish)."""
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
        return jsonify({"found": True, "data": row_to_dict(row, keys)})


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
        return jsonify({"groups": [row_to_dict(r, ["key", "name", "code_count"]) for r in groups]})


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
            groups=[row_to_dict(g, ["l1", "l1_name", "code_count"]) for g in groups],
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
            sample = [row_to_dict(r, keys) for r in sample_rows]
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
                    groups=[row_to_dict((l1, l1_name, g[0], g[1], g[2]), ["l1", "l1_name", "l2", "l2_name", "code_count"]) for g in rows],
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
                    groups=[row_to_dict((l1, l1_name, l2, l2_name, g[0], g[1], g[2]), ["l1", "l1_name", "l2", "l2_name", "l3", "l3_name", "code_count"]) for g in rows],
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
            cd = row_to_dict(c, keys) if c else None
        return render_template("consumable_detail.html", c=cd, code=code, rules=rules)



