"""Utility functions for SQL query construction and safe input conversion.

Extracted from app.py + admin.py to address:
  - TD-06: FTS query builder duplication (was jieba_query in app.py
    and _admin_fts_query in admin.py) - single source of truth.
  - TD-07: int() without validation - _safe_int() enforces bounds and
    returns a default on conversion error, eliminating try/except
    noise at every HTTP parameter site.
"""


from __future__ import annotations

import re


# ---- FTS5 query construction --------------------------------------------

_ASCII_ONLY = re.compile(r"^[A-Za-z0-9]+$")
_KEEP = re.compile(r"[^\w\u4e00-\u9fff]+")


def fts_query(q: str, *, sanitize: bool = False) -> str:
    """Build FTS5 MATCH expression for the query.

    FTS5 unicode61 tokenizes Chinese as single chars, so a multi-char
    phrase match (e.g. '"阿泰特韦"') silently returns 0 hits. Use
    prefix match (token*) instead.

    Strategy:
        - Pure ASCII/digits: append * for prefix match.
        - Chinese (>=2 chars): prefix match on first 2 chars.
        - Single Chinese char: prefix match that single char.

    When `sanitize=True`, non-word/非 CJK characters are replaced with
    spaces first (use when accepting arbitrary user-supplied keywords).
    """
    q = (q or "").strip()
    if not q:
        return ""
    if sanitize:
        q = _KEEP.sub(" ", q).strip()
        if not q:
            return ""
    if _ASCII_ONLY.match(q):
        return q + "*"
    if len(q) >= 2:
        return f'"{q[:2]}"*'
    return f'"{q}"*'


# ---- FTS5 search with LIKE fallback ------------------------------------

def fts_search(
    conn,
    q: str,
    fts_table: str,
    table: str,
    fields: list,
    name_field: str,
    code_field: str,
    limit: int = 50,
    like_fields=None,
) -> tuple:
    """FTS5 search with LIKE fallback on syntax errors.

    Parameters mirror app.py:_code_search defaults. Returns (rows, total).
    Both parameters and return type are SQLite row tuples unless a
    row_factory is set on the connection.
    """
    fts = fts_query(q)
    if not fts:
        return [], 0
    cols = ", ".join(f"t.{f}" for f in fields)
    try:
        rows = conn.execute(
            f"SELECT t.rowid AS __rid__, {cols} FROM {table} t "
            f"WHERE t.rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?) "
            f"ORDER BY t.{code_field} LIMIT ?",
            (fts, limit),
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {table} t "
            f"WHERE t.rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?)",
            (fts,),
        ).fetchone()[0]
    except Exception:
        like_pat = f"%{q.strip()}%"
        lf = like_fields or fields
        wheres = " OR ".join(f"t.{f} LIKE ?" for f in lf)
        params = [like_pat] * len(lf)
        rows = conn.execute(
            f"SELECT t.rowid AS __rid__, {cols} FROM {table} t WHERE {wheres} "
            f"ORDER BY t.{code_field} LIMIT ?",
            (*params, limit),
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {table} t WHERE {wheres}", params,
        ).fetchone()[0]
    return rows, total




def row_to_dict(row, keys=None):
    """Convert a SQLite row to a plain dict.

    Works for:
      - sqlite3.Row (uses row.keys() if conn.row_factory = sqlite3.Row)
      - plain tuple + caller-supplied keys (preferred explicit form)

    Returns {} for None. Returns dict(row) as a fallback for plain
    tuples when no keys were supplied.
    """
    if row is None:
        return {}
    if keys is not None:
        return {k: row[i] for i, k in enumerate(keys) if i < len(row)}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    if isinstance(row, (list, tuple)):
        return {i: v for i, v in enumerate(row)}
    return dict(row)


# ---- Safe input conversion ---------------------------------------------

def _safe_int(
    raw,
    default: int = 0,
    min_=None,
    max_=None,
) -> int:
    """Convert raw value to int safely; never raises.

    - Returns `default` for None or non-numeric values.
    - Optionally clamps the result to [min_, max_] inclusive.

    Use at the boundary of HTTP query params or any user-controlled
    string that the caller previously relied on `int(...)` for.
    """
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if min_ is not None and v < min_:
        v = min_
    if max_ is not None and v > max_:
        v = max_
    return v


# ---- Pagination helpers -------------------------------------------------

def page_from(
    args,
    name: str = "page",
    default: int = 1,
    min_: int = 1,
    max_: int = 10000,
) -> int:
    """Extract a clamped page number from a Flask request.args-like."""
    return _safe_int(args.get(name, default), default=default, min_=min_, max_=max_)


def limit_from(
    args,
    name: str = "limit",
    default: int = 50,
    min_: int = 1,
    max_: int = 500,
) -> int:
    """Extract a clamped list limit from a Flask request.args-like."""
    return _safe_int(args.get(name, default), default=default, min_=min_, max_=max_)
