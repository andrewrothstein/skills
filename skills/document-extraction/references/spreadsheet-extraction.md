# Spreadsheet extraction notes

The IR renders each sheet as JSON rows of the form `{"row": 7, "cells": {"A": …,
"C": …}}`, so every value has an addressable coordinate (e.g. `C7`). Empty cells
are omitted — a column letter that never appears in a row was blank there, and a
gap in the letters within a row is a blank cell, not adjacency.

## Headers are data, not decoration

- The header row is often **not row 1**. Title rows, blank rows, and metadata
  (report date, filters) commonly precede it. Find the header row by looking for
  the row where every populated cell is a label.
- Multi-row headers (year on one row, quarter on the next) must be combined to name
  a column correctly.

## Values

- The IR is generated with `data_only=True`: you see the last **computed** value of
  formulas, not the formula. If a cell shows empty where a formula clearly belongs,
  the file was saved without a cached value — flag it as `null`, don't recompute.
- Dates may surface as ISO datetimes (`2026-03-01 00:00:00`) — truncate to the date
  when the schema wants a date.
- Percentages stored as fractions render as `0.15` for 15%. Check a labeled cell or
  header for `%` cues before deciding magnitude.

## Structure hazards

- **Multiple tables per sheet**: a sheet may stack several logical tables separated
  by blank rows. Extract only the one matching the schema's target; blank-row
  boundaries delimit them.
- **Merged cells**: only the top-left cell of a merged range carries the value; the
  rest render empty. A category label followed by empty cells below it usually
  applies to all rows until the next label.
- **Totals rows**: exclude `Total`/`Subtotal` rows from line-item arrays unless the
  schema asks for them; use them to cross-check your extracted items instead.
- **Hidden sheets/rows** still render in the IR. Prefer the sheet named most like
  the schema's subject when duplicates exist.
