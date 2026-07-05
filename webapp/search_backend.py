"""搜索后端逻辑(独立于 Flask 路由).

供 app.py (/search) 和 kp.py (/api/search) 共用。

- detect_mode: 根据查询字符串判断搜索模式
- search_name / search_initials / search_code: 三种模式的搜索
- do_search: 派发到上面三种之一
- row_to_kp_dict: 把搜索结果行转成 KP dict(含 partner 解析)

Extracted from app.py (TD-08 第二期配套).
"""
from __future__ import annotations

import re
from typing import Optional

from .helpers import parse_kp_partner
from .query_utils import fts_query as jieba_query


CODE_RE = re.compile(r"^[A-Z0-9]{8,}$")
LETTERS_RE = re.compile(r"^[A-Za-z]+$")


def detect_mode(q: str) -> str:
    """根据查询字符串判断搜索模式: code / initials / name."""
    q = (q or "").strip()
    if not q:
        return "name"
    upper = q.upper()
    if CODE_RE.match(upper):
        return "code"
    if LETTERS_RE.match(q) and len(q) >= 2:
        return "initials"
    return "name"


def _row_to_kp_dict(row) -> dict:
    """将搜索结果行 tuple 转 KP dict(解出 partner 配对项)."""
    raw = row[11] if len(row) > 11 else None
    obj = row[12] if len(row) > 12 else None
    return {
        "id": row[0],
        "subject_name": row[1],
        "pinyin_initials": row[2],
        "code_count": row[3],
        "detection_logic": row[4],
        "logic_basis": row[5],
        "codes_preview": row[6],
        "rule_subject": row[7],
        "source": row[8],
        "batch_label": row[9],
        "pub_date": row[10],
        "partner": parse_kp_partner(raw, obj),
    }


def search_name(conn, q: str, source: Optional[str], limit: int, offset: int):
    """name 模式:FTS5 + bm25 排序."""
    fts_q = jieba_query(q)
    if not fts_q:
        return [], 0
    sql = """
        SELECT kp.id, kp.subject_name, kp.pinyin_initials, kp.code_count,
               kp.detection_logic, kp.logic_basis, kp.codes,
               r.rule_subject, r.source, b.batch_label, b.pub_date,
               kp.raw_row, r.object_type,
               bm25(kp_fts) AS score
        FROM kp_fts
        JOIN knowledge_points kp ON kp.id = kp_fts.rowid
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kp_fts MATCH ?
    """
    params: list = [fts_q]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY score LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    if source:
        cnt_sql = (
            "SELECT COUNT(*) FROM kp_fts JOIN knowledge_points kp ON kp.id=kp_fts.rowid "
            "JOIN rules r ON r.id=kp.rule_id WHERE kp_fts MATCH ? AND r.source = ?"
        )
        total = conn.execute(cnt_sql, [fts_q, source]).fetchone()[0]
    else:
        total = conn.execute(
            "SELECT COUNT(*) FROM kp_fts WHERE kp_fts MATCH ?", [fts_q]
        ).fetchone()[0]
    return rows, total


def search_initials(conn, q: str, source: Optional[str], limit: int, offset: int):
    """initials 模式:拼音首字母 LIKE 前缀."""
    needle = q.lower()
    sql = """
        SELECT kp.id, kp.subject_name, kp.pinyin_initials, kp.code_count,
               kp.detection_logic, kp.logic_basis, kp.codes,
               r.rule_subject, r.source, b.batch_label, b.pub_date,
               kp.raw_row, r.object_type
        FROM knowledge_points kp
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kp.pinyin_initials LIKE ?
    """
    params: list = [needle + "%"]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY kp.subject_name LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    if source:
        cnt_sql = (
            "SELECT COUNT(*) FROM knowledge_points kp JOIN rules r ON r.id=kp.rule_id "
            "WHERE kp.pinyin_initials LIKE ? AND r.source = ?"
        )
        total = conn.execute(cnt_sql, [needle + "%", source]).fetchone()[0]
    else:
        total = conn.execute(
            "SELECT COUNT(*) FROM knowledge_points kp WHERE kp.pinyin_initials LIKE ?",
            [needle + "%"],
        ).fetchone()[0]
    # 兼容 search_name 的元组格式(末尾追加 score=None)
    return [tuple(r) + (None,) for r in rows], total


def search_code(conn, q: str, source: Optional[str], limit: int, offset: int):
    """code 模式:医保编码精确匹配."""
    code = q.upper()
    sql = """
        SELECT kp.id, kp.subject_name, kp.pinyin_initials, kp.code_count,
               kp.detection_logic, kp.logic_basis, kp.codes,
               r.rule_subject, r.source, b.batch_label, b.pub_date,
               kp.raw_row, r.object_type
        FROM knowledge_point_codes kpc
        JOIN knowledge_points kp ON kp.id = kpc.kp_id
        JOIN rules r ON r.id = kp.rule_id
        JOIN batches b ON b.id = r.batch_id
        WHERE kpc.code = ?
    """
    params: list = [code]
    if source:
        sql += " AND r.source = ?"
        params.append(source)
    sql += " ORDER BY kp.id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    total = len(rows) + offset if len(rows) == limit else (offset + len(rows))
    return [(r + (None,)) for r in rows], total


def do_search(conn, q: str, mode: str, source: Optional[str], limit: int, offset: int):
    """根据 mode 派发到上面三个 search_* 之一."""
    if mode == "code":
        return search_code(conn, q, source, limit, offset)
    if mode == "initials":
        return search_initials(conn, q, source, limit, offset)
    return search_name(conn, q, source, limit, offset)
