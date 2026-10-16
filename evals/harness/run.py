#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Run the document-extraction skill over eval cases and score the results.

    uv run run.py --label baseline [--model claude-sonnet-5] [--only case-id ...]

For each case this spawns a headless `claude -p` session instructed to follow the
skill, then scores all predictions with score.py. Everything lands in one run
directory so a run is a self-contained, comparable record:

    evals/runs/<UTC-timestamp>-<label>/
        predictions/<case-id>.json        extraction outputs
        predictions/<case-id>.meta.json   duration, cost, turns, session id
        results.json                      scored run record (see score.py)

Use --predictions-only to produce predictions without scoring, or score.py
directly to re-score an existing run after changing comparators.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HARNESS = Path(__file__).parent
EVALS = HARNESS.parent
REPO = EVALS.parent
SKILL_DIR = REPO / "skills" / "document-extraction"

# The repo is loaded as a plugin (--plugin-dir), so naming the skill in the
# prompt makes Claude invoke it via the Skill tool — same path a real user hits.
PROMPT_TEMPLATE = """\
Use the document-extraction skill to extract structured data from the document
{document}
according to the JSON Schema at {schema}.
Write the final schema-conforming JSON (and nothing else) to {output}.
Use {scratch} for intermediate files.
"""


def run_case(case_dir: Path, out_dir: Path, scratch_root: Path, model: str | None, timeout: int, extra_args: list[str]) -> dict:
    case_id = case_dir.name
    doc = next(p for p in (case_dir / "document").iterdir() if not p.name.startswith("."))
    output = out_dir / f"{case_id}.json"
    scratch = scratch_root / case_id
    scratch.mkdir(parents=True, exist_ok=True)

    prompt = PROMPT_TEMPLATE.format(
        skill_md=SKILL_DIR / "SKILL.md",
        document=doc.resolve(),
        schema=(case_dir / "schema.json").resolve(),
        output=output.resolve(),
        scratch=scratch.resolve(),
    )
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--plugin-dir", str(REPO),
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Bash(uv run:*),Read,Write,Glob,Grep,Skill",
        "--add-dir", str(REPO), "--add-dir", str(scratch_root), "--add-dir", str(out_dir),
    ]
    if model:
        cmd += ["--model", model]
    cmd += extra_args

    start = time.monotonic()
    meta: dict = {"case": case_id, "model": model}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=scratch)
        meta["exit_code"] = proc.returncode
        try:
            payload = json.loads(proc.stdout)
            meta["cost_usd"] = payload.get("total_cost_usd")
            meta["num_turns"] = payload.get("num_turns")
            meta["session_id"] = payload.get("session_id")
            meta["is_error"] = payload.get("is_error", False)
        except json.JSONDecodeError:
            meta["stderr_tail"] = proc.stderr[-2000:]
    except subprocess.TimeoutExpired:
        meta["exit_code"] = None
        meta["timed_out"] = True
    meta["duration_s"] = round(time.monotonic() - start, 1)
    meta["produced_output"] = output.exists()

    (out_dir / f"{case_id}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    flag = "ok" if output.exists() else "NO OUTPUT"
    print(f"  {case_id}: {flag} ({meta['duration_s']}s, ${meta.get('cost_usd') or '?'})")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", required=True, help="run label, e.g. 'baseline' or 'v2-prompts'")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=2, help="cases run in parallel")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per case")
    ap.add_argument("--predictions-only", action="store_true")
    ap.add_argument("--claude-args", nargs=argparse.REMAINDER, default=[],
                    help="extra args passed through to the claude CLI")
    args = ap.parse_args()

    cases = sorted(d for d in (EVALS / "cases").iterdir() if (d / "expected.json").exists())
    if args.only:
        cases = [d for d in cases if d.name in set(args.only)]
    if not cases:
        print("error: no cases matched", file=sys.stderr)
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVALS / "runs" / f"{ts}-{args.label}"
    pred_dir = run_dir / "predictions"
    pred_dir.mkdir(parents=True)
    scratch_root = run_dir / "scratch"

    print(f"running {len(cases)} cases -> {run_dir}")
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        metas = list(pool.map(
            lambda c: run_case(c, pred_dir, scratch_root, args.model, args.timeout, args.claude_args),
            cases,
        ))

    total_cost = sum(m.get("cost_usd") or 0 for m in metas)
    print(f"total cost: ${total_cost:.2f}")

    if args.predictions_only:
        print(f"predictions in {pred_dir}; score with:\n"
              f"  uv run {HARNESS}/score.py --cases {EVALS}/cases --predictions {pred_dir} "
              f"--out {run_dir}/results.json --label {args.label}")
        return 0

    score_cmd = [
        "uv", "run", str(HARNESS / "score.py"),
        "--cases", str(EVALS / "cases"),
        "--predictions", str(pred_dir),
        "--out", str(run_dir / "results.json"),
        "--label", args.label,
    ]
    if args.model:
        score_cmd += ["--model", args.model]
    if args.only:
        score_cmd += ["--only", *args.only]
    return subprocess.run(score_cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
