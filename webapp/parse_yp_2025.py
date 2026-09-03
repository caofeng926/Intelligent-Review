# -*- coding: utf-8 -*-
"""2025 版国家医保药品目录 PDF 解析器

数据源: 原始数据/基本医保药品目录.pdf (202 页, 2026-07-06 维护)

5 个部分:
  凡例                          p1-7   (跳过)
  西药部分                      p9-82
  中成药部分                    p83-125
  协议期内谈判药品部分          p126-191
  中药饮片部分                  p192-202

列结构差异:
  西药       : 甲/乙 编号 名称 剂型 [备注]      (5 列, 部分缺备注)
  中成药     : 甲/乙 编号 名称 备注              (4 列, 剂型在名称括号内)
  谈判药品   : 乙  编号 名称 价格 备注 日期      (价格/日期跨行需合并)
  中药饮片   : 编号 名称 [备注]                  (双列布局)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

import pypdf


@dataclass
class Drug:
    list_no: str = ""
    name: str = ""
    category: str = ""
    list_class: str = ""
    category_code: str = ""
    category_name: str = ""
    dosage_form: str = ""
    payment_standard: str = ""
    payment_validity: str = ""
    remark: str = ""
    star_ref: str = ""
    page_no: int = 0

    def to_row(self) -> dict:
        return asdict(self)


# 顶层分类: XA / ZA (2 字符, 第二字符必须是大写字母)
RE_TOPCAT = re.compile(r"^([XZ][A-Z])\s+(.+)$")
# 子分类: XA01 / XA02BA / XA04C 等 (3-6 字符, 必须含数字)
RE_SUBCAT = re.compile(r"^([XZ][A-Z][0-9]{1,2}[A-Z]{0,3})\s+(.+)$")
RE_FOOTER = re.compile(r"^第\s*\d+\s*页\s*$")
RE_DRUG_HDR = re.compile(r"^([甲乙])\s+(?:(★\(\d+\))|(\d+))\s+(.+)$")
RE_DATE_RANGE = re.compile(
    r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*至\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
)
# 价格: 数字 + 元 + (单位) (用 search 不是 match, 因为 rest 可能含 name 前缀)
RE_PRICE = re.compile(r"(\d+(?:\.\d+)?\s*元.*?)\s+")

# 已知剂型 (凡例 + 历年目录统计)
DOSAGE_FORMS = (
    "口服常释剂型", "缓释控释剂型", "口服液体剂", "丸剂", "颗粒剂",
    "口服散剂", "外用散剂", "软膏剂", "贴剂", "外用液体剂", "硬膏剂",
    "凝胶剂", "涂剂", "栓剂", "滴眼剂", "滴耳剂", "滴鼻剂", "吸入剂",
    "注射剂", "注射用无菌粉末", "植入剂", "透析液", "洗剂", "涂膜剂",
    "膏剂", "糊剂", "膜剂", "棒剂", "海绵剂", "熨剂", "气雾剂", "喷雾剂",
    "粉雾剂", "滴丸剂", "糖浆剂", "合剂", "酊剂", "酒剂", "露剂",
    "茶剂", "锭剂", "曲剂", "胶囊剂", "片剂", "滴剂", "眼用制剂",
    "鼻用制剂", "耳用制剂", "口腔用制剂", "阴道用制剂", "直肠用制剂",
    "植入片", "植入棒", "灌肠剂", "含漱液", "冲洗剂",
    "搽剂", "油剂", "乳剂", "混悬剂", "乳膏剂", "凝胶膏剂",
    "巴布膏剂", "橡胶膏剂", "注射用乳剂", "注射用混悬剂",
    "注射用乳状液", "注射用溶液剂", "注射用微球", "注射用脂质体",
    "眼膏剂",
)
# set 用于 parse_drug_rest 快速查
DOSAGE_SET = set(DOSAGE_FORMS)
# 排序: 长 → 短 (避免短词先匹配)
DOSAGE_PATTERN = "|".join(
    re.escape(df) for df in sorted(DOSAGE_FORMS, key=len, reverse=True)
)
# 通用 drug_rest 解析: "name dosage_form [remark]"
RE_DRUG_REST = re.compile(rf"^(.+?)\s+({DOSAGE_PATTERN})(?:\s+(.+))?$")


def parse_drug_rest(rest: str, has_dosage_col: bool):
    """解析药品 rest 部分为 (name, dosage_form, remark).

    启发式:
      1. 从尾部扫描, 找以 "限" / "备注" 开头的 token 作 remark 起点
      2. 剩下的 tokens 中, 若最后 token 在 DOSAGE_FORMS 集合内 -> dosage_form
      3. 否则整段作 name (中成药剂型在 name 括号内时也走这条)

    has_dosage_col: 当前未使用 (中成药与西药共享启发式, 西药有时也缺剂型列).
    """
    _ = has_dosage_col
    rest = rest.strip()
    if not rest:
        return "", "", ""
    tokens = rest.split()
    if len(tokens) == 1:
        return tokens[0], "", ""
    # 1. 找 remark 起点
    remark_idx = None
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].startswith("限") or tokens[i].startswith("备注"):
            remark_idx = i
            break
    if remark_idx is not None:
        name_form_tokens = tokens[:remark_idx]
        remark_tokens = tokens[remark_idx:]
    else:
        name_form_tokens = tokens
        remark_tokens = []
    if not name_form_tokens:
        return "", "", " ".join(remark_tokens)
    # 2. 检查最后 token 是否是剂型
    if name_form_tokens[-1] in DOSAGE_SET:
        return (
            " ".join(name_form_tokens[:-1]),
            name_form_tokens[-1],
            " ".join(remark_tokens),
        )
    return " ".join(name_form_tokens), "", " ".join(remark_tokens)


def _classify_line(line: str):
    s = line.strip()
    if not s:
        return "blank", ""
    if RE_FOOTER.match(s):
        return "footer", ""
    headers = (
        "西药部分", "中成药部分", "协议期内谈判药品部分", "中药饮片部分",
        "（一）西药", "（一）中成药", "（一）基金予以支付的中药饮片",
    )
    if s in headers:
        return "header", s
    if s.startswith("（二") or s.startswith("(二") or "不得纳入基金支付" in s:
        return "header", s
    if RE_TOPCAT.match(s):
        return "topcat", s
    if RE_SUBCAT.match(s):
        return "subcat", s
    if RE_DRUG_HDR.match(s):
        return "drug_hdr", s
    return "other", s


def _parse_western_like(
    reader,
    *,
    category_label: str,
    page_start: int,
    page_end: int,
    has_dosage_col: bool,
) -> List[Drug]:
    drugs: List[Drug] = []
    cur_code = ""
    cur_cname = ""
    cur_class = ""
    cur_no = ""
    cur_name = ""
    cur_form = ""
    cur_remark_parts: List[str] = []
    in_drug = False
    cur_page = 0

    def flush():
        nonlocal in_drug, cur_name, cur_form, cur_remark_parts, cur_class, cur_no
        if not in_drug:
            return
        full_remark = " ".join(cur_remark_parts).strip()
        if cur_name:
            d = Drug(
                list_no=cur_no,
                name=cur_name.strip(),
                category=category_label,
                list_class=cur_class,
                category_code=cur_code,
                category_name=cur_cname,
                dosage_form=cur_form.strip(),
                remark=full_remark,
                page_no=cur_page,
            )
            if d.list_no.startswith("★("):
                m = re.match(r"★\((\d+)\)", d.list_no)
                if m:
                    d.star_ref = m.group(1)
                    d.list_no = f"★({m.group(1)})"
            drugs.append(d)
        cur_name = ""
        cur_form = ""
        cur_remark_parts = []
        cur_class = ""
        cur_no = ""
        in_drug = False

    for pidx in range(page_start, page_end):
        cur_page = pidx + 1
        text = reader.pages[pidx].extract_text() or ""
        for line in text.split("\n"):
            kind, body = _classify_line(line)
            if kind == "topcat":
                flush()
                m = RE_TOPCAT.match(body)
                cur_code, cur_cname = m.group(1), m.group(2).strip()
            elif kind == "subcat":
                flush()
                m = RE_SUBCAT.match(body)
                cur_code, cur_cname = m.group(1), m.group(2).strip()
            elif kind == "drug_hdr":
                flush()
                m = RE_DRUG_HDR.match(body)
                cur_class = m.group(1)
                cur_no = m.group(2) or m.group(3)
                cur_name, cur_form, cur_remark_parts = parse_drug_rest(
                    m.group(4), has_dosage_col
                )
                cur_remark_parts = [cur_remark_parts] if cur_remark_parts else []
                in_drug = True
            elif kind == "other":
                if in_drug:
                    cur_remark_parts.append(body)
        flush()

    return drugs


def parse_western(reader) -> List[Drug]:
    return _parse_western_like(
        reader, category_label="西药",
        page_start=8, page_end=82, has_dosage_col=True,
    )


def parse_tcm_patent(reader) -> List[Drug]:
    return _parse_western_like(
        reader, category_label="中成药",
        page_start=82, page_end=125, has_dosage_col=False,
    )




def _extract_price(text: str) -> str:
    """从 text 中找首个价格段.

    价格段: 从 "数字+元" 开始, 到 first " 至" / " 限" / " 备注" / 行尾.
    """
    m = re.search(r"\d+(?:\.\d+)?\s*元", text)
    if not m:
        return ""
    after = text[m.start():]
    stop = re.search(r"\s+(?:至|限|备注)", after)
    if stop:
        return after[:stop.start()].strip()
    return after.strip()

# 日期片段正则
RE_DATE_START_TO = re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*至\s*$")
RE_DATE_END = re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$")


def parse_negotiated(reader) -> List[Drug]:
    """谈判药品: 状态机扫描, 处理跨行日期和价格."""
    drugs: List[Drug] = []
    cur_code = ""
    cur_cname = ""
    cur_class = ""
    cur_no = ""
    cur_name = ""
    cur_price = ""
    cur_remark_parts: List[str] = []
    cur_validity_start = ""
    cur_validity_end = ""
    cur_validity_full = ""
    in_drug = False
    section = "谈判西药"
    cur_page = 0

    def flush():
        nonlocal in_drug, cur_name, cur_price, cur_remark_parts
        nonlocal cur_validity_start, cur_validity_end, cur_validity_full
        nonlocal cur_class, cur_no
        if not in_drug:
            return
        if cur_validity_full:
            validity = cur_validity_full
        elif cur_validity_start and cur_validity_end:
            validity = cur_validity_start + cur_validity_end
        else:
            validity = cur_validity_start or cur_validity_end
        full_remark = " ".join(cur_remark_parts).strip()
        d = Drug(
            list_no=cur_no,
            name=cur_name.strip(),
            category=section,
            list_class=cur_class,
            category_code=cur_code,
            category_name=cur_cname,
            payment_standard=cur_price.strip(),
            payment_validity=validity.strip(),
            remark=full_remark,
            page_no=cur_page,
        )
        if d.list_no.startswith("★("):
            m = re.match(r"★\((\d+)\)", d.list_no)
            if m:
                d.star_ref = m.group(1)
        drugs.append(d)
        cur_name = ""
        cur_price = ""
        cur_remark_parts = []
        cur_validity_start = ""
        cur_validity_end = ""
        cur_validity_full = ""
        cur_class = ""
        cur_no = ""
        in_drug = False

    for pidx in range(125, 191):
        cur_page = pidx + 1
        text = reader.pages[pidx].extract_text() or ""
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            if s in ("（一）西药", "(一)西药"):
                flush()
                section = "谈判西药"
                continue
            if s in ("（二）中成药", "(二)中成药"):
                flush()
                section = "谈判中成药"
                continue
            if s.startswith("协议期内") or s in ("药品分类", "药品分类代码"):
                continue
            if RE_FOOTER.match(s):
                flush()
                continue
            m_top = RE_TOPCAT.match(s)
            if m_top:
                flush()
                cur_code, cur_cname = m_top.group(1), m_top.group(2).strip()
                continue
            m_sub = RE_SUBCAT.match(s)
            if m_sub:
                flush()
                cur_code, cur_cname = m_sub.group(1), m_sub.group(2).strip()
                continue
            m_drug = RE_DRUG_HDR.match(s)
            if m_drug:
                flush()
                cur_class = m_drug.group(1)
                cur_no = m_drug.group(2) or m_drug.group(3)
                rest = m_drug.group(4).strip()
                # 1. 同行完整日期
                m_full = RE_DATE_RANGE.search(rest)
                if m_full:
                    cur_validity_full = f"{m_full.group(1)}至{m_full.group(2)}"
                    rest = (rest[:m_full.start()] + rest[m_full.end():]).strip()
                else:
                    cur_validity_full = ""
                # 2. 抽 name (first token)
                m_name = re.match(r"^(\S+)", rest)
                if m_name:
                    cur_name = m_name.group(1).strip()
                    rest = rest[m_name.end():].strip()
                else:
                    cur_name = rest
                    rest = ""
                # 3. 抽 price (到 stop pattern 前)
                cur_price = _extract_price(rest)
                if cur_price:
                    m_p = re.search(r"\d+(?:\.\d+)?\s*元", rest)
                    if m_p:
                        after = rest[m_p.start():]
                        stop = re.search(r"(?:至|限|；|;|备注)", after)
                        price_end = m_p.start() + (stop.start() if stop else len(after))
                        rest = (rest[:m_p.start()] + rest[price_end:]).strip()
                else:
                    cur_price = ""
                # 4. 检测 "X年X月X日至" 在 rest 末尾 (跨行日期开头)
                cur_remark_parts = [rest] if rest else []
                m_to = RE_DATE_START_TO.search(rest)
                if m_to:
                    cur_validity_start = m_to.group(1) + "至"
                    rest_after = (rest[:m_to.start()] + rest[m_to.end():]).strip()
                    cur_remark_parts = [rest_after] if rest_after else []
                in_drug = True
                continue
            # 续行
            if in_drug:
                if RE_DATE_END.match(s):
                    cur_validity_end = s
                elif RE_DATE_START_TO.match(s):
                    cur_validity_start = s
                elif RE_DATE_RANGE.search(s):
                    m_dr = RE_DATE_RANGE.search(s)
                    cur_validity_full = f"{m_dr.group(1)}至{m_dr.group(2)}"
                elif cur_price and cur_price.count("(") > cur_price.count(")"):
                    cur_price = cur_price + " " + s
                elif "元" in s and re.search(r"\d+(?:\.\d+)?\s*元", s):
                    cur_price = (cur_price + " " + s).strip() if cur_price else s
                else:
                    cur_remark_parts.append(s)

    flush()
    return drugs

def parse_herbal_pieces(reader) -> List[Drug]:
    """中药饮片: 双列布局 "1 一枝黄花 43 小茴香 □" → 拆为两行."""
    drugs: List[Drug] = []
    in_section = False
    cur_class = ""

    for pidx in range(191, 202):
        text = reader.pages[pidx].extract_text() or ""
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            if "（一）基金予以支付" in s or "(一)基金予以支付" in s:
                in_section = True
                cur_class = "中药饮片支付"
                continue
            if s.startswith("（二") or s.startswith("(二") or "不得纳入基金支付" in s:
                in_section = False
                cur_class = "中药饮片不得支付"
                drugs.append(Drug(
                    list_no="",
                    name=s,
                    category="中药饮片",
                    list_class=cur_class,
                    page_no=pidx + 1,
                    remark="原文逗号分隔, 不逐条拆分",
                ))
                continue
            if not in_section:
                continue
            if RE_FOOTER.match(s):
                continue
            # 双列布局: tokens 序列切成多个 (数字, 名称)
            tokens = s.split()
            i = 0
            while i < len(tokens):
                if tokens[i].isdigit():
                    no = tokens[i]
                    j = i + 1
                    while j < len(tokens) and not tokens[j].isdigit():
                        j += 1
                    name = " ".join(tokens[i + 1:j])
                    drugs.append(Drug(
                        list_no=no,
                        name=name,
                        category="中药饮片",
                        list_class=cur_class,
                        page_no=pidx + 1,
                    ))
                    i = j
                else:
                    i += 1

    return drugs



# 脱敏过滤: 价格保密药品的支付标准 + 备注
# 命中条件: remark 含 "价格保密"/"阶梯价格"/"阶梯单价"/"计算举例"
REDACTION_MARK = "[内容因企业申请价格保密已屏蔽]"

def _is_price_confidential(drug: "Drug") -> bool:
    r = drug.remark or ""
    return any(kw in r for kw in (
        "价格保密", "阶梯价格", "阶梯单价", "计算举例",
        "支付阶梯价格方案", "企业申请价格保密",
    ))


def sanitize_price_confidential(drugs: List["Drug"]) -> List["Drug"]:
    """对价格保密药品做脱敏: payment_standard -> '*', remark -> 屏蔽标记.
    payment_validity 是公开的协议有效期, 保留.
    与 NHSA 官方 PDF 中其他价格保密药品(如注射用全氟丙烷人血白蛋白微球)
    的处理方式一致 (payment_standard='*')."""
    n = 0
    for d in drugs:
        if _is_price_confidential(d):
            d.payment_standard = "*"
            d.remark = REDACTION_MARK
            n += 1
    if n:
        print(f"[sanitize] redacted {n} price-confidential drugs")
    return drugs

def parse_pdf(path) -> List[Drug]:
    path = Path(path)
    reader = pypdf.PdfReader(str(path))
    all_drugs: List[Drug] = []
    all_drugs.extend(parse_western(reader))
    all_drugs.extend(parse_tcm_patent(reader))
    all_drugs.extend(parse_negotiated(reader))
    all_drugs.extend(parse_herbal_pieces(reader))
    sanitize_price_confidential(all_drugs)
    return all_drugs


def stats(drugs: List[Drug]) -> dict:
    out = {"total": len(drugs), "by_category": {}, "by_class": {}}
    for d in drugs:
        out["by_category"].setdefault(d.category, 0)
        out["by_category"][d.category] += 1
        key = f"{d.category}/{d.list_class}"
        out["by_class"].setdefault(key, 0)
        out["by_class"][key] += 1
    return out


if __name__ == "__main__":
    import json
    import sys

    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\Workspace\医保智审规则库\原始数据\基本医保药品目录.pdf"
    )
    drugs = parse_pdf(pdf)
    print(json.dumps(stats(drugs), ensure_ascii=False, indent=2))
    print("---")
    print("样例 (西药):")
    for d in [x for x in drugs if x.category == "西药"][:5]:
        print(d.to_row())
    print("---")
    print("样例 (中成药):")
    for d in [x for x in drugs if x.category == "中成药"][:5]:
        print(d.to_row())