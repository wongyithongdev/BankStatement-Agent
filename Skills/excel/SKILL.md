---
name: excel
description: Use this skill before writing any XLSX output for bank statement extraction. Provides exact color constants, helper functions, and complete sheet-writing functions for all 4 required sheets.
license: MIT
---

# Bank Statement Excel Export Guide (openpyxl)

## Core Imports

```python
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from collections import OrderedDict
```

## Color Palette

```python
# ── Headers ────────────────────────────────────────────────────────────────
COLOR_HEADER_BG    = "1F3864"   # dark navy  — sheet header row background
COLOR_HEADER_FONT  = "FFFFFF"   # white      — sheet header row text

# ── Transaction rows ───────────────────────────────────────────────────────
COLOR_CREDIT_BG    = "E2EFDA"   # light green  — credit rows (money IN)
COLOR_DEBIT_BG     = "FCE4D6"   # light orange — debit rows (money OUT)

# ── Grouping & totals ──────────────────────────────────────────────────────
COLOR_GROUP_BG     = "D9E1F2"   # soft blue   — payee group header
COLOR_SUBTOTAL_BG  = "BDD7EE"   # light blue  — subtotal / total rows
COLOR_SECTION_CR   = "375623"   # dark green  — CREDITS section header
COLOR_SECTION_DR   = "843C0C"   # dark orange — DEBITS section header

# ── Summary sheet ─────────────────────────────────────────────────────────
COLOR_SUMMARY_LABEL = "D6E4F0"  # pale blue   — label cells on summary sheet
COLOR_SUMMARY_VALUE = "FFFFFF"  # white       — value cells on summary sheet

# ── Misc ───────────────────────────────────────────────────────────────────
COLOR_DATE_BG      = "EBF3FB"   # very light blue — date column in daily summary
COLOR_BORDER       = "BFBFBF"   # grey        — cell borders
```

## Style Helpers

```python
def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def font(bold=False, color="000000", size=10):
    return Font(bold=bold, color=color, size=size, name="Calibri")

def border():
    s = Side(style="thin", color=COLOR_BORDER)
    return Border(left=s, right=s, top=s, bottom=s)

def align(h="left", wrap=False):
    return Alignment(horizontal=h, vertical="center", wrap_text=wrap)

def money_fmt():
    return '#,##0.00_);[Red](#,##0.00)'   # positives normal, negatives red in parens

def zero_dash_fmt():
    return '#,##0.00_);[Red](#,##0.00);"-"'  # zeros show as dash
```

## Number Formatting Rules

- **All monetary columns** (Credit, Debit, Balance, subtotals): use `money_fmt()` or `zero_dash_fmt()`
- **Zero-value cells**: format as `"-"` not `"0.00"` — use `zero_dash_fmt()` on the whole column
- **Dates**: store as plain string (as extracted from PDF), left-aligned
- **Row numbers (No.)**: center-aligned, no number format
- **Page numbers**: center-aligned, integer

```python
# Apply money format to a cell
cell.number_format = money_fmt()

# Apply zero-as-dash format (better for summary sheets with many zeros)
cell.number_format = zero_dash_fmt()
```

## Sheet 1 — Summary (account overview)

This is the FIRST sheet. It gives the reader an instant overview before they look at data.

