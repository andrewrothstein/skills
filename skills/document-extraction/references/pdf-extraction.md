# PDF extraction notes

## Scanned pages / missing text layer

When `convert.py` reports `NO_TEXT_LAYER` for a page, the page is an image. Read the
original PDF with the Read tool (it renders pages visually) and transcribe from the
rendered page. Transcribe conservatively: if a character is illegible, the field it
belongs to is `null`, not a best guess.

## Tables

`pdfplumber` table detection depends on ruling lines. Failure modes and what to do:

- **Merged or split cells**: a logical row may be split across two IR rows (wrapped
  text) or two columns may be fused. Cross-check each row against the running total
  or column arithmetic when the document provides one.
- **Borderless tables**: may appear as plain text lines in the page text rather than
  as an IR table. Column alignment in the text is your structure signal — split on
  runs of 2+ spaces.
- **Headers repeated across pages**: a multi-page table repeats its header row on
  each page. Do not extract the repeated header as a data row.

## Numbers and amounts

- Negative amounts may be rendered as `(1,234.56)` (accounting style) — that is
  `-1234.56`.
- A trailing `-` (e.g. `1,234.56-`) is also negative in some ERP exports.
- Distinguish thousands separators from decimal separators by currency/locale cues
  in the document, not by assumption. `1.234,56` is `1234.56` in many EU documents.

## Multi-column layouts

Text extraction is top-to-bottom, left-to-right per line, which interleaves columns
in two-column layouts. If sentences read as nonsense, suspect column interleaving
and read the rendered page instead.
