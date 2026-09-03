# trigger-deploy: re-trigger deploy Action on 8c781ba so debug step is included
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

import hashlib
import html
import json
import math
import os
import sys
import time

from flask import Flask, abort, jsonify, render_template, request

from . import admin, db, nhsa_api, nhsa_browse, yp2025, yp2025_sx
from .helpers import PAGE_SIZE, SOURCE_LABEL
from .query_utils import fts_search, row_to_dict
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
yp2025.register(app)
yp2025_sx.register(app)
app.register_blueprint(admin.admin_bp)
app.config["JSON_AS_ASCII"] = False
# 静态资源缓存: 本地开发 0 = 立即刷新; 生产用 60s + 模板里 `?v=YYYYMMDD` 强制 bust,
# 浏览器遇到带查询串的 URL 会跳过缓存命中。部署后把模板里的 ?v= 改成新日期即可。
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0 if app.debug else 60  # dev=0 / prod=1min


# 生产模式静态资源强制 no-cache (must-revalidate),保证部署后页面立即看到新版本
# 带查询串 (?v=...) 的 URL 浏览器通常跳过缓存命中,作为额外保险
if not app.debug:
    @app.after_request
    def _static_no_cache(resp):
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


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


def _safe_count(conn, table):
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return 0


# 小程序首页聚合统计接口 (2026-07-14 miniapp)
@app.get("/api/stats")
def api_stats():
    with db.connect() as conn:
        return jsonify({
            "knowledge_points": conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0],
            "codes": conn.execute("SELECT COUNT(*) FROM knowledge_point_codes").fetchone()[0],
            "rules": conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0],
            "nhsa_rules": conn.execute("SELECT COUNT(*) FROM rules WHERE source='nhsa_batch'").fetchone()[0],
            "consumables": _safe_count(conn, "consumable_codes"),
            "yp_2025": _safe_count(conn, "yp_catalog_2025"),
            "tcm": _safe_count(conn, "tcm_codes"),
            "icd": _safe_count(conn, "icd_codes"),
            "ivd": _safe_count(conn, "ivd_codes"),
            "ms": _safe_count(conn, "medical_service_codes"),
        })


# 首页"最新政策"列表 (miniapp)
@app.get("/api/recent")
def api_recent():
    """返回按发布时间倒序的最新 N 条知识点，供小程序首页展示。"""
    limit = min(int(request.args.get("limit", 12)), 30)
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT kp.id, kp.subject_name, r.rule_subject, b.batch_label, b.pub_date,
                   r.source
            FROM knowledge_points kp
            JOIN rules r ON r.id = kp.rule_id
            JOIN batches b ON b.id = r.batch_id
            WHERE b.pub_date IS NOT NULL AND kp.subject_name IS NOT NULL AND kp.subject_name != ''
            ORDER BY b.pub_date DESC, kp.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        items = [
            {
                "kp_id": r[0],
                "id": r[0],
                "subject_name": r[1],
                "rule_subject": r[2] or "",
                "batch_label": r[3] or "",
                "pub_date": r[4] or "",
                "source": r[5] or "",
            }
            for r in rows
        ]
    return jsonify({"items": items, "total": len(items)})


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
            "yp_catalog_2025": _safe_count(conn, "yp_catalog_2025"),
            "yp_catalog_sx_2025": _safe_count(conn, "yp_catalog_sx_2025"),
            "sn_ms": _safe_count(conn, "sn_ms_codes"),
            "sn_ms_material": _safe_count(conn, "sn_ms_material_codes"),
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
    """Thin wrapper around query_utils.fts_search (TD-08 dedup, NEW-06).

    Centralises FTS5 + LIKE-fallback logic in query_utils.fts_search so the
    search query builder and LIKE fallback live in one place.
    """
    return fts_search(conn, q, fts_table, table, fields, name_field, code_field, limit=limit)


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


# ----------- 微信小程序静默登录 (2026-07-14 miniapp) -----------
# 用 jscode2session 拿 openid 换成服务端 token。
# 生产要求:
#   - WECHAT_APPID / WECHAT_SECRET 必须配齐; 否则 anon 降级直接 503 (除 MA_ALLOW_ANON_LOGIN=1)
#   - MA_TOKEN_SALT 必须显式提供, 默认 salt 仅 dev 模式可接受
#   - token 持久化到 mini_app_tokens 表, /api/fav 等接口通过 Bearer 鉴权
WECHAT_APPID = os.environ.get("WECHAT_APPID", "")
WECHAT_SECRET = os.environ.get("WECHAT_SECRET", "")
MA_ENV = os.environ.get("MA_ENV", "dev").lower()  # dev | staging | prod
MA_ALLOW_ANON_LOGIN = os.environ.get("MA_ALLOW_ANON_LOGIN", "") in ("1", "true", "yes")


