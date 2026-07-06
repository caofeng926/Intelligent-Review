"""
webapp/admin.py
通用管理后台蓝图：aside 菜单 + header 标题栏 + main 工作区。
所有页面继承 templates/admin/base_admin.html，菜单在 base 中静态配置。
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from typing import Optional

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from . import db
from .query_utils import fts_query, row_to_dict

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
    static_folder="static",
    static_url_path="/admin-static",
)

# ---------- 菜单（可被 base_admin.html 渲染）----------
# 隐藏的菜单组 key（路由保留, 等用户给具体三级菜单后移除）
HIDDEN_GROUPS = {"policy"}


MENU = [
    {
        "key": "policy",
        "label": "医保政策查询",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>',
        "group": True,
        "children": [
            {"key": "policy_urban", "label": "城乡居民", "endpoint": "admin.policy_urban"},
            {"key": "policy_employee", "label": "职工医保", "endpoint": "admin.policy_employee"},
        ],
    },
    {
        "key": "rules_group",
        "label": "智能审核规则查询",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>',
        "group": True,
        "children": [
            {"key": "rules", "label": "审核规则", "endpoint": "admin.rules_page"},
            {"key": "knowledge", "label": "审核知识点", "endpoint": "admin.knowledge_page"},
            {"key": "batches", "label": "规则批次", "endpoint": "admin.batches_page"},
        ],
    },
    {
        "key": "codes_group",
        "label": "医保编码查询",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>',
        "group": True,
        "children": [
            {"key": "yp", "label": "医保药品", "endpoint": "admin.codes_yp"},
            {"key": "hc", "label": "医保医用耗材", "endpoint": "admin.codes_hc"},
            {"key": "hc7", "label": "7 类重点耗材", "endpoint": "admin.codes_hc7"},
            {"key": "ivd", "label": "体外诊断试剂", "endpoint": "admin.codes_ivd"},
            {"key": "icd", "label": "疾病诊断 ICD-10", "endpoint": "admin.codes_icd"},
            {"key": "ms", "label": "医疗服务项目", "endpoint": "admin.codes_ms"},
            {"key": "tcm", "label": "中医病证术语", "endpoint": "admin.codes_tcm"},
        ],
    },
    {
        "key": "dashboard",
        "label": "概览",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
        "endpoint": "admin.dashboard",
    },
    {
        "key": "sync",
        "label": "数据同步",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
        "endpoint": "admin.sync_page",
    },
    {
        "key": "audit",
        "label": "审计日志",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="14" y2="14"/></svg>',
        "endpoint": "admin.audit_page",
    },
    {
        "key": "settings",
        "label": "系统设置",
        "icon": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
        "endpoint": "admin.settings_page",
    },
]


def _ctx():
    """全局 context，所有 admin 页面共享。"""
    # 过滤隐藏的菜单组（路由仍保留, 只是不显示在左侧菜单）
    menu = [m for m in MENU if m.get("key") not in HIDDEN_GROUPS]
    counts = {}
    try:
        with db.connect() as conn:
            for tbl in ("batches", "rules", "knowledge_points",
                        "knowledge_point_codes", "consumable_codes",
                        "ivd_codes", "consumable7_codes", "icd_codes",
                        "medical_service_codes", "tcm_codes",
                        "yp_codes", "drug_detail"):
                try:
                    counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                except Exception:
                    counts[tbl] = 0
    except Exception:
        pass
    return {
        "admin_menu": menu,
        "counts": counts,
        "now": datetime.now(),
    }


@admin_bp.context_processor
def inject_globals():
    return _ctx()


# ---------- 路由 ----------
@admin_bp.route("/")
@admin_bp.route("/dashboard")
def dashboard():
    """概览 / 仪表板。"""
    with db.connect() as conn:
        # Top stats
        stats = {
            "rules": conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0],
            "kp": conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0],
            "codes": conn.execute(
                "SELECT COUNT(*) FROM knowledge_point_codes"
            ).fetchone()[0],
            "batches": conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
        }
        # 最新批次
        recent_batches = conn.execute(
            "SELECT id, source, batch_label, rule_subject, pub_date "
            "FROM batches ORDER BY id DESC LIMIT 6"
        ).fetchall()
        recent_batches = [row_to_dict(r, ["id", "source", "batch_label", "rule_subject", "pub_date"])
            for r in recent_batches]
        # 最新规则
        recent_rules = conn.execute(
            "SELECT r.id, r.rule_subject, b.batch_label, b.pub_date, "
            "       (SELECT COUNT(*) FROM knowledge_points kp "
            "        WHERE kp.rule_id = r.id) AS kp_count "
            "FROM rules r JOIN batches b ON r.batch_id = b.id "
            "ORDER BY r.id DESC LIMIT 8"
        ).fetchall()
        recent_rules = [row_to_dict(r, ["id", "rule_subject", "batch_label", "pub_date", "kp_count"])
            for r in recent_rules]
    return render_template(
        "admin/dashboard.html",
        title="概览",
        active="dashboard",
        stats=stats,
        recent_batches=recent_batches,
        recent_rules=recent_rules,
    )


@admin_bp.route("/rules")
def rules_page():
    """规则管理列表。"""
    page = max(1, int(request.args.get("page", 1)))
    page_size = 20
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        rows = conn.execute(
            "SELECT r.id, r.rule_subject, b.batch_label, b.pub_date, "
            "       r.row_count, "
            "       (SELECT COUNT(*) FROM knowledge_points kp "
            "        WHERE kp.rule_id = r.id) AS kp_count, "
            "       (SELECT COUNT(*) FROM knowledge_point_codes kpc "
            "        JOIN knowledge_points kp ON kpc.kp_id = kp.id "
            "        WHERE kp.rule_id = r.id) AS code_count "
            "FROM rules r JOIN batches b ON r.batch_id = b.id "
            "ORDER BY r.id DESC LIMIT ? OFFSET ?",
            (page_size, (page-1)*page_size),
        ).fetchall()
        rows = [row_to_dict(r, ["id", "rule_subject", "batch_label", "pub_date",
             "row_count", "kp_count", "code_count"]) for r in rows]
    pages = (total + page_size - 1) // page_size
    return render_template(
        "admin/rules.html",
        title="审核规则",
        active="rules",
        rows=rows, total=total, page=page, pages=pages, page_size=page_size,
    )


@admin_bp.route("/codes")
def codes_page():
    """编码库首页（多 tab 概览）。"""
    return render_template(
        "admin/codes.html",
        title="医保编码库",
        active="codes",
    )


# 编码库各 tab 配置：(key, title, table, fts_table, label_col, code_col, active)
CODES_TABS = {
    "yp": {
        "label": "医保药品",
        "table": "yp_codes",
        "fts_table": "yp_codes_fts",
        "name_col": "reg_name",
        "code_col": "code",
        "columns": [
            ("code", "编码"),
            ("reg_name", "通用名"),
            ("product_name", "产品名称"),
            ("reg_dosage_form", "剂型"),
            ("reg_spec", "规格"),
            ("manufacturer", "生产企业"),
            ("approval_no", "批准文号"),
            ("list_class", "医保类别"),
        ],
    },
    "hc": {
        "label": "医保医用耗材",
        "table": "consumable_codes",
        "fts_table": "consumable_codes_fts",
        "name_col": "generic_name",
        "code_col": "code",
        "columns": [
            ("code", "耗材编码"),
            ("generic_name", "通用名"),
            ("spec", "规格"),
            ("material", "材质"),
            ("generic_category", "管理类别"),
            ("generic_no", "医保通用名编号"),
            ("cat_l1_name", "一级分类"),
            ("cat_l2_name", "二级分类"),
            ("cat_l3_name", "三级分类"),
            ("manufacturer", "生产企业"),
        ],
    },
    "ivd": {
        "label": "体外诊断试剂",
        "table": "ivd_codes",
        "fts_table": "ivd_codes_fts",
        "name_col": "catalog_full_name",
        "code_col": "code",
        "columns": [
            ("code", "试剂编码"),
            ("catalog_full_name", "产品名称"),
            ("spec_code", "规格"),
            ("testing_category", "检验类别"),
            ("testing_index", "检验指标"),
            ("use_type", "使用类型"),
            ("check_type", "检查类型"),
            ("company_name", "企业名称"),
        ],
    },
    "hc7": {
        "label": "7 类重点耗材",
        "table": "consumable7_codes",
        "fts_table": "consumable_codes_fts",
        "name_col": "generic_name",
        "code_col": "code",
        "columns": [
            ("code", "耗材编码"),
            ("generic_name", "通用名"),
            ("spec", "规格"),
            ("material", "材质"),
            ("generic_category", "管理类别"),
            ("cat_l1_name", "一级分类"),
            ("cat_l2_name", "二级分类"),
            ("cat_l3_name", "三级分类"),
            ("manufacturer", "生产企业"),
        ],
    },
    "icd": {
        "label": "疾病诊断 ICD-10",
        "table": "icd_codes",
        "fts_table": "icd_codes_fts",
        "name_col": "diagnosis_name",
        "code_col": "code",
        "columns": [
            ("code", "诊断编码"),
            ("diagnosis_name", "诊断名称"),
            ("chapter_name", "章"),
            ("section_name", "节"),
            ("category_name", "类目"),
            ("subcategory_name", "亚目"),
        ],
    },
    "ms": {
        "label": "医疗服务项目",
        "table": "medical_service_codes",
        "fts_table": "medical_service_codes_fts",
        "name_col": "name",
        "code_col": "code",
        "columns": [
            ("code", "项目编码"),
            ("name", "项目名称"),
            ("pinyin_code", "拼音助记"),
            ("level", "项目级别"),
            ("charge_unit", "计价单位"),
            ("explain", "项目说明"),
            ("is_using", "启用状态"),
        ],
    },
    "tcm": {
        "label": "中医病证术语",
        "table": "tcm_codes",
        "fts_table": "tcm_codes_fts",
        "name_col": "name",
        "code_col": "code",
        "columns": [
            ("code", "编码"),
            ("name", "名称"),
            ("part_code", "类目码"),
            ("class_name", "类目名称"),
            ("level", "层级"),
            ("apply_explain", "适用说明"),
            ("remark", "备注"),
        ],
    },
}


@admin_bp.route("/codes/yp", endpoint="codes_yp")
@admin_bp.route("/codes/hc", endpoint="codes_hc")
@admin_bp.route("/codes/ivd", endpoint="codes_ivd")
@admin_bp.route("/codes/hc7", endpoint="codes_hc7")
@admin_bp.route("/codes/icd", endpoint="codes_icd")
@admin_bp.route("/codes/ms", endpoint="codes_ms")
@admin_bp.route("/codes/tcm", endpoint="codes_tcm")
def codes_browse():
    """统一的编码浏览/搜索页（按 tab 区分数据源）。"""
    # Determine current tab from request.endpoint
    tab = request.endpoint.split(".")[-1]  # e.g. "codes_yp"
    tab_key = tab.replace("codes_", "") if tab.startswith("codes_") else "yp"
    if tab_key not in CODES_TABS:
        abort(404)
    cfg = CODES_TABS[tab_key]
    label = cfg["label"]
    table = cfg["table"]
    fts_table = cfg["fts_table"]
    columns = cfg["columns"]  # [(col, label), ...]
    name_col = cfg["name_col"]
    code_col = cfg["code_col"]
    select_cols = ", ".join(c[0] + " AS " + chr(34) + c[0] + chr(34) for c in columns)
    col_names = [c[0] for c in columns]

    q = (request.args.get("q") or "").strip()
    page = max(1, int(request.args.get("page", 1)))
    page_size = 30

    with db.connect() as conn:
        total_all = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        rows = []
        total = 0
        if q:
            fts = fts_query(q)
            if fts:
                try:
                    rows = conn.execute(
                        f"SELECT {select_cols} "
                        f"FROM {table} "
                        f"WHERE {table}.rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?) "
                        f"ORDER BY {code_col} LIMIT ? OFFSET ?",
                        (fts, page_size, (page - 1) * page_size),
                    ).fetchall()
                    total = conn.execute(
                        f"SELECT COUNT(*) FROM {table} "
                        f"WHERE {table}.rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?)",
                        (fts,),
                    ).fetchone()[0]
                except Exception as e:
                    current_app.logger.warning("codes_browse query failed: %s", e)
                    rows, total = [], 0
            rows = [row_to_dict(r, col_names) for r in rows]
        else:
            total = total_all
    pages = (total + page_size - 1) // page_size

    return render_template(
        "admin/codes_tab.html",
        title=label,
        active=tab_key,
        tab_key=tab_key,
        tab_label=label,
        table=table,
        columns=columns,
        total=total_all,
        matched=total if q else None,
        query=q,
        rows=rows,
        page=page,
        pages=pages,
        page_size=page_size,
        latest=_nhsa_batch(table),
    )


@admin_bp.route("/knowledge")
def knowledge_page():
    """知识点列表。"""
    page = max(1, int(request.args.get("page", 1)))
    page_size = 20
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
        rows = conn.execute(
            "SELECT kp.id, kp.subject_name, kp.code_count, kp.pinyin_initials, "
            "       r.rule_subject, b.batch_label "
            "FROM knowledge_points kp "
            "JOIN rules r ON kp.rule_id = r.id "
            "JOIN batches b ON r.batch_id = b.id "
            "ORDER BY kp.id DESC LIMIT ? OFFSET ?",
            (page_size, (page-1)*page_size),
        ).fetchall()
        rows = [row_to_dict(r, ["id", "subject_name", "code_count", "pinyin_initials",
             "rule_subject", "batch_label"]) for r in rows]
    pages = (total + page_size - 1) // page_size
    return render_template(
        "admin/knowledge.html",
        title="知识点",
        active="knowledge",
        rows=rows, total=total, page=page, pages=pages, page_size=page_size,
    )


@admin_bp.route("/sync")
def sync_page():
    """数据同步状态。"""
    with db.connect() as conn:
        batches = conn.execute(
            "SELECT ROWID, source, batch_label, pub_date, ingested_at, "
            "       json_path, csv_path, record_count, sysflag "
            "FROM nhsa_batches ORDER BY ingested_at DESC"
        ).fetchall()
        batches = [row_to_dict(b, ["rowid", "source", "batch_label", "pub_date", "ingested_at",
             "json_path", "csv_path", "record_count", "sysflag"])
            for b in batches]
    return render_template(
        "admin/sync.html",
        title="数据同步",
        active="sync",
        batches=batches,
    )


@admin_bp.route("/audit")
def audit_page():
    """审计日志（基于 SQLite + service journal）。"""
    page = max(1, int(request.args.get("page", 1)))
    page_size = 50
    return render_template(
        "admin/audit.html",
        title="审计日志",
        active="audit",
        page=page, page_size=page_size,
    )


@admin_bp.route("/settings")
def settings_page():
    """系统设置（只读配置快照）。"""
    import platform
    return render_template(
        "admin/settings.html",
        title="系统设置",
        active="settings",
        info={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cwd": os.getcwd(),
            "data_path": current_app.config.get("DB_PATH", "n/a"),
        },
    )



# ==================== 规则批次 ====================
@admin_bp.route("/batches")
def batches_page():
    """规则批次列表（来自 batches 表，含 NHSA + PDF 2025）。"""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT b.id, b.source, b.batch_label, b.rule_subject, b.pub_date, "
            "       b.ann_url, b.pdf_path, "
            "       (SELECT COUNT(*) FROM rules r WHERE r.batch_id=b.id) AS rule_count, "
            "       (SELECT COUNT(*) FROM knowledge_points kp "
            "        JOIN rules r ON kp.rule_id=r.id WHERE r.batch_id=b.id) AS kp_count, "
            "       (SELECT COUNT(*) FROM knowledge_point_codes kpc "
            "        JOIN knowledge_points kp ON kpc.kp_id=kp.id "
            "        JOIN rules r ON kp.rule_id=r.id WHERE r.batch_id=b.id) AS code_count "
            "FROM batches b ORDER BY b.id DESC"
        ).fetchall()
        rows = [row_to_dict(r, ["id", "source", "batch_label", "rule_subject", "pub_date",
             "ann_url", "pdf_path", "rule_count", "kp_count", "code_count"])
            for r in rows]
    return render_template(
        "admin/batches.html",
        title="规则批次",
        active="batches",
        batches=rows,
    )


# ==================== 医保政策查询 ====================
@admin_bp.route("/policy/urban")
def policy_urban():
    """城乡居民医保政策查询。"""
    return render_template(
        "admin/policy_urban.html",
        title="城乡居民医保政策",
        active="policy_urban",
    )


@admin_bp.route("/policy/employee")
def policy_employee():
    """职工医保政策查询。"""
    return render_template(
        "admin/policy_employee.html",
        title="职工医保政策",
        active="policy_employee",
    )



# ==================== 规则详情（admin 内） ====================
@admin_bp.route("/rules/<int:rid>")
def rule_detail(rid: int):
    with db.connect() as conn:
        rule = conn.execute(
            "SELECT r.id, r.rule_subject, r.category, r.object_type, "
            "       r.page_start, r.page_end, r.xlsx_path, r.row_count, "
            "       b.id AS batch_id, b.batch_label, b.pub_date, b.ann_url "
            "FROM rules r JOIN batches b ON r.batch_id = b.id "
            "WHERE r.id = ?", (rid,)
        ).fetchone()
        if not rule:
            abort(404)
        keys = ["id", "rule_subject", "category", "object_type",
                "page_start", "page_end", "xlsx_path", "row_count",
                "batch_id", "batch_label", "pub_date", "ann_url"]
        rule = row_to_dict(rule, keys)
        kps = conn.execute(
            "SELECT kp.id, kp.seq, kp.subject_name, kp.code_count, kp.pinyin_initials, "
            "       (SELECT GROUP_CONCAT(kpc.code, \'・\') FROM knowledge_point_codes kpc "
            "        WHERE kpc.kp_id = kp.id LIMIT 5) AS codes_preview "
            "FROM knowledge_points kp "
            "WHERE kp.rule_id = ? ORDER BY kp.seq, kp.id LIMIT 200",
            (rid,)
        ).fetchall()
        kps = [row_to_dict(k, ["id", "seq", "subject_name", "code_count", "pinyin_initials", "codes_preview"])
            for k in kps]
    return render_template(
        "admin/rule_detail.html",
        title=f"规则 #{rid} - " + (rule.get('rule_subject') or ''),
        active="rules",
        rule=rule, kps=kps,
    )


# ==================== 知识点详情（admin 内） ====================
@admin_bp.route("/kp/<int:kp_id>")
def kp_detail(kp_id: int):
    with db.connect() as conn:
        kp = conn.execute(
            "SELECT kp.id, kp.rule_id, kp.seq, kp.subject_name, kp.code_count, "
            "       kp.detection_logic, kp.logic_basis, kp.codes, kp.remark, kp.pinyin_initials, "
            "       r.rule_subject, b.batch_label, b.pub_date "
            "FROM knowledge_points kp "
            "JOIN rules r ON kp.rule_id = r.id "
            "JOIN batches b ON r.batch_id = b.id "
            "WHERE kp.id = ?", (kp_id,)
        ).fetchone()
        if not kp:
            abort(404)
        keys = ["id", "rule_id", "seq", "subject_name", "code_count",
                "detection_logic", "logic_basis", "codes", "remark", "pinyin_initials",
                "rule_subject", "batch_label", "pub_date"]
        kp = row_to_dict(kp, keys)
        # Split codes by "・"
        if kp["codes"]:
            kp["codes_list"] = [c.strip() for c in kp["codes"].replace("\u30fb", "・").split("・") if c.strip()]
        else:
            kp["codes_list"] = []
    return render_template(
        "admin/kp_detail.html",
        title=f"知识点 #{kp_id} - " + (kp.get('subject_name') or ''),
        active="knowledge",
        kp=kp,
    )


# ==================== admin 内搜索 ====================
@admin_bp.route("/search")
def admin_search():
    q = (request.args.get("q") or "").strip()
    page = max(1, int(request.args.get("page", 1)))
    page_size = 20
    rows, total = [], 0
    if q:
        with db.connect() as conn:
            fts = fts_query(q)
            if fts:
                try:
                    rows = conn.execute(
                        "SELECT kp.id, kp.subject_name, kp.code_count, kp.pinyin_initials, "
                        "       r.rule_subject, b.batch_label "
                        "FROM kp_fts "
                        "JOIN knowledge_points kp ON kp.id = kp_fts.rowid "
                        "JOIN rules r ON kp.rule_id = r.id "
                        "JOIN batches b ON r.batch_id = b.id "
                        "WHERE kp_fts MATCH ? "
                        "ORDER BY bm25(kp_fts) LIMIT ? OFFSET ?",
                        (fts, page_size, (page - 1) * page_size),
                    ).fetchall()
                    total = conn.execute(
                        "SELECT COUNT(*) FROM kp_fts WHERE kp_fts MATCH ?",
                        (fts,),
                    ).fetchone()[0]
                except Exception:
                    rows, total = [], 0
            rows = [row_to_dict(r, ["id", "subject_name", "code_count", "pinyin_initials",
                 "rule_subject", "batch_label"]) for r in rows]
    pages = (total + page_size - 1) // page_size
    return render_template(
        "admin/search.html",
        title="搜索结果",
        active="",
        q=q, rows=rows, total=total, page=page, pages=pages, page_size=page_size,
    )

# ---------- helpers ----------
def _nhsa_batch(source: str) -> dict:
    with db.connect() as conn:
        r = conn.execute(
            "SELECT batch_label, pub_date, ingested_at, record_count "
            "FROM nhsa_batches WHERE source=? "
            "ORDER BY ingested_at DESC LIMIT 1", (source,)).fetchone()
    if not r:
        return {}
    keys = ["batch_label", "pub_date", "ingested_at", "record_count"]
    return row_to_dict(r, keys)
