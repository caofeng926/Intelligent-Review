"""SQLite schema + idempotent upsert helpers + FTS5 sync."""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kp.db")

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,
    batch_label   TEXT    NOT NULL,
    rule_subject  TEXT,
    pub_date      TEXT,
    ann_url       TEXT,
    pdf_path      TEXT,
    xlsx_path     TEXT
);
CREATE INDEX IF NOT EXISTS idx_batches_uniq
    ON batches(source, batch_label, IFNULL(rule_subject, ''));

CREATE TABLE IF NOT EXISTS rules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    source        TEXT    NOT NULL,
    rule_subject  TEXT    NOT NULL,
    category      TEXT,
    object_type   TEXT,
    page_start    INTEGER,
    page_end      INTEGER,
    xlsx_path     TEXT,
    row_count     INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_rules_batch_subject ON rules(source, batch_id, rule_subject);
CREATE INDEX IF NOT EXISTS idx_rules_subject ON rules(rule_subject);
CREATE INDEX IF NOT EXISTS idx_rules_source  ON rules(source);
CREATE INDEX IF NOT EXISTS idx_rules_cat     ON rules(category);

CREATE TABLE IF NOT EXISTS knowledge_points (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id          INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    seq              INTEGER,
    subject_name     TEXT,
    code_count       INTEGER,
    detection_logic  TEXT,
    logic_basis      TEXT,
    codes            TEXT,
    remark           TEXT,
    raw_row          TEXT
);
CREATE INDEX IF NOT EXISTS idx_kp_rule ON knowledge_points(rule_id);
CREATE INDEX IF NOT EXISTS idx_kp_seq  ON knowledge_points(rule_id, seq);

-- One-to-many: 1 KP may have many codes (drug/consumable different mfr/spec).
-- Sheet 1 of NHSA xlsx only declares code_count; actual codes live in sheet 2
-- and link back via seq (对应知识点序号).
CREATE TABLE IF NOT EXISTS knowledge_point_codes (
    kp_id     INTEGER NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    code_seq  INTEGER NOT NULL,
    code      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kpc_kp ON knowledge_point_codes(kp_id);
CREATE INDEX IF NOT EXISTS idx_kpc_code ON knowledge_point_codes(code);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_kpc ON knowledge_point_codes(kp_id, code);

CREATE VIRTUAL TABLE IF NOT EXISTS kp_fts USING fts5(
    subject_name, detection_logic, logic_basis, remark, codes,
    content='knowledge_points', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS kp_ai AFTER INSERT ON knowledge_points BEGIN
    INSERT INTO kp_fts(rowid, subject_name, detection_logic, logic_basis, remark, codes)
    VALUES (new.id, COALESCE(new.subject_name,''), COALESCE(new.detection_logic,''),
            COALESCE(new.logic_basis,''), COALESCE(new.remark,''), COALESCE(new.codes,''));
END;
CREATE TRIGGER IF NOT EXISTS kp_ad AFTER DELETE ON knowledge_points BEGIN
    INSERT INTO kp_fts(kp_fts, rowid, subject_name, detection_logic, logic_basis, remark, codes)
    VALUES ('delete', old.id, COALESCE(old.subject_name,''), COALESCE(old.detection_logic,''),
            COALESCE(old.logic_basis,''), COALESCE(old.remark,''), COALESCE(old.codes,''));
END;
CREATE TRIGGER IF NOT EXISTS kp_au AFTER UPDATE ON knowledge_points BEGIN
    INSERT INTO kp_fts(kp_fts, rowid, subject_name, detection_logic, logic_basis, remark, codes)
    VALUES ('delete', old.id, COALESCE(old.subject_name,''), COALESCE(old.detection_logic,''),
            COALESCE(old.logic_basis,''), COALESCE(old.remark,''), COALESCE(old.codes,''));
    INSERT INTO kp_fts(rowid, subject_name, detection_logic, logic_basis, remark, codes)
    VALUES (new.id, COALESCE(new.subject_name,''), COALESCE(new.detection_logic,''),
            COALESCE(new.logic_basis,''), COALESCE(new.remark,''), COALESCE(new.codes,''));
END;
"""


@contextmanager
def connect(path: Optional[str] = None):
    p = path or DB_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Optional[str] = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def reset_db(path: Optional[str] = None) -> None:
    p = path or DB_PATH
    if os.path.exists(p):
        os.remove(p)
    init_db(p)


def get_or_create_batch(
    conn,
    source: str,
    batch_label: str,
    *,
    rule_subject=None,
    pub_date=None,
    ann_url=None,
    pdf_path=None,
    xlsx_path=None,
):
    row = conn.execute(
        """SELECT id FROM batches
           WHERE source = ? AND batch_label = ? AND IFNULL(rule_subject,'') = IFNULL(?, '')""",
        (source, batch_label, rule_subject),
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        """INSERT INTO batches(source, batch_label, rule_subject, pub_date, ann_url, pdf_path, xlsx_path)
           VALUES (?,?,?,?,?,?,?)""",
        (source, batch_label, rule_subject, pub_date, ann_url, pdf_path, xlsx_path),
    )
    return cur.lastrowid


def get_or_create_rule(
    conn,
    source: str,
    rule_subject: str,
    batch_id: int,
    *,
    category=None,
    object_type=None,
    page_start=None,
    page_end=None,
    xlsx_path=None,
):
    row = conn.execute(
        "SELECT id FROM rules WHERE source = ? AND batch_id = ? AND rule_subject = ?",
        (source, batch_id, rule_subject),
    ).fetchone()
    if row:
        if any(v is not None for v in (category, object_type, page_start, page_end, xlsx_path)):
            conn.execute(
                """UPDATE rules SET
                     category = COALESCE(?, category),
                     object_type = COALESCE(?, object_type),
                     page_start = COALESCE(?, page_start),
                     page_end = COALESCE(?, page_end),
                     xlsx_path = COALESCE(?, xlsx_path)
                   WHERE id = ?""",
                (category, object_type, page_start, page_end, xlsx_path, row[0]),
            )
        return row[0]
    cur = conn.execute(
        """INSERT INTO rules(batch_id, source, rule_subject, category, object_type,
                             page_start, page_end, xlsx_path)
           VALUES (?,?,?,?,?,?,?,?)""",
        (batch_id, source, rule_subject, category, object_type, page_start, page_end, xlsx_path),
    )
    return cur.lastrowid


def replace_kp_for_rule(conn, rule_id: int) -> None:
    conn.execute("DELETE FROM knowledge_points WHERE rule_id = ?", (rule_id,))


def insert_kp(
    conn,
    rule_id: int,
    *,
    seq=None,
    subject_name=None,
    code_count=None,
    detection_logic=None,
    logic_basis=None,
    codes=None,
    remark=None,
    raw_row=None,
):
    cur = conn.execute(
        """INSERT INTO knowledge_points(rule_id, seq, subject_name, code_count,
                                        detection_logic, logic_basis, codes, remark, raw_row)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (rule_id, seq, subject_name, code_count, detection_logic, logic_basis, codes, remark, raw_row),
    )
    return cur.lastrowid


def insert_kp_codes(conn, kp_id: int, codes) -> int:
    """Bulk insert codes for a KP. codes is an iterable of strings; returns row count."""
    n = 0
    for i, c in enumerate(codes, start=1):
        c = (c or "").strip()
        if not c:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_point_codes(kp_id, code_seq, code) VALUES (?,?,?)",
            (kp_id, i, c),
        )
        n += 1
    return n


