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
import hmac
import html
import json
import math
import os
import secrets
import sys
import time
from functools import wraps

from flask import Flask, Response, abort, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from . import admin, db, nhsa_api, nhsa_browse, yp2025, yp2025_sx
from .helpers import PAGE_SIZE, SOURCE_LABEL
from .query_utils import _safe_int, fts_search, row_to_dict
from .search_backend import _row_to_kp_dict, detect_mode, do_search

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---- Security configuration (audit 2026-09-03 H3 + H2 + H1) ------------
# SECRET_KEY: required for Flask sessions, signed cookies, Flask-WTF, etc.
# 优先级: env > 内置随机 fallback. 生产必须设 (审计 H3).
_secret_env = os.environ.get("MA_SECRET_KEY")
if _secret_env:
    app.config["SECRET_KEY"] = _secret_env
elif not app.debug:
    # 生产模式必须有 secret,否则 fail-fast
    raise RuntimeError(
        "MA_SECRET_KEY environment variable is required in production. "
        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
    )
else:
    # 开发模式用一次性随机 key (重启即失效,但 dev 没关系)
    app.config["SECRET_KEY"] = secrets.token_hex(32)

# JSON 配置
app.config["JSON_AS_ASCII"] = False

# ---- Flask-Talisman: 安全响应头 (审计 H2) -------------------------------
# 默认 strict CSP / HSTS / X-Frame-Options=DENY / X-Content-Type-Options=nosniff
# dev 模式禁用 force_https / HSTS,避免本地调试被强制 HTTPS
Talisman(
    app,
    force_https=not app.debug,
    strict_transport_security=not app.debug,
    strict_transport_security_max_age=31536000,
    strict_transport_security_include_subdomains=True,
    strict_transport_security_preload=True,
    content_security_policy={
        "default-src": "'self'",
        "script-src": ["'self'", "'unsafe-inline'"],  # 内联 script 已有,允许
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
        "frame-ancestors": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
    },
    referrer_policy="strict-origin-when-cross-origin",
    feature_policy={
        "geolocation": "'none'",
        "microphone": "'none'",
        "camera": "'none'",
    },
)

# ---- Flask-Limiter: 限速 (审计 H1) ---------------------------------------
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute", "3000 per hour"],  # 全局宽松限制
    storage_uri="memory://",  # 单进程; 多 worker 时需改 redis
    headers_enabled=True,
)

# ---- /admin/* 鉴权 (审计 C1) ----------------------------------------------
# 双因子: (a) HTTP Basic Auth (env) + (b) IP 白名单 (env)
# 任一失败 → 401/403
_ADMIN_BASIC_USER = os.environ.get("MA_ADMIN_USER")
_ADMIN_BASIC_PASS = os.environ.get("MA_ADMIN_PASS")
_ADMIN_IP_ALLOW = os.environ.get(
    "MA_ADMIN_ALLOW_CIDR", "127.0.0.1/32,::1/128"
)  # 默认仅本机


def _parse_cidrs(s: str):
    """Parse a comma-separated CIDR list; return list of (net, mask) tuples for IPv4."""
    import ipaddress
    out = []
    for raw in s.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            if "/" in raw:
                out.append(ipaddress.ip_network(raw, strict=False))
            else:
                # bare IP → /32 (v4) or /128 (v6)
                ip = ipaddress.ip_address(raw)
                out.append(
                    ipaddress.ip_network(
                        f"{raw}/32" if ip.version == 4 else f"{raw}/128",
                        strict=False,
                    )
                )
        except ValueError:
            pass
    return out


_ADMIN_NETS = _parse_cidrs(_ADMIN_IP_ALLOW)


def _check_basic_auth() -> Response | None:
    """Return a 401 Response if basic-auth fails, else None."""
    if not _ADMIN_BASIC_USER or not _ADMIN_BASIC_PASS:
        # 没有配 creds → 完全拒绝 (默认 deny)
        resp = Response("Admin auth not configured", status=401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="admin"'
        return resp
    h = request.headers.get("Authorization", "")
    if not h.startswith("Basic "):
        resp = Response("Auth required", status=401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="admin"'
        return resp
    try:
        import base64
        user, _, pw = base64.b64decode(h[6:]).decode("utf-8", "replace").partition(":")
    except Exception:
        return Response("Bad auth header", status=401)
    # constant-time compare 防时序攻击
    if not (hmac.compare_digest(user, _ADMIN_BASIC_USER)
            and hmac.compare_digest(pw, _ADMIN_BASIC_PASS)):
        resp = Response("Invalid credentials", status=401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="admin"'
        return resp
    return None


def _ip_allowed(remote: str) -> bool:
    import ipaddress
    try:
        addr = ipaddress.ip_address(remote or "0.0.0.0")
    except ValueError:
        return False
    return any(addr in n for n in _ADMIN_NETS)


@app.before_request
def _admin_gate():
    """拦截 /admin/*: Basic Auth + IP 白名单."""
    if not request.path.startswith("/admin"):
        return None
    if not _ip_allowed(request.remote_addr or ""):
        return Response("Forbidden: IP not in admin allowlist", status=403)
    return _check_basic_auth()


# ---- Blueprint 注册 (在鉴权 gate 之后) -----------------------------------
nhsa_api.register(app)
limiter.limit("60 per minute")(nhsa_api.__dict__.get("_stats", lambda: None))  # no-op if missing

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
    limit = _safe_int(request.args.get("limit"), default=12, min_=1, max_=30)
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
    page = _safe_int(request.args.get("page"), default=1, min_=1, max_=10000)
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
    page = _safe_int(request.args.get("page"), default=1, min_=1, max_=10000)
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
        # 1. 检查耗材代码 (C 开头 + >=17 位数字)
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

        # 2. NHSA 6 类代码表 (yp 药品 / tcm 中药 / icd 诊断 / ivd 体外诊断 / ms 医疗服务)
        # 这些是 NHSA 官方代码表, 在 knowledge_point_codes 里没有, 但 search 接口能命中
        nhsa_tables = [
            ("yp_codes",   "nhsa_yp",   ["code", "reg_name", "product_name", "spec", "dosage_form", "manufacturer", "approval_no"]),
            ("tcm_codes",  "nhsa_tcm",  ["code", "name", "p_code", "part_code", "code_length", "level", "apply_explain", "remark", "class_code", "class_name"]),
            ("icd_codes",  "nhsa_icd",  ["code", "chapter_no", "chapter_range", "chapter_name", "section_range", "section_name", "category_code", "category_name", "subcategory_code", "subcategory_name", "diagnosis_code", "diagnosis_name"]),
            ("ivd_codes",  "nhsa_ivd",  ["code", "cat_l1_name", "cat_l2_name", "cat_l3_name", "testing_category", "testing_index", "use_type", "check_type", "company_name"]),
            ("medical_service_codes", "nhsa_ms", ["code", "name", "p_code", "level", "pinyin_code", "contains_content", "excluded_content", "charge_unit", "explain", "area", "is_using"]),
        ]
        for tbl, kind, keys in nhsa_tables:
            row = conn.execute(f"SELECT {', '.join(keys)} FROM {tbl} WHERE code = ?", (code,)).fetchone()
            if row:
                return jsonify({"code": code, "kind": kind, "data": row_to_dict(row, keys)})

        # 3. KP 关联代码 (审核规则关联的医保编码)
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