```python
def write_summary_sheet(wb, meta):
    """
    meta dict keys:
        account_name   str   — account holder name
        account_no     str   — account number (masked OK: "1234-5678-****")
        bank           str   — bank name
        period_from    str   — statement start date
        period_to      str   — statement end date
        opening_bal    float — opening balance
        closing_bal    float — closing balance
        total_credits  float — sum of all credits
        total_debits   float — sum of all debits
        txn_count      int   — total transaction count
        currency       str   — e.g. "MYR"
    """
    ws = wb.create_sheet("Summary", 0)   # insert at position 0 (first sheet)

    # Column widths
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 32

    # Title row
    ws["A1"] = "BANK STATEMENT SUMMARY"
    ws["A1"].font      = font(bold=True, color=COLOR_HEADER_FONT, size=14)
    ws["A1"].fill      = fill(COLOR_HEADER_BG)
    ws["A1"].alignment = align("center")
    ws["B1"].fill      = fill(COLOR_HEADER_BG)
    ws.row_dimensions[1].height = 30

    rows = [
        ("Account Holder",  meta.get("account_name", "—")),
        ("Account Number",  meta.get("account_no", "—")),
        ("Bank",            meta.get("bank", "—")),
        ("Statement From",  meta.get("period_from", "—")),
        ("Statement To",    meta.get("period_to", "—")),
        ("Currency",        meta.get("currency", "MYR")),
        (None, None),   # spacer
        ("Opening Balance", meta.get("opening_bal", 0)),
        ("Total Credits",   meta.get("total_credits", 0)),
        ("Total Debits",    meta.get("total_debits", 0)),
        ("Closing Balance", meta.get("closing_bal", 0)),
        (None, None),   # spacer
        ("Total Transactions", meta.get("txn_count", 0)),
    ]

    for r, (label, value) in enumerate(rows, start=2):
        if label is None:
            ws.row_dimensions[r].height = 8
            continue
        lc = ws.cell(row=r, column=1, value=label)
        vc = ws.cell(row=r, column=2, value=value)
        lc.fill      = fill(COLOR_SUMMARY_LABEL)
        lc.font      = font(bold=True, size=11)
        lc.alignment = align("left")
        lc.border    = border()
        vc.fill      = fill(COLOR_SUMMARY_VALUE)
        vc.font      = font(size=11)
        vc.alignment = align("right")
        vc.border    = border()
        # Format monetary rows
        if label in ("Opening Balance", "Total Credits", "Total Debits", "Closing Balance"):
            vc.number_format = money_fmt()
        ws.row_dimensions[r].height = 20

    return ws
```

## Sheet 2 — Transactions

```python
def write_transactions_sheet(wb, transactions):
    """
    transactions: list of dicts with keys:
        page, date, description, payee, credit, debit, balance
    credit/debit are float or None (never both filled).
    """
    ws = wb.active
    ws.title = "Transactions"

    HEADERS    = ["Page", "Date", "Description", "Payee", "Credit (RM)", "Debit (RM)", "Balance (RM)"]
    COL_WIDTHS = [6,      14,     52,             28,      14,            14,            14]

    for i, w in enumerate(COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Header row
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill      = fill(COLOR_HEADER_BG)
        cell.font      = font(bold=True, color=COLOR_HEADER_FONT, size=10)
        cell.alignment = align("center")
        cell.border    = border()
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    # Data rows
    for i, t in enumerate(transactions, start=2):
        is_credit = bool(t.get("credit"))
        bg = COLOR_CREDIT_BG if is_credit else COLOR_DEBIT_BG

        ws.append([
            t.get("page"),
            t.get("date"),
            t.get("description"),
            t.get("payee"),
            t.get("credit") if t.get("credit") else None,
            t.get("debit")  if t.get("debit")  else None,
            t.get("balance"),
        ])

        for col, cell in enumerate(ws[i], start=1):
            cell.fill   = fill(bg)
            cell.border = border()
            cell.font   = font(size=10)
            if col == 1:                    # Page
                cell.alignment = align("center")
            elif col in (5, 6, 7):         # Credit / Debit / Balance
                cell.alignment = align("right")
                cell.number_format = zero_dash_fmt()
            else:
                cell.alignment = align("left")

    ws.auto_filter.ref = f"A1:G{len(transactions) + 1}"
    return ws
```

## Sheet 3 — By Payee & Buyer

