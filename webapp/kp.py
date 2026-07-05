"""KP (knowledge point) routes: /kp/<id> 页面 + /api/kp/<id> JSON.

Extracted from app.py (TD-08).
"""

from __future__ import annotations

import sqlite3

from flask import abort, jsonify, render_template, request

from . import db
from .helpers import PAGE_SIZE, SOURCE_LABEL, parse_kp_partner
from .search_backend import _row_to_kp_dict, detect_mode, do_search


def register(app):
    """挂载 KP 路由到 app."""
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