def _hash_token(openid: str) -> str:
    """把 openid 哈希成 token. 生产 salt 必须显式注入, 默认 salt 仅 dev 兜底."""
    salt = os.environ.get("MA_TOKEN_SALT", "")
    if not salt:
        if MA_ENV == "prod":
            raise RuntimeError("MA_TOKEN_SALT must be set in production")
        salt = "yibao-zs-DEV-ONLY-DO-NOT-USE-IN-PROD"
    return hashlib.sha256(f"{salt}|{openid}".encode()).hexdigest()[:48]


def _persist_token(token: str, openid: str, ttl_seconds: int = 7200) -> None:
    """把 token↔openid 写入 mini_app_tokens, 供后续鉴权查询."""
    expires_at = time.time() + ttl_seconds
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO mini_app_tokens (token, openid, expires_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(token) DO UPDATE SET
                       openid = excluded.openid,
                       expires_at = excluded.expires_at""",
                (token, openid, expires_at),
            )
            conn.commit()
    except Exception:
        pass


def _openid_from_request() -> str:
    """从 Authorization: Bearer <token> 头反查 openid, 无/过期/未找到返回 ''."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    token = auth[7:].strip()
    if not token:
        return ""
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT openid, expires_at FROM mini_app_tokens WHERE token = ?",
                (token,),
            ).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    openid, expires_at = row[0], row[1]
    if expires_at and expires_at < time.time():
        return ""
    return openid or ""


@app.post("/api/auth/wechat-login")
def api_auth_wechat_login():
    """小程序静默登录：wx.login → code → 换 openid/unionid → 自签 token。"""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"errcode": 400, "message": "missing code"}), 400

    openid = None
    unionid = None

    if WECHAT_APPID and WECHAT_SECRET:
        try:
            import urllib.parse
            import urllib.request
            query = urllib.parse.urlencode({
                "appid": WECHAT_APPID,
                "secret": WECHAT_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            })
            with urllib.request.urlopen(
                f"https://api.weixin.qq.com/sns/jscode2session?{query}",
                timeout=5
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("openid"):
                openid = payload["openid"]
                unionid = payload.get("unionid")
            else:
                return jsonify({
                    "errcode": payload.get("errcode", 500),
                    "message": payload.get("errmsg", "wx jscode2session failed"),
                }), 400
        except Exception as ex:
            return jsonify({"errcode": -1, "message": f"wx api error: {ex}"}), 502
    else:
        # 开发降级：用 code 做稳定 hash 得到 anonymous openid
        # 生产环境: 没有 WECHAT_APPID/SECRET 必须 503, 禁止 anon 静默登录
        if MA_ENV == "prod" and not MA_ALLOW_ANON_LOGIN:
            return jsonify({
                "errcode": 503,
                "message": "WECHAT_APPID / WECHAT_SECRET not configured in production",
            }), 503
        anon = hashlib.md5(code.encode()).hexdigest()[:16]
        openid = f"anon_{anon}"
        unionid = None

    token = _hash_token(openid)
    _persist_token(token, openid, ttl_seconds=7200)
    # 记录到 users 表（首次访问 = 新增）
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO mini_app_users (openid, unionid, last_seen_at, login_count)
                   VALUES (?, ?, datetime('now'), 1)
                   ON CONFLICT(openid) DO UPDATE SET
                       last_seen_at = datetime('now'),
                       login_count = login_count + 1""",
                (openid, unionid),
            )
            conn.commit()
    except Exception:
        # mini_app_users 表可能不存在，忽略（不影响登录主流程）
        pass

    return jsonify({
        "errcode": 0,
        "openid": openid,
        "unionid": unionid,
        "access_token": token,
        "expires_in": 7200,  # 2 小时，让前端定时 refresh
    })


@app.post("/api/track/event")
def api_track_event():
    """轻量埋点上报，前端批量累积后 submit。"""
    data = request.get_json(silent=True) or {}
    event = (data.get("event") or "").strip()
    if not event or len(event) > 64:
        return jsonify({"errcode": 400, "message": "invalid event name"}), 400
    try:
        params = data.get("params")
        params_json = json.dumps(params, ensure_ascii=False) if params else None
        ts = float(data.get("t") or 0) or time.time()
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO mini_app_events (event, params_json, openid, ua, t)
                   VALUES (?, ?, ?, ?, ?)""",
                (event, params_json,
                 data.get("openid") or "",
                 request.headers.get("User-Agent", ""),
                 ts),
            )
            conn.commit()
    except Exception:
        # 降级：埋点失败不影响业务
        pass
    return jsonify({"errcode": 0})


# ----------- V1.1 留存功能 (2026-07-14) -----------