```python
def classify_txn_type(description):
    desc = (description or "").upper().strip()
    if desc.startswith("DUITNOW"):                                          return "DuitNow"
    if desc.startswith(("CMS -", "CMS-")):                                 return "CMS"
    if desc.startswith(("RCMS -", "RCMS-")):                               return "RCMS"
    if desc.startswith(("TRANSFER TO", "TRANSFER FROM", "INTERBANK")):     return "Transfer"
    if desc.startswith(("IBG FROM", "INTER-BANK", "GIRO CREDIT")):         return "IBG"
    return "Other"


def write_payee_buyer_sheet(wb, transactions):
    ws = wb.create_sheet("By Payee & Buyer")

    HEADERS    = ["No.", "Date", "Description", "Payee", "Type", "Debit (RM)", "Credit (RM)", "Balance (RM)"]
    COL_WIDTHS = [6,     14,     50,             28,      12,     14,           14,             14]
    for i, w in enumerate(COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill      = fill(COLOR_HEADER_BG)
        cell.font      = font(bold=True, color=COLOR_HEADER_FONT, size=10)
        cell.alignment = align("center")
        cell.border    = border()
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    def _write_section(ws, label, txns, row_num, sec_color):
        # Section header
        ws.append([label] + [""] * 7)
        for cell in ws[row_num]:
            cell.fill      = fill(sec_color)
            cell.font      = font(bold=True, color="FFFFFF", size=11)
            cell.border    = border()
            cell.alignment = align("left")
        ws.row_dimensions[row_num].height = 22
        row_num += 1

        by_payee = OrderedDict()
        for t in txns:
            by_payee.setdefault(t.get("payee") or "Unknown", []).append(t)

        counter = 1
        for payee, ptxns in by_payee.items():
            # Payee group header
            ws.append([payee] + [""] * 7)
            for cell in ws[row_num]:
                cell.fill      = fill(COLOR_GROUP_BG)
                cell.font      = font(bold=True, size=10)
                cell.border    = border()
                cell.alignment = align("left")
            row_num += 1

            for t in ptxns:
                bg = COLOR_CREDIT_BG if t.get("credit") else COLOR_DEBIT_BG
                ws.append([
                    counter,
                    t.get("date"),
                    (t.get("description") or "")[:60],
                    t.get("payee"),
                    classify_txn_type(t.get("description", "")),
                    t.get("debit")   if t.get("debit")   else None,
                    t.get("credit")  if t.get("credit")  else None,
                    t.get("balance"),
                ])
                for col, cell in enumerate(ws[row_num], start=1):
                    cell.fill   = fill(bg)
                    cell.border = border()
                    cell.font   = font(size=10)
                    if col in (6, 7, 8):
                        cell.alignment    = align("right")
                        cell.number_format = zero_dash_fmt()
                    elif col == 1:
                        cell.alignment = align("center")
                    else:
                        cell.alignment = align("left")
                row_num += 1
                counter += 1

            # Payee subtotal
            sub_d = sum(t.get("debit")  or 0 for t in ptxns)
            sub_c = sum(t.get("credit") or 0 for t in ptxns)
            ws.append(["", f"Subtotal — {payee}", "", "", "",
                        sub_d if sub_d else None,
                        sub_c if sub_c else None, ""])
            for col, cell in enumerate(ws[row_num], start=1):
                cell.fill   = fill(COLOR_SUBTOTAL_BG)
                cell.font   = font(bold=True, size=10)
                cell.border = border()
                if col in (6, 7):
                    cell.alignment    = align("right")
                    cell.number_format = money_fmt()
                else:
                    cell.alignment = align("left")
            row_num += 1

        return row_num

    credits = [t for t in transactions if t.get("credit")]
    debits  = [t for t in transactions if t.get("debit")]
    row_num = 2

    row_num = _write_section(ws, "SECTION 1: BUYERS / PAYERS (Credits — Money IN)",
                             credits, row_num, COLOR_SECTION_CR)
    ws.append([""] * 8)   # spacer
    row_num += 1
    row_num = _write_section(ws, "SECTION 2: SUPPLIERS / VENDORS (Debits — Money OUT)",
                             debits, row_num, COLOR_SECTION_DR)

    ws.auto_filter.ref = f"A1:H{row_num}"
    return ws
```

## Sheet 4 — Daily Summary

