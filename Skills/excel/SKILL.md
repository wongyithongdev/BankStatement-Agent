---
name: excel
description: Use this skill whenever you need to write Excel (XLSX) files with formatting, colors, multiple sheets, summaries, or charts using openpyxl. Covers: cell colors, bold/italic fonts, column widths, frozen panes, borders, number formats, and building daily summary sheets from transaction data.
license: MIT
---

# Excel Formatting & Summary Guide (openpyxl)

## Core Imports

```python
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter
```

## Color Constants (bank statement standard palette)

```python
# Header
COLOR_HEADER_BG   = "1F3864"   # dark navy blue
COLOR_HEADER_FONT = "FFFFFF"   # white

# Transaction rows
COLOR_CREDIT_BG   = "E2EFDA"   # light green  — credit rows
COLOR_DEBIT_BG    = "FCE4D6"   # light orange — debit rows
COLOR_ALT_BG      = "F2F2F2"   # light grey   — alternating blank rows

# Summary sheets
COLOR_NET_POS     = "C6EFCE"   # green  — positive net
COLOR_NET_NEG     = "FFC7CE"   # pink   — negative net
COLOR_TOTAL_BG    = "BDD7EE"   # light blue — total row

# Borders
BORDER_COLOR      = "BFBFBF"
```

## Helper Functions

```python
def make_fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def make_font(bold=False, color="000000", size=10):
    return Font(bold=bold, color=color, size=size, name="Calibri")

def make_border():
    side = Side(style="thin", color=BORDER_COLOR)
    return Border(left=side, right=side, top=side, bottom=side)

def make_center():
    return Alignment(horizontal="center", vertical="center", wrap_text=False)

def make_left():
    return Alignment(horizontal="left", vertical="center", wrap_text=False)
```

## Sheet 1 — Transactions (colored rows, formatted header)

```python
def write_transactions_sheet(wb, transactions):
    """
    transactions: list of dicts with keys:
        page, date, description, payee, credit, debit, balance
    """
    ws = wb.active
    ws.title = "Transactions"

    HEADERS = ["Page", "Date", "Description", "Payee", "Credit", "Debit", "Balance"]

    # --- Column widths ---
    col_widths = [6, 14, 50, 28, 12, 12, 14]
    for i, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # --- Header row ---
    ws.append(HEADERS)
    for col, cell in enumerate(ws[1], start=1):
        cell.fill  = make_fill(COLOR_HEADER_BG)
        cell.font  = make_font(bold=True, color=COLOR_HEADER_FONT, size=10)
        cell.alignment = make_center()
        cell.border = make_border()
    ws.row_dimensions[1].height = 20

    # Freeze header row
    ws.freeze_panes = "A2"

    # --- Transaction rows ---
    for i, t in enumerate(transactions, start=2):
        is_credit = bool(t.get("credit"))
        row_color = COLOR_CREDIT_BG if is_credit else COLOR_DEBIT_BG

        ws.append([
            t["page"],
            t["date"],
            t["description"],
            t["payee"],
            t["credit"] if t.get("credit") else "",
            t["debit"]  if t.get("debit")  else "",
            t["balance"],
        ])

        for col, cell in enumerate(ws[i], start=1):
            cell.fill      = make_fill(row_color)
            cell.border    = make_border()
            cell.font      = make_font(size=10)
            cell.alignment = make_left()

            # Right-align and format numeric columns
            if col in (1, 5, 6, 7):   # Page, Credit, Debit, Balance
                cell.alignment = make_center() if col == 1 else Alignment(horizontal="right")
                if col in (5, 6, 7) and cell.value != "":
                    cell.number_format = '#,##0.00'

    # Auto-filter
    ws.auto_filter.ref = f"A1:G{len(transactions) + 1}"

    return ws
```

## Sheet 2 — Daily Summary

