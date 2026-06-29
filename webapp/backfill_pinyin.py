"""Backfill pinyin_initials column for all knowledge_points."""
from __future__ import annotations
import re
import sqlite3
from pypinyin import lazy_pinyin, Style

from . import db


def make_initials(text: str) -> str | None:
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    # 纯非中文 / 纯数字 / 纯符号 -> None (不被索引)
    if not re.search(r"[\u4e00-\u9fff]", text):
        return None
    try:
        s = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER, errors=lambda x: [c for c in x]))
    except Exception:
        return None
    s = s.lower()
    # 去掉非字母
    s = re.sub(r"[^a-z]", "", s)
    return s or None


def main():
    n = 0
    with db.connect() as conn:
        for sid, subj in conn.execute("SELECT id, subject_name FROM knowledge_points"):
            initials = make_initials(subj or "")
            if initials is not None or subj is None or subj == "":
                conn.execute("UPDATE knowledge_points SET pinyin_initials = ? WHERE id = ?", (initials, sid))
                n += 1
    print(f"backfilled {n} rows")


if __name__ == "__main__":
    main()
