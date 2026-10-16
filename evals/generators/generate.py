#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "reportlab>=4.0",
#   "openpyxl>=3.1",
#   "python-docx>=1.1",
#   "python-pptx>=1.0",
#   "pyyaml>=6.0",
# ]
# ///
"""Generate synthetic eval cases: a document plus guaranteed-correct ground truth.

    uv run generate.py all --out ../cases            # default corpus (2 per family)
    uv run generate.py invoice --seed 7 --out ../cases

Each case directory is self-contained:

    <family>-<seed>/
        document/<file>     the input document
        schema.json         extraction target schema
        expected.json       ground truth (written by the same code that wrote the doc)
        case.yaml           doc_kind, tags, and scoring config

Determinism: the same family+seed always produces the same document and truth, so
cases are reproducible and diffs reviewable. Each family embeds a known extraction
hazard (see the family docstrings) so scores measure real failure modes.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import yaml

VENDORS = ["Acme Industrial Supply", "Northwind Traders", "Cascadia Paper Co.", "Blue Harbor Logistics", "Summit Office Systems"]
CLIENTS = ["Meridian Health Partners", "Foxglove Analytics", "Harborview Ventures", "Stonebridge Manufacturing"]
PEOPLE = ["Dana Whitfield", "Marcus Chen", "Priya Raman", "Tomás Alvarez", "Keiko Tanaka", "Sam O'Donnell", "Leah Katz", "Viktor Ilyin"]
PRODUCTS = [
    ("SKU-1042", "A4 recycled copy paper, 500 sheets"),
    ("SKU-2210", "Wireless ergonomic keyboard"),
    ("SKU-3305", "Standing desk converter, 32in"),
    ("SKU-4118", "Toner cartridge, high yield black"),
    ("SKU-5521", "Conference speakerphone"),
    ("SKU-6007", "Whiteboard, magnetic, 6x4 ft"),
    ("SKU-7133", "USB-C docking station, dual 4K"),
]
CATEGORIES = ["Travel", "Meals", "Software", "Hardware", "Training", "Office Supplies"]
DEPARTMENTS = ["Engineering", "Field Operations", "Customer Success", "Finance"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def write_case(out: Path, case_id: str, doc_name: str, schema: dict, expected: dict, meta: dict) -> Path:
    case_dir = out / case_id
    (case_dir / "document").mkdir(parents=True, exist_ok=True)
    (case_dir / "schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    (case_dir / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
    (case_dir / "case.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    return case_dir / "document" / doc_name


def money(rng: random.Random, lo: float, hi: float) -> float:
    return round(rng.uniform(lo, hi), 2)


# ------------------------------------------------------------------ invoice pdf


INVOICE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["invoice_number", "issue_date", "due_date", "vendor_name", "bill_to_name",
                 "po_number", "currency", "line_items", "subtotal", "discount", "tax", "total"],
    "properties": {
        "invoice_number": {"type": "string"},
        "issue_date": {"type": "string", "format": "date"},
        "due_date": {"type": "string", "format": "date"},
        "vendor_name": {"type": "string"},
        "bill_to_name": {"type": "string"},
        "po_number": {"type": ["string", "null"], "description": "null when the invoice shows no PO"},
        "currency": {"type": "string"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sku", "description", "quantity", "unit_price", "amount"],
                "properties": {
                    "sku": {"type": "string"},
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                },
            },
        },
        "subtotal": {"type": "number"},
        "discount": {"type": ["number", "null"], "description": "negative number as shown; null when absent"},
        "tax": {"type": "number"},
        "total": {"type": "number"},
    },
}


def gen_invoice(seed: int, out: Path) -> str:
    """Hazards: accounting-style negative discount `(123.45)`; PO number present
    only sometimes (tests null discipline); ruled table for pdfplumber."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    rng = random.Random(seed)
    vendor = rng.choice(VENDORS)
    client = rng.choice(CLIENTS)
    inv_no = f"INV-2026-{rng.randint(1000, 9999)}"
    month, day = rng.randint(1, 6), rng.randint(1, 28)
    issue = f"2026-{month:02d}-{day:02d}"
    due = f"2026-{month + 1:02d}-{day:02d}"
    po = f"PO-{rng.randint(10000, 99999)}" if rng.random() < 0.6 else None

    items = []
    for sku, desc in rng.sample(PRODUCTS, rng.randint(3, 5)):
        qty = rng.randint(1, 12)
        unit = money(rng, 8, 450)
        items.append({"sku": sku, "description": desc, "quantity": qty,
                      "unit_price": unit, "amount": round(qty * unit, 2)})
    subtotal = round(sum(i["amount"] for i in items), 2)
    discount = round(-money(rng, 10, subtotal * 0.1), 2) if rng.random() < 0.5 else None
    taxable = round(subtotal + (discount or 0), 2)
    tax = round(taxable * 0.095, 2)
    total = round(taxable + tax, 2)

    expected = {"invoice_number": inv_no, "issue_date": issue, "due_date": due,
                "vendor_name": vendor, "bill_to_name": client, "po_number": po,
                "currency": "USD", "line_items": items, "subtotal": subtotal,
                "discount": discount, "tax": tax, "total": total}
    meta = {
        "doc_kind": "pdf", "family": "invoice", "seed": seed,
        "tags": ["pdf", "invoice", "tables", "numbers"] + (["negatives"] if discount else []) + ([] if po else ["nulls"]),
        "scoring": {"fields": {
            "line_items": {"align_keys": ["sku"]},
            "line_items[].description": {"comparator": "fuzzy", "threshold": 0.85},
            "total": {"weight": 3},
            "invoice_number": {"weight": 2},
        }},
    }
    doc_path = write_case(out, f"invoice-{seed:03d}", "invoice.pdf", INVOICE_SCHEMA, expected, meta)

    c = canvas.Canvas(str(doc_path), pagesize=letter)
    w, h = letter
    y = h - 54
    c.setFont("Helvetica-Bold", 16); c.drawString(54, y, vendor)
    c.setFont("Helvetica-Bold", 22); c.drawRightString(w - 54, y, "INVOICE")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(54, y, "4102 Commerce Way, Portland, OR 97201")
    y -= 30
    for label, val in [("Invoice #", inv_no), ("Issue date", issue), ("Due date", due)] + ([("PO number", po)] if po else []):
        c.setFont("Helvetica-Bold", 10); c.drawString(w - 240, y, f"{label}:")
        c.setFont("Helvetica", 10); c.drawString(w - 150, y, val)
        y -= 14
    c.setFont("Helvetica-Bold", 10); c.drawString(54, y + (14 * (3 + (1 if po else 0))) - 14, "Bill to:")
    c.setFont("Helvetica", 10); c.drawString(110, y + (14 * (3 + (1 if po else 0))) - 14, client)

    y -= 24
    cols = [54, 130, 360, 410, 480, w - 54]
    headers = ["SKU", "Description", "Qty", "Unit Price", "Amount"]
    row_h = 20

    def row(vals: list[str], bold: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        c.line(cols[0], y, cols[-1], y)
        for i, v in enumerate(vals):
            if i >= 2:
                c.drawRightString(cols[i + 1] - 6, y - 14, v)
            else:
                c.drawString(cols[i] + 4, y - 14, v)
        y -= row_h

    top = y
    row(headers, bold=True)
    for it in items:
        row([it["sku"], it["description"], str(it["quantity"]),
             f"{it['unit_price']:,.2f}", f"{it['amount']:,.2f}"])
    c.line(cols[0], y, cols[-1], y)
    for x in cols:
        c.line(x, top, x, y)

    y -= 20
    c.setFont("Helvetica", 10)
    c.drawRightString(480, y, "Subtotal:"); c.drawRightString(w - 54, y, f"{subtotal:,.2f}"); y -= 15
    if discount is not None:
        c.drawRightString(480, y, "Discount:"); c.drawRightString(w - 54, y, f"({abs(discount):,.2f})"); y -= 15
    c.drawRightString(480, y, "Tax (9.5%):"); c.drawRightString(w - 54, y, f"{tax:,.2f}"); y -= 15
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(480, y, "Total due (USD):"); c.drawRightString(w - 54, y, f"{total:,.2f}")
    y -= 40
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(54, y, "Payment terms: Net 30. Please reference the invoice number on remittance.")
    c.save()
    return f"invoice-{seed:03d}"


# ------------------------------------------------------------- expense xlsx


EXPENSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["report_month", "department", "currency", "expenses", "total_amount"],
    "properties": {
        "report_month": {"type": "string", "pattern": "^\\d{4}-\\d{2}$"},
        "department": {"type": "string"},
        "currency": {"type": "string"},
        "expenses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["date", "employee", "category", "amount"],
                "properties": {
                    "date": {"type": "string", "format": "date"},
                    "employee": {"type": "string"},
                    "category": {"type": "string"},
                    "amount": {"type": "number"},
                },
            },
        },
        "total_amount": {"type": "number"},
    },
}