```python
from collections import defaultdict

def write_daily_summary_sheet(wb, transactions, opening_balance):
    ws = wb.create_sheet("Daily Summary")

    HEADERS = ["Date", "Credits", "Debits", "Net", "Closing Balance", "Txn Count"]
    col_widths = [14, 14, 14, 14, 16, 10]
    for i, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # Header
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill = make_fill(COLOR_HEADER_BG)
        cell.font = make_font(bold=True, color=COLOR_HEADER_FONT)
        cell.alignment = make_center()
        cell.border = make_border()
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"

    # Group by date (preserve order)
    from collections import OrderedDict
    daily = OrderedDict()
    for t in transactions:
        d = t["date"]
        if d not in daily:
            daily[d] = {"credits": 0.0, "debits": 0.0, "count": 0, "last_balance": None}
        daily[d]["credits"] += t.get("credit") or 0
        daily[d]["debits"]  += t.get("debit")  or 0
        daily[d]["count"]   += 1
        daily[d]["last_balance"] = t["balance"]

    row_num = 2
    for date, info in daily.items():
        net = info["credits"] - info["debits"]
        closing = info["last_balance"]
        ws.append([date, info["credits"], info["debits"], net, closing, info["count"]])

        net_color = COLOR_NET_POS if net >= 0 else COLOR_NET_NEG

        for col, cell in enumerate(ws[row_num], start=1):
            cell.border    = make_border()
            cell.font      = make_font()
            if col == 1:
                cell.alignment = make_center()
                cell.fill = make_fill("EBF3FB")  # light blue date column
            elif col == 4:
                cell.fill = make_fill(net_color)
                cell.alignment = Alignment(horizontal="right")
                cell.number_format = '#,##0.00'
                cell.font = make_font(bold=True)
            elif col in (2, 3, 5):
                cell.alignment = Alignment(horizontal="right")
                cell.number_format = '#,##0.00'
                cell.fill = make_fill("FFFFFF")
            elif col == 6:
                cell.alignment = make_center()
                cell.fill = make_fill("FFFFFF")

        row_num += 1

    # Total row
    total_credits = sum(d["credits"] for d in daily.values())
    total_debits  = sum(d["debits"]  for d in daily.values())
    total_net     = total_credits - total_debits
    ws.append(["TOTAL", total_credits, total_debits, total_net, "", sum(d["count"] for d in daily.values())])

    for col, cell in enumerate(ws[row_num], start=1):
        cell.fill   = make_fill(COLOR_TOTAL_BG)
        cell.font   = make_font(bold=True)
        cell.border = make_border()
        if col in (2, 3, 4):
            cell.alignment = Alignment(horizontal="right")
            cell.number_format = '#,##0.00'
        elif col == 6:
            cell.alignment = make_center()
        else:
            cell.alignment = make_center()

    return ws
```

## Transaction Type Classification

Before building summary sheets, classify each transaction by type based on the raw Description field.

```python
def classify_txn_type(description):
    """
    Classify a transaction by its description prefix.
    Returns one of: "DuitNow", "CMS", "RCMS", "Transfer", "IBG", "ATM", "Salary", "Other"
    """
    desc = description.upper().strip()
    if desc.startswith("DUITNOW"):
        return "DuitNow"
    elif desc.startswith("CMS -") or desc.startswith("CMS-"):
        return "CMS"
    elif desc.startswith("RCMS -") or desc.startswith("RCMS-"):
        return "RCMS"
    elif desc.startswith("TRANSFER TO") or desc.startswith("TRANSFER FROM") or desc.startswith("INTERBANK TRANSFER"):
        return "Transfer"
    elif desc.startswith("IBG FROM") or desc.startswith("INTER-BANK PAYMENT") or desc.startswith("GIRO CREDIT"):
        return "IBG"
    elif desc.startswith("ATM WITHDRAWAL"):
        return "ATM"
    elif desc.startswith("SALARY PAYMENT"):
        return "Salary"
    else:
        return "Other"
```

## Sheet 3 — By Payee & Buyer (detailed transactions grouped by entity)

This sheet lists every individual transaction grouped by payee/payer — like a general ledger view.
Structure: Section header → Payee group header → individual transaction rows → payee subtotal → next payee.