def get_kp_codes(conn, kp_id: int):
    return [r[0] for r in conn.execute(
        "SELECT code FROM knowledge_point_codes WHERE kp_id = ? ORDER BY code_seq",
        (kp_id,)).fetchall()]


import re as _re
_WS_RE = _re.compile(r"[\s\u3000]+")
def normalize_text(v):
    """Collapse all whitespace (incl. \r\n\t, full-width space \u3000) to nothing."""
    if v is None:
        return None
    s = str(v)
    s = _WS_RE.sub("", s)
    return s or None


def normalize_codes_join(codes):
    """Join a list of codes with the Chinese ideographic comma \u3001 (、
    ). FTS5 unicode61 treats it as a word boundary, so per-code search still works.
    """
    parts = [normalize_text(c) for c in codes or ()]
    parts = [p for p in parts if p]
    return "\u3001".join(parts)


def update_rule_row_count(conn, rule_id: int) -> int:
    n = conn.execute("SELECT COUNT(*) FROM knowledge_points WHERE rule_id = ?", (rule_id,)).fetchone()[0]
    conn.execute("UPDATE rules SET row_count = ? WHERE id = ?", (n, rule_id))
    return n


def count_kp(conn, source=None) -> int:
    if source:
        return conn.execute(
            """SELECT COUNT(*) FROM knowledge_points kp
               JOIN rules r ON r.id = kp.rule_id WHERE r.source = ?""",
            (source,),
        ).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]


def list_rule_subjects(conn, source=None):
    if source:
        rows = conn.execute(
            "SELECT DISTINCT rule_subject, source FROM rules WHERE source = ? ORDER BY rule_subject",
            (source,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT rule_subject, source FROM rules ORDER BY rule_subject").fetchall()
    return [(r[0], r[1]) for r in rows]
