"""Shared helpers across webapp modules.

Use these instead of duplicating small functions in each module to
avoid circular-import resistance and keep behavior consistent.
"""

from __future__ import annotations

import json
from typing import Optional


def parse_kp_partner(
    raw_row: Optional[str], object_type: Optional[str]
) -> Optional[dict[str, str]]:
    """解出 KP 配对项目(药品↔项目 / 服务↔手术).

    Returns a {"name", "code", "label"} dict or None.
    """
    if not raw_row:
        return None
    try:
        d = json.loads(raw_row)
    except (TypeError, ValueError):
        return None
    if object_type == "pair":
        nb = (d.get("subject_name_b") or "").strip()
        cb = (d.get("codes_b") or "").strip()
        if nb or cb:
            return {"name": nb, "code": cb, "label": "配对项目"}
    if object_type == "service":
        row = d.get("row")
        if isinstance(row, list) and len(row) >= 3:
            code = str(row[1] or "").strip()
            name = str(row[2] or "").strip()
            if code or name:
                return {"name": name, "code": code, "label": "配对手术"}
    return None


# Shared label mapping for batch sources. Kept in sync between app.py
# and kp.py via this single source of truth.
SOURCE_LABEL: dict[str, str] = {
    "nhsa_batch": "NHSA 公告",
    "pdf_2025": "2025 版主册",
    "pdf_old": "2025 之前 PDF",
}


# 分页大小(用于 /search 与 /rules 等列表路由)
PAGE_SIZE = 20
