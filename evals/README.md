# Evaluation framework

Quantitative grading for the extraction skills. The unit of measurement is the
**leaf field**: every scalar position in the expected/predicted JSON trees gets a
score in [0, 1] and a status, and everything else aggregates up from there.

## Case anatomy

```
cases/<case-id>/
  document/<file>      input document (pdf/docx/xlsx/pptx)
  schema.json          extraction target (JSON Schema, draft 2020-12)
  expected.json        ground truth
  case.yaml            metadata + scoring config
```

`case.yaml`:

```yaml
doc_kind: pdf                # slice key for reporting
family: invoice
seed: 1
tags: [pdf, tables, numbers] # hazard tags — slice keys for reporting
scoring:
  fields:                    # path rules; [] matches any index
    line_items:              {align_keys: [sku]}          # how to pair list items
    line_items[].description: {comparator: fuzzy, threshold: 0.85}
    total:                   {weight: 3}                  # matters more than a memo field
```

## How grading works (`harness/comparators.py`)

Typed comparators per leaf, chosen by config or inferred from the expected value:

| comparator | behavior |
|---|---|
| `number` | parses `$1,234.56`, `(45.00)` accounting negatives; abs/rel tolerance |
| `date` | compares ISO dates, tolerating datetime suffixes |
| `string` | exact after NFKC + whitespace-collapse + casefold |
| `fuzzy` | SequenceMatcher ratio, credited only above `threshold` |
| `bool` / enum | identity |

Structures recurse. Lists of objects are **aligned** first — by `align_keys` when
configured, else greedily by pairwise similarity — then unmatched expected items
count as *missing* and unmatched predicted items as *spurious*. Scalar lists match
as order-insensitive multisets.

Statuses: `correct`, `partial` (fuzzy credit), `incorrect`, `missing` (expected a
value, got null/absent), `spurious` (hallucinated a value where truth is null),
`both_null` (correctly absent — scores 1.0 but excluded from precision/recall so
easy nulls can't inflate P/R).

## Metrics (`harness/score.py`)

- **field_accuracy** — weighted mean leaf score, nulls included (micro pools all
  leaves; macro averages per-case scores so small documents count equally).
- **precision** — credit over predicted-present leaves. Drops when the skill
  hallucinates. **recall** — credit over expected-present leaves. Drops when it
  omits. **f1** — harmonic mean.
- **exact_match** — case scored 1.0 on every leaf.
- Slices: `by_doc_kind`, `by_tag` — where a regression localizes.

A case with no prediction file scores as fully missing: a run cannot improve its
average by crashing on hard cases.

## Running

```sh
uv run harness/run.py --label <label> [--model <id>] [--only case-id ...] [--jobs N]
```

spawns one headless `claude -p` per case (plugin loaded via `--plugin-dir`, the
prompt invokes the skill the way a user would), writes
`runs/<timestamp>-<label>/predictions/` + per-case cost/duration metadata, then
scores into `results.json`.

Re-score without re-running (e.g. after improving comparators):

```sh
uv run harness/score.py --cases cases --predictions runs/<run>/predictions \
    --out runs/<run>/results.json --label <label>
```

Trends and comparisons:

```sh
uv run harness/report.py                       # all runs, oldest→newest
uv run harness/report.py --compare <runA> <runB>  # per-case + per-slice deltas
```

## Methodology rules

1. **Commit run records.** `runs/*/results.json` and `predictions/` are the
   measurement history; without them "improvement" is unfalsifiable. (Scratch dirs
   are gitignored.)
2. **One variable per comparison.** Change the skill *or* the model between runs,
   never both; the run record's `git_sha` + `model` fields enforce honesty.
3. **Never tune on the whole corpus.** When chasing a specific failure, add new
   seeds/cases for that hazard and check the *other* slices didn't regress —
   `report.py --compare` shows per-slice deltas for exactly this.
4. **Grow truth carefully.** Synthetic cases have exact truth by construction. For
   real documents, `expected.json` must be hand-verified against the document by a
   person before the case enters the corpus.
5. **Scorer changes invalidate comparisons.** After editing comparators, re-score
   all historical runs (predictions are kept for this reason) so the trend line
   stays apples-to-apples.