def gen_expenses(seed: int, out: Path) -> str:
    """Hazards: header row is row 5, not row 1; dates are datetime cells; a
    Total row that must not be extracted as a line item; a second sheet of noise."""
    from datetime import datetime

    import openpyxl

    rng = random.Random(1000 + seed)
    month = rng.randint(1, 6)
    dept = rng.choice(DEPARTMENTS)
    rows = []
    for _ in range(rng.randint(6, 10)):
        rows.append({
            "date": f"2026-{month:02d}-{rng.randint(1, 28):02d}",
            "employee": rng.choice(PEOPLE),
            "category": rng.choice(CATEGORIES),
            "amount": money(rng, 12, 900),
        })
    rows.sort(key=lambda r: r["date"])
    total = round(sum(r["amount"] for r in rows), 2)

    expected = {"report_month": f"2026-{month:02d}", "department": dept,
                "currency": "USD", "expenses": rows, "total_amount": total}
    meta = {
        "doc_kind": "xlsx", "family": "expenses", "seed": seed,
        "tags": ["xlsx", "tables", "dates", "totals-row"],
        "scoring": {"fields": {
            "expenses": {"align_keys": ["date", "employee", "amount"]},
            "total_amount": {"weight": 3},
        }},
    }
    doc_path = write_case(out, f"expenses-{seed:03d}", "expenses.xlsx", EXPENSE_SCHEMA, expected, meta)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws["A1"] = f"Expense Report — {MONTH_NAMES[month - 1]} 2026"
    ws["A2"] = f"Department: {dept}"
    ws["A3"] = "All amounts in USD"
    ws.append([])
    ws.append(["Date", "Employee", "Category", "Amount"])
    for r in rows:
        d = datetime.fromisoformat(r["date"])
        ws.append([d, r["employee"], r["category"], r["amount"]])
    ws.append([])
    ws.append(["Total", None, None, total])

    notes = wb.create_sheet("Notes")
    notes["A1"] = "Reminder: submit receipts within 30 days."
    notes["A2"] = "Draft — figures on this sheet are illustrative only."
    notes["A4"] = "Sample amount: 99999.99"
    wb.save(str(doc_path))
    return f"expenses-{seed:03d}"


