"""清理 drug_detail.manufacturer 字段 (PDF 解析边界错位修复).

可重复执行（幂等）:
  1) 加 manufacturer_raw 备份列（首次）
  2) 加 manufacturer_flag 标记列（首次）
  3) 截断 manufacturer 里的"国药准字..."/"869..."/"分号..."等混入内容
  4) 标记 ⚠混入规格 / ⚠过短 / ⚠过长 / ⚠空

用法:
  python -m webapp.clean_drug_detail            # 跑当前 DB
  python -m webapp.clean_drug_detail --db PATH  # 指定 DB 路径
"""
import argparse
import re
import sqlite3
import time


# 精确规格关键词 (LIKE 模式, 不依赖短字)
SPEC_KEYWORDS = [
    "PVC", "聚酯", "复合膜", "PE膜", "铝箔", "纸塑",
    "硬片", "塑料瓶", "瓶盖", "垫片", "固体药用", "中药丸",
    "浓缩丸", "蜜丸", "水丸", "安瓿", "小盒", "装盒",
    "压片", "糖衣片", "薄膜衣片", "分散片", "泡腾片", "肠溶片",
    "咀嚼片", "口含片", "舌下片", "贴片", "缓释片",
    "聚乙烯瓶", "聚丙烯瓶", "玻璃瓶",
]

# 末位 g/片/丸/袋/瓶/支 → 规格 (用 GLOB 末位匹配)
TAIL_UNIT_GLOBS = ["*[g片丸袋瓶支]"]

# 每 N 丸/片/袋/瓶/支/盒 → 规格
PER_UNIT_PATTERNS = [
    "%每_丸%", "%每_片%", "%每_袋%", "%每_瓶%", "%每_支%", "%每_盒%",
]

# 末位 PE/膜 → 规格
TAIL_PE_MEM = ["*PE", "*膜"]


def ensure_columns(c: sqlite3.Connection) -> None:
    cols = {r[1] for r in c.execute("PRAGMA table_info(drug_detail)").fetchall()}
    if "manufacturer_raw" not in cols:
        c.execute("ALTER TABLE drug_detail ADD COLUMN manufacturer_raw TEXT")
    if "manufacturer_flag" not in cols:
        c.execute("ALTER TABLE drug_detail ADD COLUMN manufacturer_flag TEXT")
    c.commit()


def backup_original(c: sqlite3.Connection) -> int:
    cur = c.execute(
        "UPDATE drug_detail SET manufacturer_raw = manufacturer WHERE manufacturer_raw IS NULL"
    )
    c.commit()
    return cur.rowcount


def truncate_guoyao(c: sqlite3.Connection) -> int:
    cur = c.execute(
        """
        UPDATE drug_detail
        SET manufacturer = rtrim(substr(manufacturer, 1, instr(manufacturer, '国药准字') - 1))
        WHERE instr(manufacturer, '国药准字') > 0
        """
    )
    c.commit()
    return cur.rowcount


def truncate_869(c: sqlite3.Connection) -> int:
    cur = c.execute(
        """
        UPDATE drug_detail
        SET manufacturer = rtrim(substr(manufacturer, 1, instr(manufacturer, '869') - 1))
        WHERE manufacturer LIKE '%869%'
          AND length(manufacturer) > 30
          AND manufacturer GLOB '869[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*'
        """
    )
    c.commit()
    return cur.rowcount


def truncate_punct(c: sqlite3.Connection) -> int:
    # 用 GLOB 模式列表（按顺序匹配首个出现的）
    # 仅使用明确作为"规格/多段"分隔符的标点
    # 不包括 : ( ) + - 等（公司名中常见, 误伤率高）
    puncts = [
        (";", ";"),              # 半角分号 - 规格/多公司分隔
        ("ï¼", "，"),  # 全角逗号
        (",", ","),              # 半角逗号
        ("ã", "。"),  # 全角句号
        ("/", "/"),              # 半角斜杠 - 包装/规格分隔
        ("ã", "、"),  # 顿号
        ("\n", "char(10)"),
        ("\r", "char(13)"),
    ]
    # 动态构造 SQL: 多个 WHEN 块
    when_clauses = []
    for lit, _ in puncts:
        esc_lit = lit.replace("'", "''")
        when_clauses.append(
            f"            WHEN instr(manufacturer, '{esc_lit}') > 0 "
            f"THEN substr(manufacturer, 1, instr(manufacturer, '{esc_lit}')-1)"
        )
    sql = (
        "UPDATE drug_detail\n"
        "        SET manufacturer = rtrim(\n"
        "          CASE\n"
        + "\n".join(when_clauses) + "\n"
        "            ELSE manufacturer END\n"
        "        )"
    )
    cur = c.execute(sql)
    c.commit()
    return cur.rowcount




def truncate_pages(c: sqlite3.Connection) -> int:
    """截断 PDF 残留: 第N页/共N页/页码编号"""
    cur = c.execute(
        """
        UPDATE drug_detail
        SET manufacturer = rtrim(
          CASE
            WHEN instr(manufacturer, '第') > 0
             AND instr(manufacturer, '页') > 0
             AND instr(manufacturer, '页') > instr(manufacturer, '第')
            THEN substr(manufacturer, 1, instr(manufacturer, '第') - 1)
            ELSE manufacturer END
        )
        """
    )
    c.commit()
    return cur.rowcount


# 折叠 CJK-空白-CJK (例如: "珠海联邦制药股份 有限公司" -> "珠海联邦制药股份有限公司").
# 防御性修复 — 2026-06-28 之后回归保护. 命中通常为 0.
_CJK = re.compile(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])")


