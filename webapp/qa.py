"""Cross-source QA: 1-15 batch XLSX vs 2025 PDF."""
from __future__ import annotations
import os
import json
import difflib
from collections import defaultdict

from . import db


def norm(s: str) -> str:
    """Strip entity-type prefixes for fuzzy rule_subject matching."""
    if not s:
        return ""
    for p in ("医疗服务项目", "医用耗材", "中药饮片", "耗材", "药品"):
        if s.startswith(p):
            return s[len(p):]
    return s


def main():
    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "db_path": db.DB_PATH,
        "totals": {},
        "coverage": {},
        "per_rule": [],
        "sample_similarity": {},
    }

    with db.connect() as conn:
        # totals
        for src in ("nhsa_batch", "pdf_2025"):
            report["totals"][src] = {
                "rules": conn.execute("SELECT count(*) FROM rules WHERE source = ?", (src,)).fetchone()[0],
                "knowledge_points": conn.execute(
                    "SELECT count(*) FROM knowledge_points kp JOIN rules r ON r.id = kp.rule_id WHERE r.source = ?",
                    (src,),
                ).fetchone()[0],
            }
        report["totals"]["combined"] = {
            "rules": conn.execute("SELECT count(*) FROM rules").fetchone()[0],
            "knowledge_points": conn.execute("SELECT count(*) FROM knowledge_points").fetchone()[0],
        }

        # subject sets
        xlsx_subs = set(r[0] for r in conn.execute(
            "SELECT DISTINCT rule_subject FROM rules WHERE source='nhsa_batch'"
        ).fetchall())
        pdf_subs = set(r[0] for r in conn.execute(
            "SELECT DISTINCT rule_subject FROM rules WHERE source='pdf_2025'"
        ).fetchall())

        xlsx_norm = {norm(s) for s in xlsx_subs}
        pdf_norm = {norm(s) for s in pdf_subs}

        exact_intersect = xlsx_subs & pdf_subs
        fuzzy_intersect = xlsx_norm & pdf_norm

        report["coverage"] = {
            "xlsx_rule_count": len(xlsx_subs),
            "pdf_rule_count": len(pdf_subs),
            "exact_intersect": sorted(exact_intersect),
            "exact_intersect_count": len(exact_intersect),
            "fuzzy_intersect_count": len(fuzzy_intersect),
            "only_in_xlsx": sorted(xlsx_subs - pdf_subs),
            "only_in_pdf": sorted(pdf_subs - xlsx_subs),
        }

        # per-rule row counts comparison (for fuzzy intersections)
        xlsx_rows_by_subj = dict(conn.execute(
            """SELECT rule_subject, SUM(row_count) FROM rules WHERE source='nhsa_batch' GROUP BY rule_subject"""
        ).fetchall())
        pdf_rows_by_subj = dict(conn.execute(
            """SELECT rule_subject, SUM(row_count) FROM rules WHERE source='pdf_2025' GROUP BY rule_subject"""
        ).fetchall())
        for s in sorted(fuzzy_intersect):
            # find a representative raw subject in each side
            x_raw = next((x for x in xlsx_subs if norm(x) == s), None)
            p_raw = next((x for x in pdf_subs if norm(x) == s), None)
            report["per_rule"].append({
                "normalized": s,
                "xlsx_subject": x_raw,
                "pdf_subject": p_raw,
                "xlsx_kp": xlsx_rows_by_subj.get(x_raw, 0),
                "pdf_kp": pdf_rows_by_subj.get(p_raw, 0),
            })

        # sample similarity: for each fuzzy_intersect, sample 5 from each side
        sim_scores = []
        for s in sorted(fuzzy_intersect):
            x_raw = next((x for x in xlsx_subs if norm(x) == s), None)
            p_raw = next((x for x in pdf_subs if norm(x) == s), None)
            if not (x_raw and p_raw):
                continue
            x_samples = conn.execute(
                """SELECT subject_name, detection_logic FROM knowledge_points kp
                   JOIN rules r ON r.id = kp.rule_id
                   WHERE r.source='nhsa_batch' AND r.rule_subject = ? AND subject_name IS NOT NULL
                   LIMIT 5""", (x_raw,),
            ).fetchall()
            p_samples = conn.execute(
                """SELECT subject_name, detection_logic FROM knowledge_points kp
                   JOIN rules r ON r.id = kp.rule_id
                   WHERE r.source='pdf_2025' AND r.rule_subject = ? AND subject_name IS NOT NULL
                   LIMIT 5""", (p_raw,),
            ).fetchall()
            scores = []
            for xs in x_samples:
                for ps in p_samples:
                    a = (xs[0] or "") + "|" + (xs[1] or "")
                    b = (ps[0] or "") + "|" + (ps[1] or "")
                    ratio = difflib.SequenceMatcher(None, a, b).ratio()
                    scores.append(ratio)
            if scores:
                sim_scores.append((s, max(scores), sum(scores) / len(scores), len(scores)))
        report["sample_similarity"] = {
            "rules_compared": len(sim_scores),
            "average_max_similarity": round(sum(s[1] for s in sim_scores) / len(sim_scores), 4) if sim_scores else 0,
            "average_mean_similarity": round(sum(s[2] for s in sim_scores) / len(sim_scores), 4) if sim_scores else 0,
            "details": [
                {"subject": s, "max": round(mx, 3), "mean": round(mn, 3), "pairs": n}
                for s, mx, mn, n in sim_scores
            ],
        }

    # verdict
    cov = report["coverage"]
    sim = report["sample_similarity"]
    pdf_covers_all_xlsx = (cov["only_in_xlsx"] == [])
    sim_ok = sim["average_mean_similarity"] >= 0.70
    report["verdict"] = {
        "pdf_covers_all_xlsx_rules": pdf_covers_all_xlsx,
        "sample_similarity_ok": sim_ok,
        "pass": pdf_covers_all_xlsx and sim_ok,
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "qa_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"QA report written to: {out_path}\n")
    print(f"=== Totals ===")
    for k, v in report["totals"].items():
        print(f"  {k}: {v}")
    print(f"\n=== Coverage ===")
    print(f"  XLSX rule subjects: {cov['xlsx_rule_count']}")
    print(f"  PDF rule subjects:  {cov['pdf_rule_count']}")
    print(f"  Exact intersect:    {cov['exact_intersect_count']}")
    print(f"  Fuzzy intersect:    {cov['fuzzy_intersect_count']}  (= match after stripping '医疗服务项目/药品/中药饮片/耗材')")
    print(f"  Only in XLSX:       {len(cov['only_in_xlsx'])}  {cov['only_in_xlsx']}")
    print(f"  Only in PDF:        {len(cov['only_in_pdf'])}")
    print(f"\n=== Sample similarity ===")
    print(f"  Rules compared:           {sim['rules_compared']}")
    print(f"  Avg max similarity:       {sim['average_max_similarity']}")
    print(f"  Avg mean similarity:      {sim['average_mean_similarity']}")
    print(f"\n=== Verdict ===")
    print(f"  pdf_covers_all_xlsx:      {report['verdict']['pdf_covers_all_xlsx_rules']}")
    print(f"  sample_similarity_ok:     {report['verdict']['sample_similarity_ok']}")
    print(f"  PASS:                     {report['verdict']['pass']}")


if __name__ == "__main__":
    main()