# ---------------------------------------------------------------- minutes docx


MINUTES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["meeting_title", "date", "attendees", "decisions", "action_items"],
    "properties": {
        "meeting_title": {"type": "string"},
        "date": {"type": "string", "format": "date"},
        "attendees": {"type": "array", "items": {"type": "string"}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["owner", "task", "due_date"],
                "properties": {
                    "owner": {"type": "string"},
                    "task": {"type": "string"},
                    "due_date": {"type": ["string", "null"], "format": "date"},
                },
            },
        },
    },
}

PROJECTS = ["Project Phoenix", "Atlas Migration", "Q3 Pricing Review", "Data Platform Rollout"]
TASKS = [
    "Draft the vendor comparison matrix",
    "Schedule security review with the platform team",
    "Publish the updated onboarding runbook",
    "Close out the remaining migration tickets",
    "Prepare the budget variance summary",
    "Circulate the revised project timeline",
]
DECISIONS = [
    "Approved moving the launch date to the end of the quarter.",
    "Agreed to consolidate reporting into a single weekly dashboard.",
    "Deferred the tooling upgrade until after the audit.",
    "Selected the phased rollout option over the big-bang cutover.",
    "Increased the contingency budget by ten percent.",
]


def gen_minutes(seed: int, out: Path) -> str:
    """Hazards: date written long-form ('March 12, 2026') but schema wants ISO;
    an action item with due date 'TBD' that must map to null."""
    import docx

    rng = random.Random(2000 + seed)
    project = rng.choice(PROJECTS)
    title = f"{project} — Steering Committee Minutes"
    month, day = rng.randint(1, 6), rng.randint(1, 28)
    date_iso = f"2026-{month:02d}-{day:02d}"
    date_long = f"{MONTH_NAMES[month - 1]} {day}, 2026"
    attendees = rng.sample(PEOPLE, rng.randint(4, 6))
    decisions = rng.sample(DECISIONS, rng.randint(2, 3))
    actions = []
    for task in rng.sample(TASKS, rng.randint(3, 4)):
        has_due = rng.random() < 0.75
        due = f"2026-{month + 1:02d}-{rng.randint(1, 28):02d}" if has_due else None
        actions.append({"owner": rng.choice(attendees), "task": task, "due_date": due})

    expected = {"meeting_title": title, "date": date_iso, "attendees": attendees,
                "decisions": decisions, "action_items": actions}
    meta = {
        "doc_kind": "docx", "family": "minutes", "seed": seed,
        "tags": ["docx", "lists", "dates", "nulls"],
        "scoring": {"fields": {
            "action_items": {"align_keys": ["task"]},
            "action_items[].task": {"comparator": "fuzzy", "threshold": 0.85},
            "decisions[]": {"comparator": "fuzzy", "threshold": 0.85},
        }},
    }
    doc_path = write_case(out, f"minutes-{seed:03d}", "minutes.docx", MINUTES_SCHEMA, expected, meta)

    doc = docx.Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph(f"Date: {date_long}")
    doc.add_heading("Attendees", level=1)
    for a in attendees:
        doc.add_paragraph(a, style="List Bullet")
    doc.add_heading("Decisions", level=1)
    for d in decisions:
        doc.add_paragraph(d, style="List Number")
    doc.add_heading("Action Items", level=1)
    table = doc.add_table(rows=1 + len(actions), cols=3)
    table.style = "Table Grid"
    for i, htxt in enumerate(["Owner", "Task", "Due"]):
        table.rows[0].cells[i].text = htxt
    for r, a in enumerate(actions, 1):
        table.rows[r].cells[0].text = a["owner"]
        table.rows[r].cells[1].text = a["task"]
        table.rows[r].cells[2].text = a["due_date"] or "TBD"
    doc.add_paragraph("Minutes recorded by the project office.")
    doc.save(str(doc_path))
    return f"minutes-{seed:03d}"


