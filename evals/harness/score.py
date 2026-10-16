#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Score prediction JSONs against ground truth and emit a run record.

    uv run score.py --cases evals/cases --predictions <dir> --out <results.json>

Predictions layout: <dir>/<case-id>.json, one schema-conforming JSON per case.
A missing prediction file scores the case as fully missing (the run failed there),
so a flaky skill can't improve its average by crashing on hard cases.

Metrics
-------
Per case:
  field_accuracy  weighted mean leaf score over every leaf (nulls included —
                  correctly predicting "absent" is part of the job)
  precision       credit on predicted-present leaves (penalizes hallucination)
  recall          credit on expected-present leaves (penalizes omission)
  f1, exact_match, status counts
Corpus:
  macro (mean of case scores), micro (all leaves pooled), exact-match rate,
  and per-tag / per-doc-kind breakdowns for slicing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from comparators import CompareConfig, FieldResult, compare  # noqa: E402


def prf(leaves: list[FieldResult]) -> dict:
    scored = [l for l in leaves if not l.trivial]
    exp_present = [l for l in scored if l.expected is not None]
    pred_present = [l for l in scored if l.predicted is not None]
    recall = sum(l.score for l in exp_present) / len(exp_present) if exp_present else 1.0
    precision = sum(l.score for l in pred_present) / len(pred_present) if pred_present else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def weighted_accuracy(leaves: list[FieldResult]) -> float:
    total_w = sum(l.weight for l in leaves)
    return sum(l.score * l.weight for l in leaves) / total_w if total_w else 1.0


def score_case(case_dir: Path, prediction_path: Path) -> dict:
    meta = yaml.safe_load((case_dir / "case.yaml").read_text()) or {}
    expected = json.loads((case_dir / "expected.json").read_text())
    cfg = CompareConfig(fields=meta.get("scoring", {}).get("fields", {}))

    if prediction_path.exists():
        try:
            predicted = json.loads(prediction_path.read_text())
            error = None
        except json.JSONDecodeError as e:
            predicted, error = None, f"prediction is not valid JSON: {e}"
    else:
        predicted, error = None, "no prediction produced"

    leaves = compare(expected, predicted, cfg)
    statuses: dict[str, int] = {}
    for l in leaves:
        statuses[l.status] = statuses.get(l.status, 0) + 1
    acc = weighted_accuracy(leaves)
    return {
        "case": case_dir.name,
        "tags": meta.get("tags", []),
        "doc_kind": meta.get("doc_kind"),
        "error": error,
        "field_accuracy": round(acc, 4),
        **prf(leaves),
        "exact_match": acc >= 1.0,
        "statuses": statuses,
        "leaves": [
            {
                "path": l.path,
                "status": l.status,
                "score": round(l.score, 4),
                "expected": l.expected,
                "predicted": l.predicted,
                "comparator": l.comparator,
            }
            for l in leaves
            if l.status not in ("correct", "both_null")  # record only the misses
        ],
        "_all_leaves": leaves,  # stripped before serialization
    }


def aggregate(case_results: list[dict], by: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for r in case_results:
        keys = r.get(by) or []
        if isinstance(keys, str):
            keys = [keys]
        for k in keys:
            groups.setdefault(k, []).append(r)
    out = {}
    for k, rs in sorted(groups.items()):
        pooled = [l for r in rs for l in r["_all_leaves"]]
        out[k] = {
            "cases": len(rs),
            "macro_field_accuracy": round(sum(r["field_accuracy"] for r in rs) / len(rs), 4),
            "micro_field_accuracy": round(weighted_accuracy(pooled), 4),
            **prf(pooled),
        }
    return out


def git_sha(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default=None, help="human label for this run (e.g. 'baseline')")
    ap.add_argument("--model", default=None, help="model id used to produce predictions")
    ap.add_argument("--only", nargs="*", default=None, help="score only these case ids")
    args = ap.parse_args()

    case_dirs = sorted(d for d in args.cases.iterdir() if (d / "expected.json").exists())
    if args.only:
        case_dirs = [d for d in case_dirs if d.name in set(args.only)]
    if not case_dirs:
        print("error: no cases found", file=sys.stderr)
        return 2

    results = [score_case(d, args.predictions / f"{d.name}.json") for d in case_dirs]
    pooled = [l for r in results for l in r["_all_leaves"]]

    run = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": args.label,
        "model": args.model,
        "git_sha": git_sha(args.cases),
        "n_cases": len(results),
        "aggregate": {
            "macro_field_accuracy": round(sum(r["field_accuracy"] for r in results) / len(results), 4),
            "micro_field_accuracy": round(weighted_accuracy(pooled), 4),
            **prf(pooled),
            "exact_match_rate": round(sum(r["exact_match"] for r in results) / len(results), 4),
        },
        "by_doc_kind": aggregate(results, "doc_kind"),
        "by_tag": aggregate(results, "tags"),
        "cases": results,
    }
    for r in results:
        del r["_all_leaves"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run, indent=2) + "\n")

    agg = run["aggregate"]
    print(f"scored {len(results)} cases -> {args.out}")
    print(
        f"  micro accuracy {agg['micro_field_accuracy']:.1%} | macro {agg['macro_field_accuracy']:.1%}"
        f" | P {agg['precision']:.1%} R {agg['recall']:.1%} F1 {agg['f1']:.1%}"
        f" | exact-match {agg['exact_match_rate']:.1%}"
    )
    worst = sorted(results, key=lambda r: r["field_accuracy"])[:3]
    for r in worst:
        note = f" ({r['error']})" if r["error"] else ""
        print(f"  worst: {r['case']} {r['field_accuracy']:.1%}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
