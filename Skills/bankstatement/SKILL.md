---
name: bankstatement
description: "Bank statement PDF extraction reference for Malaysian banks (Maybank, CIMB, RHB, Public Bank, Hong Leong, AmBank). Contains: legal disclaimer filter list, page boundary markers, payee definition with examples, transaction type classification table, and verification formulas. Load this before extracting any bank statement PDF — it gives you the reference data you need to identify real transactions vs. noise."
---

# Bank Statement Extraction — Reference Data

This is a reference document. Use the data here as lookup material while you adapt your extraction logic to what you actually observe in the PDF.

---

## Legal Disclaimer Lines — Filter These Out

These lines appear after the last transaction on the final page (footer pollution). Drop any continuation line that contains these strings — they are never part of a transaction description:

```
Bank ini diberitahu
diberitahu atas sebarang
discrepancy within 14 days
Perhatian / Note ditandakan
BAKI LEGAR = BAKI AKHIR
Wang yang keluar berlebihan
All items and balances shown
Sila beritahu kami
Please notify us
可 应 用 存 于
此 对 账 单
本 欄 内 誌 DR
```

---

## Page Boundary Markers

### Header boundary (last line before transactions start on each page)
```
AMOUNT BALANCE
JUMLAH BAKI
TRANSACTION STATEMENT
```

### Footer boundary (first line after transactions end on each page)
```
BAKI LEGAR
LEDGER BALANCE =
ENDING BALANCE
END OF STATEMENT
```

Transactions appear only between the header boundary and the footer boundary. Skip everything outside this window on each page.

---

## Payee — What It Is

**Payee = the counterparty entity** (the person or company on the other side of the transaction). It is NOT the payment method or transaction type.

Why this matters: the "By Payee & Buyer" sheet groups by counterparty. A payee of "TRANSFER" or "DUITNOW" makes the grouping meaningless.

**Examples:**
- `"TRANSFER TO A/C RAJAWALI SDN BHD REF 20251101"` → Payee: `RAJAWALI SDN BHD`
- `"GIRO CREDIT FROM ACME CORPORATION 20251015"` → Payee: `ACME CORPORATION`
- `"SALARY PAYMENT"` → Payee: `SALARY PAYMENT` (no specific entity — keep as-is)

Observe the descriptions in this specific PDF first, then write extraction logic that fits its actual patterns.

---

## Transaction Type Classification

Use the raw first-line description to classify:

| Prefix | Type |
|--------|------|
| `DUITNOW...` | DuitNow |
| `CMS - DR...` or `CMS-DR...` | CMS |
| `RCMS - DR...` or `RCMS-DR...` | RCMS |
| `TRANSFER TO A/C...` or `TRANSFER FROM A/C...` or `INTERBANK TRANSFER...` | Transfer |
| `IBG FROM...` or `INTER-BANK PAYMENT...` or `GIRO CREDIT FROM...` | IBG |
| `ATM WITHDRAWAL...` | ATM (→ Other in Daily Summary) |
| `ESI PAYMENT...` or `SALARY PAYMENT...` | Salary (→ Other in Daily Summary) |
| anything else | Other |

---

## Verification Formulas

Always run both levels before reporting success:

**Level 1:** `opening_balance + Σcredits − Σdebits == closing_balance (±0.01)`

**Level 2:** For every row: `prev_balance + credit − debit == current_balance (±0.01)`

L1 fails → likely missing or double-counted transactions.  
L1 passes but L2 fails → likely one specific row has a parsing error.

---

## Common Pitfalls

**Multi-page continuations:** A transaction starting near the bottom of page N continues on page N+1 before that page's header. Concatenate all pages into one line stream after stripping per-page headers/footers — never process pages independently.

**Repeating headers:** Every page repeats the bank/account header block. Strip these before parsing.

**Amount format:** Malaysian statements use comma as thousands separator: `1,088.10`. Parse with `.replace(',', '')`.

**PDF column truncation:** Company names may be cut off with `*`. Keep what's there; do not guess the full name.