@app.post("/api/fav")
def api_fav_add():
    """添加收藏。"""
    data = request.get_json(silent=True) or {}
    openid = _openid_from_request() or (data.get("openid") or "").strip()  # 兼容旧前端
    kp_id = data.get("kp_id")
    if not openid or not kp_id:
        return jsonify({"errcode": 401, "message": "missing or invalid auth"}), 401
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO mini_app_favs (openid, kp_id, kp_name, batch_label)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(openid, kp_id) DO UPDATE SET
                       kp_name = excluded.kp_name,
                       batch_label = excluded.batch_label""",
                (openid, int(kp_id), data.get("kp_name") or "", data.get("batch_label") or ""),
            )
            conn.commit()
        return jsonify({"errcode": 0})
    except Exception as ex:
        return jsonify({"errcode": 500, "message": str(ex)}), 500


@app.delete("/api/fav")
def api_fav_remove():
    """取消收藏。"""
    data = request.get_json(silent=True) or {}
    openid = _openid_from_request() or (data.get("openid") or "").strip()  # 兼容旧前端
    kp_id = data.get("kp_id")
    if not openid or not kp_id:
        return jsonify({"errcode": 401, "message": "missing or invalid auth"}), 401
    try:
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM mini_app_favs WHERE openid = ? AND kp_id = ?",
                (openid, int(kp_id)),
            )
            conn.commit()
        return jsonify({"errcode": 0})
    except Exception as ex:
        return jsonify({"errcode": 500, "message": str(ex)}), 500


@app.get("/api/fav")
def api_fav_list():
    """列出用户的收藏，按收藏时间倒序。"""
    openid = _openid_from_request() or (request.args.get("openid") or "").strip()  # 兼容旧前端
    if not openid:
        return jsonify({"errcode": 401, "message": "missing or invalid auth"}), 401
    try:
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT kp_id, kp_name, batch_label, created_at
                   FROM mini_app_favs
                   WHERE openid = ?
                   ORDER BY created_at DESC
                   LIMIT 200""",
                (openid,),
            ).fetchall()
            items = [
                {
                    "kp_id": r[0],
                    "id": r[0],
                    "name": r[1] or "",
                    "batch_label": r[2] or "",
                    "created_at": r[3] or "",
                }
                for r in rows
            ]
        return jsonify({"items": items, "total": len(items)})
    except Exception as ex:
        return jsonify({"errcode": 500, "message": str(ex)}), 500


@app.get("/api/fav/check")
def api_fav_check():
    """批量检查 KP 是否已收藏（用于列表红心显示）。"""
    openid = _openid_from_request() or (request.args.get("openid") or "").strip()  # 兼容旧前端
    ids_param = (request.args.get("ids") or "").strip()
    if not openid or not ids_param:
        return jsonify({"favs": []})
    try:
        ids = [int(x) for x in ids_param.split(",") if x.isdigit()][:50]
        if not ids:
            return jsonify({"favs": []})
        ph = ",".join("?" * len(ids))
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT kp_id FROM mini_app_favs WHERE openid = ? AND kp_id IN ({ph})",
                [openid] + ids,
            ).fetchall()
        return jsonify({"favs": [r[0] for r in rows]})
    except Exception:
        return jsonify({"favs": []})


@app.post("/api/subscribe")
def api_subscribe():
    """记录用户订阅（政策更新通知）的授权结果。"""
    data = request.get_json(silent=True) or {}
    openid = _openid_from_request() or (data.get("openid") or "").strip()  # 兼容旧前端
    tmpl_id = (data.get("tmpl_id") or "").strip()
    rule_subject = (data.get("rule_subject") or "").strip()
    if not openid or not tmpl_id:
        return jsonify({"errcode": 401, "message": "missing or invalid auth"}), 401
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO mini_app_subs (openid, tmpl_id, rule_subject)
                   VALUES (?, ?, ?)
                   ON CONFLICT(openid) DO UPDATE SET
                       tmpl_id = excluded.tmpl_id,
                       rule_subject = excluded.rule_subject,
                       accepted_at = datetime('now')""",
                (openid, tmpl_id, rule_subject),
            )
            conn.commit()
        return jsonify({"errcode": 0})
    except Exception as ex:
        return jsonify({"errcode": 500, "message": str(ex)}), 500


@app.get("/api/hot-queries")
def api_hot_queries():
    """最近 7 天最热门的搜索关键词，供首页/搜索联想。"""
    try:
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT q, COUNT(*) as cnt
                   FROM mini_app_query_logs
                   WHERE t > ?
                     AND length(q) >= 2 AND length(q) <= 20
                   GROUP BY q
                   ORDER BY cnt DESC, MAX(t) DESC
                   LIMIT ?""",
                (time.time() - 7 * 86400, int(request.args.get("limit", 12))),
            ).fetchall()
        return jsonify({
            "items": [{"q": r[0], "count": r[1]} for r in rows]
        })
    except Exception:
        return jsonify({"items": []})


@app.post("/api/query-log")
def api_query_log():
    """记录一次搜索（用于热门 + 个性化推荐）。"""
    data = request.get_json(silent=True) or {}
    q = (data.get("q") or "").strip()
    if not q or len(q) > 50:
        return jsonify({"errcode": 400, "message": "invalid q"}), 400
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO mini_app_query_logs (openid, q, cat, hit_count, t)
                   VALUES (?, ?, ?, ?, ?)""",
                (data.get("openid") or "", q, data.get("cat") or "",
                 int(data.get("hit_count") or 0), time.time()),
            )
            conn.commit()
    except Exception:
        pass
    return jsonify({"errcode": 0})


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