```python
def write_daily_summary_sheet(wb, transactions):
    """
    One row per date.
    Columns: Date | DuitNow | CMS | RCMS | Transfer | IBG | Other | Daily Total | Count
    Only include type columns that have at least one non-zero value.
    """
    TYPES_ALL = ["DuitNow", "CMS", "RCMS", "Transfer", "IBG", "Other"]

    # Aggregate by date and type
    daily = OrderedDict()
    for t in transactions:
        d   = t.get("date", "Unknown")
        typ = classify_txn_type(t.get("description", ""))
        if d not in daily:
            daily[d] = {tp: 0.0 for tp in TYPES_ALL}
            daily[d]["_count"] = 0
        amt = (t.get("credit") or 0) + (t.get("debit") or 0)
        if typ not in TYPES_ALL:
            typ = "Other"
        daily[d][typ]    += amt
        daily[d]["_count"] += 1

    # Only keep types that have any data
    active_types = [tp for tp in TYPES_ALL
                    if any(daily[d][tp] != 0 for d in daily)]
    if not active_types:
        active_types = ["Other"]

    ws = wb.create_sheet("Daily Summary")
    HEADERS    = ["Date"] + [f"{tp} (RM)" for tp in active_types] + ["Daily Total (RM)", "Count"]
    COL_WIDTHS = [14]    + [14] * len(active_types)               + [16,                10]
    for i, w in enumerate(COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill      = fill(COLOR_HEADER_BG)
        cell.font      = font(bold=True, color=COLOR_HEADER_FONT, size=10)
        cell.alignment = align("center")
        cell.border    = border()
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    n_type_cols = len(active_types)
    row_num = 2
    for date, info in daily.items():
        amounts     = [info[tp] for tp in active_types]
        daily_total = sum(amounts)
        ws.append([date] + amounts + [daily_total, info["_count"]])

        for col, cell in enumerate(ws[row_num], start=1):
            cell.border = border()
            cell.font   = font(size=10)
            if col == 1:
                cell.fill      = fill(COLOR_DATE_BG)
                cell.alignment = align("center")
            elif col == n_type_cols + 2:   # Daily Total
                cell.fill          = fill(COLOR_SUBTOTAL_BG)
                cell.font          = font(bold=True, size=10)
                cell.alignment     = align("right")
                cell.number_format = money_fmt()
            elif col == n_type_cols + 3:   # Count
                cell.fill      = fill("FFFFFF")
                cell.alignment = align("center")
            else:
                cell.fill          = fill("FFFFFF")
                cell.alignment     = align("right")
                cell.number_format = zero_dash_fmt()
        row_num += 1

    # Grand total row
    totals    = [sum(daily[d][tp] for d in daily) for tp in active_types]
    g_total   = sum(totals)
    g_count   = sum(daily[d]["_count"] for d in daily)
    ws.append(["TOTAL"] + totals + [g_total, g_count])
    for col, cell in enumerate(ws[row_num], start=1):
        cell.fill   = fill(COLOR_SUBTOTAL_BG)
        cell.font   = font(bold=True, size=10)
        cell.border = border()
        if col == 1:
            cell.alignment = align("center")
        elif col == n_type_cols + 3:
            cell.alignment = align("center")
        else:
            cell.alignment     = align("right")
            cell.number_format = money_fmt()

    return ws
```

## Complete Export Function

```python
def export_to_excel(transactions, xlsx_path, meta):
    """
    transactions : list of dicts — page, date, description, payee, credit, debit, balance
    xlsx_path    : absolute output path
    meta         : dict — account_name, account_no, bank, period_from, period_to,
                          opening_bal, closing_bal, total_credits, total_debits,
                          txn_count, currency
    """
    wb = Workbook()

    write_transactions_sheet(wb, transactions)   # uses wb.active — must be first
    write_summary_sheet(wb, meta)                # inserts at position 0 (before Transactions)
    write_payee_buyer_sheet(wb, transactions)
    write_daily_summary_sheet(wb, transactions)

    wb.save(xlsx_path)
    print(f"Saved: {xlsx_path}")
    print(f"Sheets: {[ws.title for ws in wb.worksheets]}")
    print(f"Transactions: {len(transactions)}")
```

## Usage Notes

- Always call `write_transactions_sheet` first (it uses `wb.active`)
- `write_summary_sheet` inserts at position 0 — call it second so Summary becomes sheet 1
- `PatternFill` requires `fgColor` not `bgColor`
- Always call `ws.append()` BEFORE applying styles to that row
- `zero_dash_fmt()` is better than `money_fmt()` for columns that often have blanks/zeros (Credit, Debit, type breakdown)
- Column letters: use `get_column_letter(n)` for programmatic access (A=1, B=2…)
