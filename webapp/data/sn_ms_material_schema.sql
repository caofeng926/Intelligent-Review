-- ============================================================
-- Shaanxi Medical Service Pricing 2021 -- Special Material Library
-- Source xlsx sheet '鏉愭枡搴?, 215 rows:
--   40 top-level categories (HC001-HC040, 5-char) carrying a
--   comma-separated composite description.
--   175 leaf items (HC00101-HC04003, 7-char) each naming a
--   specific consumable.  Bid code is left blank by the publisher
--   and is filled by institutions at procurement time.
-- ============================================================
CREATE TABLE IF NOT EXISTS sn_ms_material_codes (
    id              INTEGER PRIMARY KEY,
    code            TEXT    UNIQUE NOT NULL,
    p_code          TEXT,
    level           INTEGER NOT NULL,
    fin_class       TEXT,
    name            TEXT,
    bid_code        TEXT,
    sheet_name      TEXT,
    level_path      TEXT
);
CREATE INDEX IF NOT EXISTS idx_smm_code      ON sn_ms_material_codes(code);
CREATE INDEX IF NOT EXISTS idx_smm_pcode     ON sn_ms_material_codes(p_code);
CREATE INDEX IF NOT EXISTS idx_smm_level     ON sn_ms_material_codes(level);

CREATE VIRTUAL TABLE IF NOT EXISTS sn_ms_material_codes_fts USING fts5(
    code, name, bid_code,
    content='sn_ms_material_codes', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS sn_ms_material_ai AFTER INSERT ON sn_ms_material_codes BEGIN
    INSERT INTO sn_ms_material_codes_fts(rowid, code, name, bid_code)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.bid_code,''));
END;
CREATE TRIGGER IF NOT EXISTS sn_ms_material_ad AFTER DELETE ON sn_ms_material_codes BEGIN
    INSERT INTO sn_ms_material_codes_fts(sn_ms_material_codes_fts, rowid, code, name, bid_code)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.bid_code,''));
END;
CREATE TRIGGER IF NOT EXISTS sn_ms_material_au AFTER UPDATE ON sn_ms_material_codes BEGIN
    INSERT INTO sn_ms_material_codes_fts(sn_ms_material_codes_fts, rowid, code, name, bid_code)
    VALUES ('delete', old.id, old.code, COALESCE(old.name,''), COALESCE(old.bid_code,''));
    INSERT INTO sn_ms_material_codes_fts(rowid, code, name, bid_code)
    VALUES (new.id, new.code, COALESCE(new.name,''), COALESCE(new.bid_code,''));
END;