```python
def write_payee_buyer_sheet(wb, transactions):
    """
    Produces a detailed ledger grouped by Payee.
    SECTION 1: BUYERS/PAYERS  — credit transactions (money IN)
    SECTION 2: SUPPLIERS/VENDORS — debit transactions (money OUT)
    """
    ws = wb.create_sheet("By Payee & Buyer")

    HEADERS = ["No.", "Date", "Description", "Payee", "Type", "Debit (RM)", "Credit (RM)", "Balance (RM)"]
    col_widths = [6, 14, 48, 28, 12, 14, 14, 14]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill      = make_fill(COLOR_HEADER_BG)
        cell.font      = make_font(bold=True, color=COLOR_HEADER_FONT)
        cell.alignment = make_center()
        cell.border    = make_border()
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"

    from collections import OrderedDict

    def _write_section(ws, section_label, txns, start_row, section_color):
        row_num = start_row

        # Section header row (full-width merge-style via fill)
        ws.append([section_label, "", "", "", "", "", "", ""])
        for col, cell in enumerate(ws[row_num], start=1):
            cell.fill      = make_fill(section_color)
            cell.font      = make_font(bold=True, size=11, color="FFFFFF")
            cell.border    = make_border()
            cell.alignment = make_left()
        row_num += 1

        # Group by payee (preserve encounter order)
        by_payee = OrderedDict()
        for t in txns:
            by_payee.setdefault(t["payee"], []).append(t)

        counter = 1
        for payee, ptxns in by_payee.items():
            # Payee group header
            ws.append([payee, "", "", "", "", "", "", ""])
            for col, cell in enumerate(ws[row_num], start=1):
                cell.fill      = make_fill("D9E1F2")   # soft blue group header
                cell.font      = make_font(bold=True)
                cell.border    = make_border()
                cell.alignment = make_left()
            row_num += 1

            # Individual transactions
            for t in ptxns:
                txn_type = classify_txn_type(t["description"])
                is_credit = bool(t.get("credit"))
                row_color = COLOR_CREDIT_BG if is_credit else COLOR_DEBIT_BG
                ws.append([
                    counter,
                    t["date"],
                    t["description"][:60],
                    t["payee"],
                    txn_type,
                    t["debit"]  if t.get("debit")  else "",
                    t["credit"] if t.get("credit") else "",
                    t["balance"],
                ])
                for col, cell in enumerate(ws[row_num], start=1):
                    cell.fill   = make_fill(row_color)
                    cell.border = make_border()
                    cell.font   = make_font(size=10)
                    if col in (6, 7, 8):
                        cell.alignment = Alignment(horizontal="right")
                        if cell.value != "":
                            cell.number_format = '#,##0.00'
                    elif col == 1:
                        cell.alignment = make_center()
                    else:
                        cell.alignment = make_left()
                row_num += 1
                counter += 1

            # Payee subtotal row
            sub_debit  = sum(t.get("debit")  or 0 for t in ptxns)
            sub_credit = sum(t.get("credit") or 0 for t in ptxns)
            ws.append(["", f"Subtotal — {payee}", "", "", "", sub_debit or "", sub_credit or "", ""])
            for col, cell in enumerate(ws[row_num], start=1):
                cell.fill   = make_fill(COLOR_TOTAL_BG)
                cell.font   = make_font(bold=True)
                cell.border = make_border()
                if col in (6, 7):
                    cell.alignment = Alignment(horizontal="right")
                    if cell.value != "":
                        cell.number_format = '#,##0.00'
                else:
                    cell.alignment = make_left()
            row_num += 1

        return row_num

    # SECTION 1: Credits (buyers/payers — money IN)
    credit_txns = [t for t in transactions if t.get("credit")]
    row_num = 2
    row_num = _write_section(ws, "SECTION 1: BUYERS / PAYERS (Credits)", credit_txns, row_num, "375623")

    # Blank spacer row
    ws.append([""] * 8)
    row_num += 1

    # SECTION 2: Debits (suppliers/vendors — money OUT)
    debit_txns = [t for t in transactions if t.get("debit")]
    row_num = _write_section(ws, "SECTION 2: SUPPLIERS / VENDORS (Debits)", debit_txns, row_num, "843C0C")

    ws.auto_filter.ref = f"A1:H{row_num}"
    return ws
```

## Sheet 4 — Daily Summary by Transaction Type

Columns break down each day by transaction type (DuitNow / CMS / RCMS / Transfer / IBG / Other),
matching the JVS Trading Payment Summary format.

