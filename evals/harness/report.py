#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Report metric trends across eval runs.

    uv run report.py                # table of all runs, oldest first
    uv run report.py --compare A B  # per-case and per-slice delta of two run dirs
    uv run report.py --markdown     # emit markdown instead of aligned text

Reads every evals/runs/*/results.json. Because run records carry the git SHA,
model, and label, a regression is attributable: same model + new SHA = skill
change; same SHA + new model = model change.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RUNS = Path(__file__).parent.parent / "runs"


def load_runs() -> list[tuple[str, dict]]:
    out = []
    for d in sorted(RUNS.iterdir()) if RUNS.exists() else []:
        f = d / "results.json"
        if f.exists():
            r = json.loads(f.read_text())
            r["_ops"] = run_ops(d)
            out.append((d.name, r))
    return out


def run_ops(run_dir: Path) -> dict:
    """Cost/latency aggregates from the per-case meta files run.py writes."""
    metas = [json.loads(m.read_text()) for m in sorted(run_dir.glob("predictions/*.meta.json"))]
    costs = [m["cost_usd"] for m in metas if m.get("cost_usd") is not None]
    durs = [m["duration_s"] for m in metas if m.get("duration_s") is not None]
    return {
        "total_cost_usd": round(sum(costs), 2) if costs else None,
        "mean_case_s": round(sum(durs) / len(durs), 1) if durs else None,
    }


def fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "-"


def table(rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows)


def trend(runs: list[tuple[str, dict]], markdown: bool) -> None:
    rows = [["run", "label", "sha", "model", "micro", "macro", "P", "R", "F1", "exact", "cost", "s/case"]]
    for name, r in runs:
        a = r["aggregate"]
        ops = r.get("_ops", {})
        cost, secs = ops.get("total_cost_usd"), ops.get("mean_case_s")
        rows.append([
            name, str(r.get("label") or "-"), str(r.get("git_sha") or "-"),
            str(r.get("model") or "-"),
            fmt_pct(a["micro_field_accuracy"]), fmt_pct(a["macro_field_accuracy"]),
            fmt_pct(a["precision"]), fmt_pct(a["recall"]), fmt_pct(a["f1"]),
            fmt_pct(a["exact_match_rate"]),
            f"${cost:.2f}" if cost is not None else "-",
            f"{secs}" if secs is not None else "-",
        ])
    print(table(rows, markdown))
    if len(runs) >= 2:
        prev, last = runs[-2][1]["aggregate"], runs[-1][1]["aggregate"]
        delta = last["micro_field_accuracy"] - prev["micro_field_accuracy"]
        print(f"\nlatest vs previous: micro accuracy {delta:+.1%}")


def compare(a_name: str, b_name: str, markdown: bool) -> None:
    a = json.loads((RUNS / a_name / "results.json").read_text())
    b = json.loads((RUNS / b_name / "results.json").read_text())
    a_cases = {c["case"]: c for c in a["cases"]}
    b_cases = {c["case"]: c for c in b["cases"]}
    rows = [["case", a_name, b_name, "delta"]]
    for cid in sorted(a_cases.keys() | b_cases.keys()):
        av = a_cases.get(cid, {}).get("field_accuracy")
        bv = b_cases.get(cid, {}).get("field_accuracy")
        d = f"{bv - av:+.1%}" if av is not None and bv is not None else "-"
        rows.append([cid, fmt_pct(av), fmt_pct(bv), d])
    print(table(rows, markdown))

    rows = [["doc_kind", a_name, b_name, "delta"]]
    for k in sorted(a.get("by_doc_kind", {}).keys() | b.get("by_doc_kind", {}).keys()):
        av = a["by_doc_kind"].get(k, {}).get("micro_field_accuracy")
        bv = b["by_doc_kind"].get(k, {}).get("micro_field_accuracy")
        d = f"{bv - av:+.1%}" if av is not None and bv is not None else "-"
        rows.append([k, fmt_pct(av), fmt_pct(bv), d])
    print()
    print(table(rows, markdown))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"))
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    if args.compare:
        compare(args.compare[0], args.compare[1], args.markdown)
        return 0
    runs = load_runs()
    if not runs:
        print("no runs found under evals/runs/", file=sys.stderr)
        return 1
    trend(runs, args.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
