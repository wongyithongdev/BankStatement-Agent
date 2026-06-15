# Bank Statement Extraction Agent

Extract and analyze financial transactions from bank statement PDFs using Claude AI with extended reasoning (MiMo-V2.5-Pro).

## Features

- **Autonomous PDF Analysis** — Investigates PDF structure, detects format patterns, extracts all transactions
- **Dual-Level Verification** — Level 1 (totals check) and Level 2 (row-by-row balance chain)
- **Multi-Sheet Excel Output** — Organized results with detailed analysis:
  - **Transactions** — 7 columns (Page, Date, Description, Payee, Credit, Debit, Balance) with color coding
  - **By Payee & Buyer** — Grouped ledger view with payee subtotals
  - **Daily Summary** — Daily breakdown by transaction type (DuitNow / CMS / RCMS / Transfer / IBG / Other)

## Installation

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```python
from agent.main import BankStatementAgent

agent = BankStatementAgent(
    api_key="your-anthropic-api-key",
    model="claude-opus-4-8",  # or mime-v2.5-pro
)

result = agent.extract("path/to/bank_statement.pdf")

if result["status"] == "completed":
    print(f"✅ Generated: {result['xlsx_path']}")
    print(f"Transactions: {result['transaction_count']}")
else:
    print(f"⚠️ Status: {result['status']}")
```

## Configuration

Set API key via environment variable:
```bash
export ANTHROPIC_API_KEY="your-key"
```

## Architecture

- **Agent Loop** — Code-first agentic pattern: model writes Python → harness executes → agent adapts
- **Tools**
  - `read_skills_doc(skill)` — Load PDF/Excel skill documentation
  - `run_python(code)` — Execute Python scripts for investigation and extraction
- **System Prompt** — Guides agent through investigation → extraction → verification → export

## Supported Banks

Currently tested with:
- Maybank (Malaysia) — 12-page statements with multi-page transactions

## Output Format

All output is **XLSX only** (Excel 2007+):
- Color-coded rows (green = credit, orange = debit)
- Frozen header rows, auto-filters, number formatting
- Grouped sheets for easy analysis

## Verification

All extracted transactions are verified at two levels:
1. **Level 1** — opening_balance + credits - debits = closing_balance (±0.01 tolerance)
2. **Level 2** — each row's running balance chain (±0.01 tolerance per row)

Both must pass before export.

## License

MIT
