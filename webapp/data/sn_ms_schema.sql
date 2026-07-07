
-- ============================================================
-- Shaanxi Medical Service Pricing 2021 edition (SN-MS)
-- Source xlsx: 8 sheets, encoding levels by digit count
--   L1=sheet_name, L2=2-digit, L3=4-digit, L4=6-digit, L5=9-digit (+ optional a/b suffix)
-- ============================================================
CREATE TABLE IF NOT EXISTS sn_ms_codes (
    id              INTEGER PRIMARY KEY,
    code            TEXT    UNIQUE NOT NULL,
    p_code          TEXT,
    name            TEXT,
    level           INTEGER NOT NULL,
    sheet_name      TEXT    NOT NULL,
    sheet_title     TEXT    NOT NULL,
    level_path      TEXT,
    fin_class       TEXT,
    unit            TEXT,
    price_l1        TEXT,
    price_l2        TEXT,
    price_l3        TEXT,
    content         TEXT,
    exclude         TEXT,
    remark          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sn_ms_code      ON sn_ms_codes(code);
CREATE INDEX IF NOT EXISTS idx_sn_ms_pcode     ON sn_ms_codes(p_code);
CREATE INDEX IF NOT EXISTS idx_sn_ms_level     ON sn_ms_codes(level);
CREATE INDEX IF NOT EXISTS idx_sn_ms_sheet     ON sn_ms_codes(sheet_name);

CREATE VIRTUAL TABLE IF NOT EXISTS sn_ms_codes_fts USING fts5(
    code, name, content, exclude, remark,
    content='sn_ms_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS sn_ms_ai AFTER INSERT ON sn_ms_codes BEGIN
    INSERT INTO sn_ms_codes_fts(rowid, code, name, content, exclude, remark)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.content,''),
        COALESCE(new.exclude,''), COALESCE(new.remark,''));
END;
CREATE TRIGGER IF NOT EXISTS sn_ms_ad AFTER DELETE ON sn_ms_codes BEGIN
    INSERT INTO sn_ms_codes_fts(sn_ms_codes_fts, rowid, code, name, content, exclude, remark)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.content,''),
        COALESCE(old.exclude,''), COALESCE(old.remark,''));
END;
CREATE TRIGGER IF NOT EXISTS sn_ms_au AFTER UPDATE ON sn_ms_codes BEGIN
    INSERT INTO sn_ms_codes_fts(sn_ms_codes_fts, rowid, code, name, content, exclude, remark)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.content,''),
        COALESCE(old.exclude,''), COALESCE(old.remark,''));
    INSERT INTO sn_ms_codes_fts(rowid, code, name, content, exclude, remark)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.content,''),
        COALESCE(new.exclude,''), COALESCE(new.remark,''));
END;

