---
name: document-extraction
description: Extract structured JSON from office documents (PDF, DOCX, XLSX, PPTX) according to a JSON Schema. Use when data needs to be pulled out of documents into structured, validated form — invoices, financial tables, meeting minutes, presentations — and when accuracy matters more than speed.
---

# Document Extraction

Extract structured data from a document into JSON that conforms to a caller-supplied JSON Schema.

## Contract

**Inputs:** a document file (`.pdf`, `.docx`, `.xlsx`, `.pptx`) and a JSON Schema describing the target structure.

**Output:** a single JSON object conforming to the schema, written to the requested output path (or printed if none given). Nothing else goes in that file — no markdown fences, no commentary.

**Rules — these outrank speed:**

1. **Never guess.** If a value is absent from the document, emit `null` (or omit the field if the schema allows). A wrong value is worse than a missing one.
2. **Transcribe, don't paraphrase.** Copy values exactly as written, then normalize only as the schema demands (numbers as JSON numbers without currency symbols or thousands separators; dates as ISO 8601 `YYYY-MM-DD` unless the schema says otherwise).
3. **Read the whole document** before extracting. Values are often restated or corrected later (e.g., a summary page overriding a line item, an amended total).
4. **Validate before finishing.** Run the validator (below) and fix any violations by re-reading the document, not by inventing values.

## Workflow

### 1. Convert the document to a readable intermediate representation

```bash
uv run <skill-dir>/scripts/convert.py <document> --out <scratch-dir>
```

This writes `<scratch-dir>/ir.json` — a structured JSON rendering where every value is coordinate-addressable (page/table/row for PDFs, sheet/cell like `Expenses!C7` for spreadsheets, slide/shape for decks) — and prints a summary (page count, table count, warnings). Read `ir.json` in full. The IR shape per format is documented in the docstring at the top of `convert.py`; in short: PDFs give `pages[].text` + `pages[].tables[].rows`, DOCX gives ordered `blocks` (headings/paragraphs/tables), XLSX gives `sheets[].rows[]` as `{"row": n, "cells": {"A": value, ...}}` with empty cells omitted, and PPTX gives `slides[].texts/tables/notes`.

Warnings to act on:
- `NO_TEXT_LAYER` on a PDF page: the page is likely scanned. Read the original PDF file directly with the Read tool (it renders pages visually) for those pages instead of relying on the IR.
- `TRUNCATED` on a spreadsheet: the sheet exceeded the render cap. Re-run with `--max-rows` / `--max-cols` raised, or target the specific sheet with `--sheet`.

Values in the IR keep their source types: numbers stay numbers, spreadsheet dates arrive as ISO strings. A string in the IR means the document showed a string — do not silently coerce unless the schema requires it.

### 2. Study the schema

Read the JSON Schema before extracting. Note required fields, types, enums, and formats. For arrays of objects (line items, rows), identify the natural key fields — extract every item, in document order.

### 3. Extract

Walk the schema field by field, locating each value in the IR (or the rendered original for scanned pages). For each value, know where it came from — if you cannot point to a location in the document, the value is a guess: emit `null`.

Ambiguity resolution:
- Multiple candidate values (e.g., two "total" figures): prefer the most specific/final one (grand total over subtotal, amended over original) and prefer values labeled with the schema field's meaning.
- Calculated vs. stated values: prefer the stated value. Do not compute values the document doesn't state, unless the schema field explicitly asks for a derived quantity.
- Units/currency: keep the magnitude as written; record the unit only if the schema has a field for it.

### 4. Validate and deliver

```bash
uv run <skill-dir>/scripts/validate.py <output.json> --schema <schema.json>
```

Fix violations by re-reading the source. When validation passes, write the final JSON to the requested output path.

## Format-specific guidance

Load only what you need:
- PDFs (layout, tables, scanned pages): `references/pdf-extraction.md`
- Spreadsheets (headers, merged cells, formulas, multi-table sheets): `references/spreadsheet-extraction.md`