def collapse_cjk_spaces(c: sqlite3.Connection) -> int:
    """移除 CJK 字符之间的空白."""
    rows = c.execute("SELECT goods_code, manufacturer FROM drug_detail WHERE manufacturer LIKE '% %'").fetchall()
    if not rows:
        return 0
    fixed = 0
    BATCH = 500
    buf: list[tuple[str, int]] = []
    for rid, mfr in rows:
        if not mfr:
            continue
        new_mfr = _CJK.sub(r"\1\2", mfr).strip()
        if new_mfr != mfr:
            buf.append((new_mfr, rid))
            fixed += 1
            if len(buf) >= BATCH:
                c.executemany("UPDATE drug_detail SET manufacturer=? WHERE goods_code=?", buf)
                buf.clear()
    if buf:
        c.executemany("UPDATE drug_detail SET manufacturer=? WHERE goods_code=?", buf)
    c.commit()
    return fixed


def tag_suspicious(c: sqlite3.Connection) -> dict:
    counts = {}
    # 先清空
    c.execute("UPDATE drug_detail SET manufacturer_flag = NULL")
    # ⚠空
    cur = c.execute(
        "UPDATE drug_detail SET manufacturer_flag='⚠空' "
        "WHERE manufacturer IS NULL OR trim(manufacturer) = ''"
    )
    counts["⚠空"] = cur.rowcount
    # ⚠过短
    cur = c.execute(
        "UPDATE drug_detail SET manufacturer_flag='⚠过短' "
        "WHERE manufacturer_flag IS NULL AND length(trim(manufacturer)) < 3"
    )
    counts["⚠过短"] = cur.rowcount
    # ⚠过长 (>50 字符, 中外合资长名可放过)
    cur = c.execute(
        "UPDATE drug_detail SET manufacturer_flag='⚠过长' "
        "WHERE manufacturer_flag IS NULL AND length(trim(manufacturer)) > 50"
    )
    counts["⚠过长"] = cur.rowcount
    # 末位 g/片/丸/袋/瓶/支
    cur = c.execute(
        "UPDATE drug_detail SET manufacturer_flag='⚠混入规格' "
        "WHERE manufacturer_flag IS NULL AND trim(manufacturer) GLOB '*[g片丸袋瓶支]'"
    )
    counts["⚠末位单位"] = cur.rowcount
    # 每 N 单位
    sub = 0
    for pat in PER_UNIT_PATTERNS:
        sub += c.execute(
            "UPDATE drug_detail SET manufacturer_flag='⚠混入规格' "
            "WHERE manufacturer_flag IS NULL AND manufacturer LIKE ?",
            (pat,),
        ).rowcount
    counts["⚠每N单位"] = sub
    # 末位 PE/膜
    sub = 0
    for g in TAIL_PE_MEM:
        sub += c.execute(
            "UPDATE drug_detail SET manufacturer_flag='⚠混入规格' "
            "WHERE manufacturer_flag IS NULL AND trim(manufacturer) GLOB ?",
            (g,),
        ).rowcount
    counts["⚠末位PE"] = sub
    # 精确关键词
    sub = 0
    for kw in SPEC_KEYWORDS:
        sub += c.execute(
            "UPDATE drug_detail SET manufacturer_flag='⚠混入规格' "
            "WHERE manufacturer_flag IS NULL AND manufacturer LIKE ?",
            (f"%{kw}%",),
        ).rowcount
    counts["⚠精确关键词"] = sub
    c.commit()
    return counts


def report(c: sqlite3.Connection) -> list:
    rows = c.execute(
        "SELECT COALESCE(manufacturer_flag,'✓干净') AS flag, COUNT(*) "
        "FROM drug_detail GROUP BY flag ORDER BY 2 DESC"
    ).fetchall()
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--db",
        default=None,
        help="SQLite DB 路径 (默认用 webapp/data/kp.db)",
    )
    args = p.parse_args()

    if args.db:
        db_path = args.db
    else:
        from .db import DB_PATH
        db_path = DB_PATH

    print(f"DB: {db_path}")
    c = sqlite3.connect(db_path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-200000")

    t0 = time.time()
    ensure_columns(c)
    print(f"  [1] 列已就绪       ({time.time()-t0:.1f}s)")

    n = backup_original(c)
    print(f"  [2] 备份原始 manufacturer: {n:,} 行  ({time.time()-t0:.1f}s)")

    # 重置 manufacturer 到 raw (使脚本可重复执行)
    n = c.execute("UPDATE drug_detail SET manufacturer = manufacturer_raw").rowcount
    c.commit()
    print(f"  [3] 重置 manufacturer=raw: {n:,} 行  ({time.time()-t0:.1f}s)")

    n = truncate_guoyao(c)
    print(f"  [4] 截'国药准字'之前:    {n:>6,} 行  ({time.time()-t0:.1f}s)")

    n = truncate_869(c)
    print(f"  [5] 截'869...'之前:      {n:>6,} 行  ({time.time()-t0:.1f}s)")

    n = truncate_punct(c)
    print(f"  [6] 截首段标点:          {n:>6,} 行  ({time.time()-t0:.1f}s)")

    n = truncate_pages(c)
    print(f"  [7] 截第N页/共N页:        {n:>6,} 行  ({time.time()-t0:.1f}s)")

    n = collapse_cjk_spaces(c)
    print(f"  [7.5] 折叠 CJK 间空白:    {n:>6,} 行  ({time.time()-t0:.1f}s)")

    tag_suspicious(c)
    print(f"  [8] 标记完成            ({time.time()-t0:.1f}s)")

    print("\n=== 清洗结果分布 ===")
    total = 0
    for flag, n in report(c):
        total += n
        print(f"  {flag:<10}  {n:>7,}")
    print(f"  {'─'*30}")
    print(f"  {'总计':<10}  {total:>7,}")
    print(f"\n完成 ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()