# -------------------------------------------------------------------- qbr pptx


QBR_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["company", "quarter", "year", "presenter", "metrics", "risks"],
    "properties": {
        "company": {"type": "string"},
        "quarter": {"type": "string", "enum": ["Q1", "Q2", "Q3", "Q4"]},
        "year": {"type": "integer"},
        "presenter": {"type": "string"},
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "value", "yoy_change_pct"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string", "description": "as shown on the slide, e.g. '$4.2M' or '38%'"},
                    "yoy_change_pct": {"type": ["number", "null"]},
                },
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
    },
}

METRIC_POOL = [
    ("Annual recurring revenue", "$", "M"),
    ("Net revenue retention", "", "%"),
    ("New logos", "", ""),
    ("Gross margin", "", "%"),
    ("Active users", "", "K"),
]
RISKS = [
    "Renewal concentration in the top three accounts",
    "Hiring pipeline behind plan for support engineers",
    "Pending platform migration may slow feature delivery",
    "Currency exposure on EMEA contracts",
    "Single-sourced data provider for enrichment",
]


def gen_qbr(seed: int, out: Path) -> str:
    """Hazards: values that must be transcribed as displayed strings ('$4.2M');
    a metric with no YoY figure ('—') that must map to null; speaker notes as
    distractor content."""
    from pptx import Presentation
    from pptx.util import Inches

    rng = random.Random(3000 + seed)
    company = rng.choice(CLIENTS)
    quarter = f"Q{rng.randint(1, 4)}"
    year = 2026
    presenter = rng.choice(PEOPLE)
    metrics = []
    for name, prefix, suffix in rng.sample(METRIC_POOL, rng.randint(3, 4)):
        if suffix == "M":
            val = f"{prefix}{rng.uniform(1.2, 9.8):.1f}{suffix}"
        elif suffix in ("%", "K"):
            val = f"{rng.randint(15, 140)}{suffix}"
        else:
            val = str(rng.randint(8, 60))
        yoy = round(rng.uniform(-12, 40), 1) if rng.random() < 0.8 else None
        metrics.append({"name": name, "value": val, "yoy_change_pct": yoy})
    risks = rng.sample(RISKS, rng.randint(2, 3))

    expected = {"company": company, "quarter": quarter, "year": year,
                "presenter": presenter, "metrics": metrics, "risks": risks}
    meta = {
        "doc_kind": "pptx", "family": "qbr", "seed": seed,
        "tags": ["pptx", "tables", "nulls", "verbatim"],
        "scoring": {"fields": {
            "metrics": {"align_keys": ["name"]},
            "risks[]": {"comparator": "fuzzy", "threshold": 0.85},
        }},
    }
    doc_path = write_case(out, f"qbr-{seed:03d}", "qbr.pptx", QBR_SCHEMA, expected, meta)

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = f"{company} — {quarter} {year} Business Review"
    slide.placeholders[1].text = f"Presented by {presenter}"
    notes = slide.notes_slide.notes_text_frame
    notes.text = "Draft deck — numbers final as of close of quarter."

    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Key Metrics"
    rows, cols = 1 + len(metrics), 3
    tbl = slide.shapes.add_table(rows, cols, Inches(0.6), Inches(1.6), Inches(8.8), Inches(0.5 + 0.45 * rows)).table
    for i, htxt in enumerate(["Metric", "Value", "YoY change"]):
        tbl.cell(0, i).text = htxt
    for r, m in enumerate(metrics, 1):
        tbl.cell(r, 0).text = m["name"]
        tbl.cell(r, 1).text = m["value"]
        tbl.cell(r, 2).text = f"{m['yoy_change_pct']:+.1f}%" if m["yoy_change_pct"] is not None else "—"

    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Top Risks"
    tf = slide.placeholders[1].text_frame
    tf.text = risks[0]
    for r in risks[1:]:
        tf.add_paragraph().text = r
    prs.save(str(doc_path))
    return f"qbr-{seed:03d}"


# ------------------------------------------------------------------------ main


FAMILIES = {"invoice": gen_invoice, "expenses": gen_expenses, "minutes": gen_minutes, "qbr": gen_qbr}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("family", choices=[*FAMILIES, "all"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=1, help="generate seeds seed..seed+count-1")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent.parent / "cases")
    args = ap.parse_args()

    families = list(FAMILIES) if args.family == "all" else [args.family]
    count = 2 if (args.family == "all" and args.count == 1) else args.count
    made = []
    for fam in families:
        for s in range(args.seed, args.seed + count):
            made.append(FAMILIES[fam](s, args.out))
    print(f"generated {len(made)} cases: {', '.join(made)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