```python
def write_daily_type_summary_sheet(wb, transactions):
    """
    Daily summary with columns per transaction type.
    Mirrors: Date | DuitNow | CMS | RCMS | Transfer | IBG | Other | Daily Total | Txn Count
    """
    ws = wb.create_sheet("Daily Summary")

    TYPES   = ["DuitNow", "CMS", "RCMS", "Transfer", "IBG", "Other"]
    HEADERS = ["Date"] + [f"{t} (RM)" for t in TYPES] + ["Daily Total (RM)", "Txn Count"]
    col_widths = [14] + [14] * len(TYPES) + [16, 10]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill      = make_fill(COLOR_HEADER_BG)
        cell.font      = make_font(bold=True, color=COLOR_HEADER_FONT)
        cell.alignment = make_center()
        cell.border    = make_border()
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"

    from collections import OrderedDict
    daily = OrderedDict()
    for t in transactions:
        d = t["date"]
        if d not in daily:
            daily[d] = {typ: 0.0 for typ in TYPES}
            daily[d]["count"] = 0
        txn_type = classify_txn_type(t["description"])
        amount   = (t.get("credit") or 0) + (t.get("debit") or 0)
        bucket   = txn_type if txn_type in TYPES else "Other"
        daily[d][bucket] += amount
        daily[d]["count"] += 1

    row_num = 2
    for date, info in daily.items():
        type_amounts = [info[typ] for typ in TYPES]
        daily_total  = sum(type_amounts)
        ws.append([date] + type_amounts + [daily_total, info["count"]])

        for col, cell in enumerate(ws[row_num], start=1):
            cell.border = make_border()
            cell.font   = make_font()
            if col == 1:
                cell.fill      = make_fill("EBF3FB")
                cell.alignment = make_center()
            elif col == len(HEADERS):     # Txn Count
                cell.fill      = make_fill("FFFFFF")
                cell.alignment = make_center()
            elif col == len(HEADERS) - 1: # Daily Total
                cell.fill      = make_fill(COLOR_TOTAL_BG)
                cell.font      = make_font(bold=True)
                cell.alignment = Alignment(horizontal="right")
                cell.number_format = '#,##0.00'
            else:
                cell.fill      = make_fill("FFFFFF")
                cell.alignment = Alignment(horizontal="right")
                if cell.value:
                    cell.number_format = '#,##0.00'
        row_num += 1

    # Grand total row
    grand = {typ: sum(daily[d][typ] for d in daily) for typ in TYPES}
    grand_total = sum(grand.values())
    grand_count = sum(daily[d]["count"] for d in daily)
    ws.append(["TOTAL"] + [grand[typ] for typ in TYPES] + [grand_total, grand_count])
    for col, cell in enumerate(ws[row_num], start=1):
        cell.fill   = make_fill(COLOR_TOTAL_BG)
        cell.font   = make_font(bold=True)
        cell.border = make_border()
        if col > 1:
            cell.alignment = Alignment(horizontal="right")
            if col < len(HEADERS):
                cell.number_format = '#,##0.00'
        else:
            cell.alignment = make_center()

    return ws
```

## Complete Export Function

```python
def export_to_excel(transactions, xlsx_path, opening_balance):
    """
    transactions: list of dicts — page, date, description, payee, credit, debit, balance
    xlsx_path: absolute path to output file
    opening_balance: float — the opening balance of the statement period
    """
    wb = Workbook()

    write_transactions_sheet(wb, transactions)
    write_payee_buyer_sheet(wb, transactions)
    write_daily_type_summary_sheet(wb, transactions)

    wb.save(xlsx_path)
    print(f"Saved {len(transactions)} transactions to {xlsx_path}")
    print(f"Sheets: {[ws.title for ws in wb.worksheets]}")
```

## Important Notes

- `PatternFill` requires `fgColor` (not `bgColor`) for solid fills
- Number format `'#,##0.00'` adds comma separators and 2 decimal places
- `freeze_panes = "A2"` freezes the header row
- Always call `ws.append()` BEFORE applying styles to that row
- Column letters: A=1, B=2, ... use `get_column_letter(n)` for programmatic access
- `auto_filter.ref` must cover the full range including header
