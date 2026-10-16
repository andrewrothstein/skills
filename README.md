# skills

Claude data-extraction skills for structured office documents (DOCX, XLSX, PPTX) and
PDFs — built around the premise that skills you can't measure are skills you can't
improve. Every change to a skill is judged by the same quantitative harness, so
"better" means a number moved, not a vibe.

## Layout

```
.claude-plugin/plugin.json       this repo is a Claude Code plugin ("data-extraction")
skills/
  document-extraction/           the skill: SKILL.md + converter/validator scripts
evals/
  cases/                         eval corpus: document + schema + ground truth each
  generators/generate.py         synthetic case generators (4 document families)
  harness/                       run.py (execute), score.py (grade), report.py (trends)
  runs/                          committed run records — the measurement history
```

## The skill

`skills/document-extraction` extracts JSON conforming to a caller-supplied JSON
Schema from a PDF/DOCX/XLSX/PPTX. Its contract is accuracy-first: transcribe rather
than paraphrase, emit `null` rather than guess, validate before delivering. Helper
scripts (run via `uv run`, dependencies self-contained via PEP 723):

- `scripts/convert.py <doc>` — renders any supported document to a JSON
  intermediate representation (`ir.json`) in which every value is
  coordinate-addressable: pages/tables/rows for PDFs, `{"row": 7, "cells":
  {"C": …}}` for spreadsheets, ordered blocks for DOCX, slides for PPTX. The IR
  is the pipeline's interchange format — the skill reads it, and downstream
  tooling can consume it directly.
- `scripts/validate.py <out.json> --schema <schema.json>` — JSON Schema validation.

Use it interactively by loading the repo as a plugin:

```sh
claude --plugin-dir /path/to/this/repo
```

## The evaluation loop

```sh
cd evals

# 1. (optional) grow the corpus — deterministic synthetic docs with exact ground truth
uv run generators/generate.py all --out cases

# 2. run the skill over the corpus headlessly and score it
uv run harness/run.py --label baseline

# 3. see the trend across all recorded runs
uv run harness/report.py
```

Each run directory under `evals/runs/` is a self-contained record — predictions,
per-case cost/duration, and `results.json` with metrics keyed to **git SHA, model,
and label**. That key structure is what makes improvement claims attributable:
same model + new SHA → the skill changed; same SHA + new model → the model changed.

Metrics (see `evals/README.md` for definitions): field-level accuracy (micro and
macro), precision (hallucination penalty), recall (omission penalty), F1, and
exact-match rate, with slices by document kind and hazard tag.

## Design notes

- **Synthetic-first corpus.** Generators write the document and the ground truth
  from the same variables, so truth is exact by construction and the corpus grows
  by changing a seed. Real documents can be added as cases the same way — drop the
  file, schema, and hand-verified `expected.json` into `evals/cases/<id>/`.
- **Hazard tags.** Each case family embeds known failure modes (accounting
  negatives, headers not on row 1, totals rows, `TBD` dates that must become
  `null`, verbatim-string fields) and tags them, so regressions localize.
- **Nulls are graded.** Correctly saying "absent" scores; hallucinating a value
  costs precision. This enforces the skill's "never guess" rule numerically.
- **`claude plugin eval` forward-compatibility.** The official plugin eval suite is
  early-access; this repo already has plugin shape, and the custom harness
  (`claude -p --output-format json` per case) is the documented interim approach.
  When eval access lands, cases can be mirrored into its `evals/<case>/prompt.md` +
  graders format without restructuring.
