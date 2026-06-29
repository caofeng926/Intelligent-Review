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
-- and link back via seq (瀵瑰簲鐭ヨ瘑鐐瑰簭鍙?.
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

-- ============================================================
-- 鍖荤敤鑰楁潗浠ｇ爜搴?(from NHSA consumables PDF, May 2026 update)
-- ============================================================
CREATE TABLE IF NOT EXISTS consumable_codes (
    id                INTEGER PRIMARY KEY,
    code              TEXT    UNIQUE NOT NULL,
    cat_l1            TEXT,
    cat_l1_name       TEXT,
    cat_l2            TEXT,
    cat_l2_name       TEXT,
    cat_l3            TEXT,
    cat_l3_name       TEXT,
    generic_category  TEXT,
    material          TEXT,
    spec              TEXT,
    generic_no        TEXT,
    generic_name      TEXT,
    manufacturer      TEXT
);
CREATE INDEX IF NOT EXISTS idx_cc_l1      ON consumable_codes(cat_l1);
CREATE INDEX IF NOT EXISTS idx_cc_l2      ON consumable_codes(cat_l1, cat_l2);
CREATE INDEX IF NOT EXISTS idx_cc_l3      ON consumable_codes(cat_l1, cat_l2, cat_l3);
CREATE INDEX IF NOT EXISTS idx_cc_generic ON consumable_codes(generic_no);
CREATE INDEX IF NOT EXISTS idx_cc_mfr     ON consumable_codes(manufacturer);

CREATE VIRTUAL TABLE IF NOT EXISTS consumable_codes_fts USING fts5(
    code, generic_name, manufacturer, generic_no,
    cat_l1_name, cat_l2_name, cat_l3_name,
    content='consumable_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS cc_ai AFTER INSERT ON consumable_codes BEGIN
    INSERT INTO consumable_codes_fts(rowid, code, generic_name, manufacturer, generic_no,
                                      cat_l1_name, cat_l2_name, cat_l3_name)
    VALUES (new.id, COALESCE(new.code,''), COALESCE(new.generic_name,''),
            COALESCE(new.manufacturer,''), COALESCE(new.generic_no,''),
            COALESCE(new.cat_l1_name,''), COALESCE(new.cat_l2_name,''),
            COALESCE(new.cat_l3_name,''));
END;
CREATE TRIGGER IF NOT EXISTS cc_ad AFTER DELETE ON consumable_codes BEGIN
    INSERT INTO consumable_codes_fts(consumable_codes_fts, rowid, code, generic_name, manufacturer, generic_no,
                                      cat_l1_name, cat_l2_name, cat_l3_name)
    VALUES ('delete', old.id, COALESCE(old.code,''), COALESCE(old.generic_name,''),
            COALESCE(old.manufacturer,''), COALESCE(old.generic_no,''),
            COALESCE(old.cat_l1_name,''), COALESCE(old.cat_l2_name,''),
            COALESCE(old.cat_l3_name,''));
END;
CREATE TRIGGER IF NOT EXISTS cc_au AFTER UPDATE ON consumable_codes BEGIN
    INSERT INTO consumable_codes_fts(consumable_codes_fts, rowid, code, generic_name, manufacturer, generic_no,
                                      cat_l1_name, cat_l2_name, cat_l3_name)
    VALUES ('delete', old.id, COALESCE(old.code,''), COALESCE(old.generic_name,''),
            COALESCE(old.manufacturer,''), COALESCE(old.generic_no,''),
            COALESCE(old.cat_l1_name,''), COALESCE(old.cat_l2_name,''),
            COALESCE(old.cat_l3_name,''));
    INSERT INTO consumable_codes_fts(rowid, code, generic_name, manufacturer, generic_no,
                                      cat_l1_name, cat_l2_name, cat_l3_name)
    VALUES (new.id, COALESCE(new.code,''), COALESCE(new.generic_name,''),
            COALESCE(new.manufacturer,''), COALESCE(new.generic_no,''),
            COALESCE(new.cat_l1_name,''), COALESCE(new.cat_l2_name,''),
            COALESCE(new.cat_l3_name,''));
END;

-- 涓€绾р啋浜岀骇鈫掍笁绾?鍒嗙被鑱氬悎瑙嗗浘
CREATE VIEW IF NOT EXISTS consumable_categories AS
SELECT
    cat_l1, cat_l1_name,
    cat_l2, cat_l2_name,
    cat_l3, cat_l3_name,
    COUNT(*) AS code_count
FROM consumable_codes
WHERE cat_l1 IS NOT NULL
GROUP BY cat_l1, cat_l2, cat_l3;
"""


# drug_detail.manufacturer 瀛楁璇存槑
# - manufacturer:        娓呮礂鍚庣殑鍊硷紙宸叉埅鏂?鍥借嵂鍑嗗瓧/869/鍒嗗彿/绗琋椤?绛夋贩鍏ュ唴瀹癸級
# - manufacturer_raw:    鍘熷鍊硷紙PDF 瑙ｆ瀽鐨勫垵娆＄粨鏋滐紝澶囦唤鐢級
# - manufacturer_flag:   鏍囪鍒楋紙NULL=鉁撳共鍑€, 鈿犵┖, 鈿犺繃鐭? 鈿犺繃闀? 鈿犳贩鍏ヨ鏍硷級
# 閲嶆柊鎵ц娓呮礂: python -m webapp.clean_drug_detail


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
    import re as _re_init
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        parts = _re_init.split(r"(?=CREATE TABLE IF NOT EXISTS|CREATE VIRTUAL TABLE IF NOT EXISTS|CREATE TRIGGER IF NOT EXISTS|CREATE INDEX IF NOT EXISTS)", EXTRA_SCHEMA + NHSA_BATCH_SCHEMA)
        for p in parts:
            p = p.strip()
            if not p: continue
            try: conn.executescript(p)
            except: pass


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
    """Join a list of codes with the Chinese ideographic comma \u3001 (銆?
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


# ============================================================
# 婢堆勶拷璇茬€悰灞肩炊閹貉嗙槚妤犲矁锟芥槒銆冮敍鍫濇儕閻滐拷2026-06-28 閼惧嘲褰囬敍?
# ============================================================
EXTRA_SCHEMA = r"""
-- 娴ｆ捇鍎犵拠濠冩焽鐠囨洖澧忛崚鍡欒娑撳簼鍞惍?IVD)
CREATE TABLE IF NOT EXISTS ivd_codes (
    id                    INTEGER PRIMARY KEY,
    code                  TEXT    UNIQUE NOT NULL,
    cat_l1                TEXT,
    cat_l1_name           TEXT,
    cat_l2                TEXT,
    cat_l2_name           TEXT,
    cat_l3                TEXT,
    cat_l3_name           TEXT,
    testing_category      TEXT,
    testing_index         TEXT,
    use_type              TEXT,
    check_type            TEXT,
    company_name          TEXT,
    business_license      TEXT,
    spec_code             TEXT,
    catalog_full_name     TEXT
);
CREATE INDEX IF NOT EXISTS idx_ivd_l1 ON ivd_codes(cat_l1);
CREATE INDEX IF NOT EXISTS idx_ivd_l2 ON ivd_codes(cat_l1, cat_l2);
CREATE INDEX IF NOT EXISTS idx_ivd_l3 ON ivd_codes(cat_l1, cat_l2, cat_l3);
CREATE INDEX IF NOT EXISTS idx_ivd_test ON ivd_codes(testing_category);
CREATE INDEX IF NOT EXISTS idx_ivd_company ON ivd_codes(company_name);

CREATE VIRTUAL TABLE IF NOT EXISTS ivd_codes_fts USING fts5(
    code, cat_l1_name, cat_l2_name, cat_l3_name, testing_category,
    testing_index, company_name,
    content='ivd_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS ivd_ai AFTER INSERT ON ivd_codes BEGIN
    INSERT INTO ivd_codes_fts(rowid, code, cat_l1_name, cat_l2_name, cat_l3_name,
        testing_category, testing_index, company_name)
    VALUES (new.id, new.code, COALESCE(new.cat_l1_name,''), COALESCE(new.cat_l2_name,''),
        COALESCE(new.cat_l3_name,''), COALESCE(new.testing_category,''),
        COALESCE(new.testing_index,''), COALESCE(new.company_name,''));
END;
CREATE TRIGGER IF NOT EXISTS ivd_ad AFTER DELETE ON ivd_codes BEGIN
    INSERT INTO ivd_codes_fts(ivd_codes_fts, rowid, code, cat_l1_name, cat_l2_name, cat_l3_name,
        testing_category, testing_index, company_name)
    VALUES ('delete', old.id, old.code, COALESCE(old.cat_l1_name,''), COALESCE(old.cat_l2_name,''),
        COALESCE(old.cat_l3_name,''), COALESCE(old.testing_category,''),
        COALESCE(old.testing_index,''), COALESCE(old.company_name,''));
END;
CREATE TRIGGER IF NOT EXISTS ivd_au AFTER UPDATE ON ivd_codes BEGIN
    INSERT INTO ivd_codes_fts(ivd_codes_fts, rowid, code, cat_l1_name, cat_l2_name, cat_l3_name,
        testing_category, testing_index, company_name)
    VALUES ('delete', old.id, old.code, COALESCE(old.cat_l1_name,''), COALESCE(old.cat_l2_name,''),
        COALESCE(old.cat_l3_name,''), COALESCE(old.testing_category,''),
        COALESCE(old.testing_index,''), COALESCE(old.company_name,''));
    INSERT INTO ivd_codes_fts(rowid, code, cat_l1_name, cat_l2_name, cat_l3_name,
        testing_category, testing_index, company_name)
    VALUES (new.id, new.code, COALESCE(new.cat_l1_name,''), COALESCE(new.cat_l2_name,''),
        COALESCE(new.cat_l3_name,''), COALESCE(new.testing_category,''),
        COALESCE(new.testing_index,''), COALESCE(new.company_name,''));
END;

-- 鐞涳拷7 缁灏伴悽銊︼拷鎰拷鎰閸掑棛琚稉搴濆敩閻?HC7)
CREATE TABLE IF NOT EXISTS consumable7_codes (
    id                INTEGER PRIMARY KEY,
    code              TEXT    UNIQUE NOT NULL,
    cat_l1            TEXT,    cat_l1_name       TEXT,
    cat_l2            TEXT,    cat_l2_name       TEXT,
    cat_l3            TEXT,    cat_l3_name       TEXT,
    generic_category  TEXT,
    material          TEXT,
    spec              TEXT,
    generic_no        TEXT,
    generic_name      TEXT,
    manufacturer      TEXT
);
CREATE INDEX IF NOT EXISTS idx_cc7_l1 ON consumable7_codes(cat_l1);
CREATE INDEX IF NOT EXISTS idx_cc7_l2 ON consumable7_codes(cat_l1, cat_l2);
CREATE INDEX IF NOT EXISTS idx_cc7_l3 ON consumable7_codes(cat_l1, cat_l2, cat_l3);

-- ICD-10 閸栨槒锟?.0 閻楀牆灏版穱婵嗗鞍閻ｆ瑥灏伴惀鍛嫲閹垮秴宸?CREATE TABLE IF NOT EXISTS icd_codes (
    id               INTEGER PRIMARY KEY,
    code             TEXT    UNIQUE NOT NULL,
    chapter_no       TEXT,
    chapter_range    TEXT,
    chapter_name     TEXT,
    section_range    TEXT,
    section_name     TEXT,
    category_code    TEXT,
    category_name    TEXT,
    subcategory_code TEXT,
    subcategory_name TEXT,
    diagnosis_code   TEXT,
    diagnosis_name   TEXT
);
CREATE INDEX IF NOT EXISTS idx_icd_chap ON icd_codes(chapter_no);
CREATE INDEX IF NOT EXISTS idx_icd_cat ON icd_codes(category_code);
CREATE INDEX IF NOT EXISTS idx_icd_sub ON icd_codes(subcategory_code);
CREATE INDEX IF NOT EXISTS idx_icd_diag ON icd_codes(diagnosis_code);

CREATE VIRTUAL TABLE IF NOT EXISTS icd_codes_fts USING fts5(
    code, chapter_name, section_name, category_name, subcategory_name, diagnosis_name,
    content='icd_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS icd_ai AFTER INSERT ON icd_codes BEGIN
    INSERT INTO icd_codes_fts(rowid, code, chapter_name, section_name, category_name,
        subcategory_name, diagnosis_name)
    VALUES (new.id, new.code, COALESCE(new.chapter_name,''), COALESCE(new.section_name,''),
        COALESCE(new.category_name,''), COALESCE(new.subcategory_name,''),
        COALESCE(new.diagnosis_name,''));
END;
CREATE TRIGGER IF NOT EXISTS icd_ad AFTER DELETE ON icd_codes BEGIN
    INSERT INTO icd_codes_fts(icd_codes_fts, rowid, code, chapter_name, section_name, category_name,
        subcategory_name, diagnosis_name)
    VALUES ('delete', old.id, old.code, COALESCE(old.chapter_name,''), COALESCE(old.section_name,''),
        COALESCE(old.category_name,''), COALESCE(old.subcategory_name,''),
        COALESCE(old.diagnosis_name,''));
END;
CREATE TRIGGER IF NOT EXISTS icd_au AFTER UPDATE ON icd_codes BEGIN
    INSERT INTO icd_codes_fts(icd_codes_fts, rowid, code, chapter_name, section_name, category_name,
        subcategory_name, diagnosis_name)
    VALUES ('delete', old.id, old.code, COALESCE(old.chapter_name,''), COALESCE(old.section_name,''),
        COALESCE(old.category_name,''), COALESCE(old.subcategory_name,''),
        COALESCE(old.diagnosis_name,''));
    INSERT INTO icd_codes_fts(rowid, code, chapter_name, section_name, category_name,
        subcategory_name, diagnosis_name)
    VALUES (new.id, new.code, COALESCE(new.chapter_name,''), COALESCE(new.section_name,''),
        COALESCE(new.category_name,''), COALESCE(new.subcategory_name,''),
        COALESCE(new.diagnosis_name,''));
END;

-- 閸忋劌娴楅崠鑽ゆ灍閺堝秴濮熸い鍦窗
CREATE TABLE IF NOT EXISTS medical_service_codes (
    id              INTEGER PRIMARY KEY,
    code            TEXT    UNIQUE NOT NULL,
    p_code          TEXT,
    name            TEXT,
    level           INTEGER,
    level_path      TEXT,
    pinyin_code     TEXT,
    contains_content TEXT,
    excluded_content TEXT,
    charge_unit     TEXT,
    explain         TEXT,
    area            TEXT,
    is_using        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ms_code ON medical_service_codes(code);
CREATE INDEX IF NOT EXISTS idx_ms_pcode ON medical_service_codes(p_code);
CREATE INDEX IF NOT EXISTS idx_ms_level ON medical_service_codes(level);

CREATE VIRTUAL TABLE IF NOT EXISTS medical_service_codes_fts USING fts5(
    code, name, explain, contains_content, excluded_content,
    content='medical_service_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS ms_ai AFTER INSERT ON medical_service_codes BEGIN
    INSERT INTO medical_service_codes_fts(rowid, code, name, explain, contains_content, excluded_content)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.explain,''),
        COALESCE(new.contains_content,''), COALESCE(new.excluded_content,''));
END;
CREATE TRIGGER IF NOT EXISTS ms_ad AFTER DELETE ON medical_service_codes BEGIN
    INSERT INTO medical_service_codes_fts(medical_service_codes_fts, rowid, code, name, explain, contains_content, excluded_content)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.explain,''),
        COALESCE(old.contains_content,''), COALESCE(old.excluded_content,''));
END;
CREATE TRIGGER IF NOT EXISTS ms_au AFTER UPDATE ON medical_service_codes BEGIN
    INSERT INTO medical_service_codes_fts(medical_service_codes_fts, rowid, code, name, explain, contains_content, excluded_content)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.explain,''),
        COALESCE(old.contains_content,''), COALESCE(old.excluded_content,''));
    INSERT INTO medical_service_codes_fts(rowid, code, name, explain, contains_content, excluded_content)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.explain,''),
        COALESCE(new.contains_content,''), COALESCE(new.excluded_content,''));
END;

-- 娑撹弓鑵戦崠鑽ゆ⒕/鐠囦椒绶?2.0 閻楋拷
CREATE TABLE IF NOT EXISTS tcm_codes (
    id              INTEGER PRIMARY KEY,
    code            TEXT    UNIQUE NOT NULL,
    p_code          TEXT,
    name            TEXT,
    part_code       TEXT,
    code_length     INTEGER,
    level           INTEGER,
    apply_explain   TEXT,
    remark          TEXT,
    class_code      TEXT,
    class_name      TEXT
);
CREATE INDEX IF NOT EXISTS idx_tcm_code ON tcm_codes(code);
CREATE INDEX IF NOT EXISTS idx_tcm_pcode ON tcm_codes(p_code);

CREATE VIRTUAL TABLE IF NOT EXISTS tcm_codes_fts USING fts5(
    code, name, class_name, apply_explain, remark,
    content='tcm_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS tcm_ai AFTER INSERT ON tcm_codes BEGIN
    INSERT INTO tcm_codes_fts(rowid, code, name, class_name, apply_explain, remark)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.class_name,''),
        COALESCE(new.apply_explain,''), COALESCE(new.remark,''));
END;
CREATE TRIGGER IF NOT EXISTS tcm_ad AFTER DELETE ON tcm_codes BEGIN
    INSERT INTO tcm_codes_fts(tcm_codes_fts, rowid, code, name, class_name, apply_explain, remark)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.class_name,''),
        COALESCE(old.apply_explain,''), COALESCE(old.remark,''));
END;
CREATE TRIGGER IF NOT EXISTS tcm_au AFTER UPDATE ON tcm_codes BEGIN
    INSERT INTO tcm_codes_fts(tcm_codes_fts, rowid, code, name, class_name, apply_explain, remark)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.class_name,''),
        COALESCE(old.apply_explain,''), COALESCE(old.remark,''));
    INSERT INTO tcm_codes_fts(rowid, code, name, class_name, apply_explain, remark)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.class_name,''),
        COALESCE(new.apply_explain,''), COALESCE(new.remark,''));
END;
"""

# batch metadata table for reference data (NHSA standard databases)
NHSA_BATCH_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS nhsa_batches (
    source        TEXT PRIMARY KEY,
    batch_label   TEXT NOT NULL,
    pub_date      TEXT,
    ann_url       TEXT,
    pdf_path      TEXT,
    csv_path      TEXT,
    json_path     TEXT,
    record_count  INTEGER,
    sysflag       TEXT,
    ingested_at   TEXT
);
"""

SCHEMA_FULL = SCHEMA + EXTRA_SCHEMA + NHSA_BATCH_SCHEMA


