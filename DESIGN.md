# pFile — Design Document

**pFile (paper-file)** is an open-source Python package for automating the preparation and paper filing of US federal income taxes. Users provide their documents (W-2s, K-1s, 1099s), answer an interview, and receive a ready-to-mail package of filled IRS PDF forms with a cover sheet and payment instructions.

---

## Goals

- Automate the tedious parts: extracting data from documents, computing the return, and filling PDF forms
- Support paper filing by mail as the primary output (no e-file)
- Be fully local — no data leaves the user's machine except OpenAI API calls for LLM parsing
- Be open source and auditable — all tax logic is readable Python, not a black box
- CLI-first; NiceGUI web UI in Phase 2

## Non-Goals

- E-filing (no IRS MeF integration)
- State tax returns beyond New York (federal + NY only)
- Tax advice or audit support
- Multi-user or cloud hosting (Phase 1)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   CLI / Web UI                      │
│         (questionary + rich / NiceGUI)              │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│                  FilingSession                      │
│         (persisted JSON, one per filer/year)        │
└──┬──────────────┬─────────────────┬─────────────────┘
   │              │                 │
┌──▼───┐   ┌──────▼──────┐   ┌─────▼──────┐
│Parse │   │   Compute   │   │   Output   │
│docs  │   │  tax return │   │  package   │
└──────┘   └─────────────┘   └────────────┘
```

### Data flow

1. **Interview** — gather taxpayer info and filing status
2. **Ingest** — upload documents; parsers extract structured data
3. **Review** — user confirms/corrects extracted fields
4. **Compute** — tax engine calculates AGI, taxable income, tax owed, credits, balance
5. **Fill** — PDF engine writes computed values into blank IRS form templates
6. **Package** — assembles filled PDFs + cover sheet + voucher into a downloadable ZIP

---

## Filing Session

A `FilingSession` is the central state object. It is persisted to a JSON file at `~/.pfile/sessions/<id>.json` and can be resumed at any time.

```python
class FilingSession(BaseModel):
    id: str                        # UUID
    tax_year: int
    filing_status: FilingStatus    # SINGLE | MFJ | MFS | HOH | QSS
    primary: TaxpayerProfile
    spouse: SpouseProfile | None   # MFJ / MFS only
    documents: list[AnyDocument]   # W2s, K1s, 1099s, etc.
    computed: ComputedReturn | None
    status: SessionStatus          # DRAFT | REVIEWED | COMPLETE
    created_at: datetime
    updated_at: datetime
```

---

## Models

### Filer

```
TaxpayerProfile   — name, SSN, DOB, address, occupation
SpouseProfile     — same fields
DependentProfile  — name, SSN, DOB, relationship
```

### Documents (input)

```
W2                — wages, federal/state withholding, box 12/14 codes
K1_1065           — partnership pass-through (all boxes)
K1_1120S          — S-corp pass-through (all boxes)
F1099_INT         — interest income
F1099_DIV         — dividends
F1099_B           — brokerage proceeds (aggregated)
F1099_R           — retirement distributions
F1099_SSA         — social security benefits
```

### Computed forms (output)

```
Form1040          — the main federal return
ScheduleB         — interest and ordinary dividends
ScheduleD         — capital gains and losses
ScheduleE         — supplemental income (K-1 pass-through)
ScheduleSE        — self-employment tax
ComputedReturn    — top-level: AGI, taxable income, tax, credits, balance due/refund

IT201             — NY resident income tax return
IT2               — NY summary of W-2 statements
ComputedNYReturn  — NY AGI, NY tax, NYC/Yonkers tax, credits, balance due/refund
```

---

## Parsers

Each parser implements the `BaseParser` interface:

```python
class BaseParser(ABC):
    @abstractmethod
    def parse(self, file: Path) -> AnyDocument: ...
    
    @property
    @abstractmethod
    def confidence(self) -> dict[str, float]: ...  # field → 0.0–1.0
```

| Document | Strategy |
|----------|----------|
| W-2 | `pdfplumber` — fields are in fixed positions; structured extraction |
| K-1 (1065/1120S) | GPT-4o vision — convert pages to images, extract to JSON schema |
| 1099-INT/DIV | `pdfplumber` with LLM fallback for non-standard layouts |
| 1099-B | `pdfplumber` for totals; LLM for complex lot-by-lot sheets |
| 1099-R / SSA | `pdfplumber` — well-structured forms |

### LLM parsing details

- PDF pages converted to images via `pdf2image`
- Sent to GPT-4o with a structured output schema (JSON mode)
- Fields with confidence < 0.8 are flagged for manual review in the interview
- API key loaded from `OPENAI_API_KEY` environment variable

---

## Compute Engine

All computation is pure Python with no side effects. Each module takes models in and returns models out.

```
agi.py          gross_income(docs) → agi(adjustments)
deductions.py   standard_deduction(profile, year) | itemized(docs)
tax.py          tax_from_brackets(taxable_income, status, year)
credits.py      child_tax_credit | earned_income | education
schedules/
  b.py          interest + dividends → Schedule B totals
  d.py          capital transactions → Schedule D / net gain/loss
  e.py          K-1 pass-through → Schedule E income/loss
  se.py         self-employment income → SE tax
```

Tax bracket data, standard deduction amounts, phase-out thresholds, and contribution limits are stored as YAML in `data/brackets/<year>.yaml` — no magic numbers in code.

---

## PDF Form Filling

Blank fillable IRS PDFs are stored in `data/forms/<year>/`. Each form has a corresponding YAML field map:

```yaml
# data/forms/2025/1040.yaml
fields:
  filing_status_single:    "topmostSubform[0].Page1[0].FilingStatus[0].c1_1[0]"
  first_name:              "topmostSubform[0].Page1[0].f1_1[0]"
  ssn:                     "topmostSubform[0].Page1[0].f1_3[0]"
  line_1a_wages:           "topmostSubform[0].Page1[0].f1_25[0]"
  # ...
```

The fill engine uses `pypdf` to write values into PDF fields by name. Checkboxes, dropdowns, and text fields are all supported.

---

## New York State

NY state tax is computed after the federal return since it starts from federal AGI.

### NY-specific filer data

```python
class NYResidencyInfo(BaseModel):
    full_year_resident: bool
    county: str
    nyc_resident: bool       # triggers NYC local tax (~3.08–3.876%)
    yonkers_resident: bool   # triggers Yonkers surcharge
```

### Compute flow

```
federal AGI
  → NY additions (e.g. state/local bond interest)
  → NY subtractions (e.g. pension exclusions, college savings)
  = NY AGI
  → NY standard or itemized deduction
  = NY taxable income
  → NY tax from brackets
  → NYC tax (if NYC resident)
  → Yonkers surcharge (if Yonkers resident)
  → NY credits
  = NY balance due / refund
```

### NY forms (Phase 1)

| Form | Description |
|------|-------------|
| IT-201 | Full-year resident income tax return |
| IT-2 | Summary of W-2 statements (attachment) |
| IT-201-V | Payment voucher (if balance due) |

Data files:
- `data/brackets/ny/2025.yaml` — NY income tax brackets + NYC + Yonkers rates
- `data/forms/ny/2025/` — blank NY DTF fillable PDFs + YAML field maps
- `data/mailing/ny_dtf.yaml` — NY DTF mailing addresses by return type

---

## Output Package

Running `pfile generate <session-id>` produces a ZIP at `~/.pfile/output/<session-id>.zip`:

```
<session-id>/
├── federal/
│   ├── 1040.pdf              # Filled Form 1040
│   ├── schedule_b.pdf        # (if applicable)
│   ├── schedule_d.pdf        # (if applicable)
│   ├── schedule_e.pdf        # (if applicable)
│   ├── 1040v.pdf             # Payment voucher (if balance due)
│   └── cover_sheet.pdf       # IRS mailing address, ordering, payment instructions
├── ny_state/
│   ├── it201.pdf             # Filled NY IT-201
│   ├── it2.pdf               # Filled NY IT-2 (W-2 summary)
│   ├── it201v.pdf            # NY payment voucher (if balance due)
│   └── cover_sheet.pdf       # NY DTF mailing address, ordering, payment instructions
└── README.txt                # Plain-text summary of both returns
```

### Cover sheet contents

- Correct IRS service center mailing address (derived from filer's state + return type)
- Document ordering per IRS instructions ("attach in order shown")
- If balance due: amount owed, due date, how to make check payable, where to mail payment
- If refund: expected processing time for paper returns
- Checklist before sealing the envelope

---

## CLI

```bash
# Install
pip install pfile

# Start a new session (interactive interview)
pfile new

# Resume an existing session
pfile resume <session-id>

# List all sessions
pfile list

# Generate output package for a completed session
pfile generate <session-id>

# Show session summary
pfile show <session-id>
```

---

## Project Structure

```
pfile/
├── pyproject.toml
├── README.md
├── DESIGN.md
├── src/
│   └── pfile/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── main.py          # Typer app, all commands
│       ├── models/
│       │   ├── __init__.py
│       │   ├── filer.py
│       │   ├── session.py
│       │   ├── documents.py
│       │   └── forms.py
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── w2.py
│       │   ├── k1.py
│       │   ├── f1099.py
│       │   └── llm.py           # Shared LLM client + prompt utilities
│               ├── compute/
│       │   ├── __init__.py
│       │   ├── agi.py
│       │   ├── deductions.py
│       │   ├── tax.py
│       │   ├── credits.py
│       │   ├── schedules/
│       │   │   ├── __init__.py
│       │   │   ├── b.py
│       │   │   ├── d.py
│       │   │   ├── e.py
│       │   │   └── se.py
│       │   └── state/
│       │       ├── __init__.py
│       │       └── ny.py            # NY IT-201, NYC/Yonkers local tax
│       ├── forms/
│       │   ├── __init__.py
│       │   └── engine.py
│       ├── output/
│       │   ├── __init__.py
│       │   ├── cover.py
│       │   ├── voucher.py
│       │   └── package.py
│       ├── interview/
│       │   ├── __init__.py
│       │   └── steps.py         # Interview step definitions
│       └── session/
│           ├── __init__.py
│           └── store.py         # Load/save sessions to ~/.pfile/
├── data/
│   ├── forms/
│   │   ├── federal/2025/        # Blank IRS fillable PDFs + YAML field maps
│   │   └── ny/2025/             # Blank NY DTF fillable PDFs + YAML field maps
│   ├── brackets/
│   │   ├── federal/2025.yaml
│   │   └── ny/2025.yaml         # NY state + NYC + Yonkers brackets
│   └── mailing/
│       ├── irs_service_centers.yaml   # IRS addresses by state + return type
│       └── ny_dtf.yaml                # NY DTF mailing addresses
└── tests/
    ├── conftest.py
    ├── models/
    ├── parsers/
    ├── compute/
    └── output/
```

---

## Phase Roadmap

### Phase 1 — CLI + core forms
- Filing statuses: Single, MFJ, MFS, HOH, QSS
- Documents: W-2, K-1 (1065), K-1 (1120S), 1099-INT, 1099-DIV, 1099-R, SSA-1099
- Federal forms: 1040, Schedule B, Schedule E
- NY state forms: IT-201, IT-2 (W-2 summary); NYC / Yonkers local tax
- Output: filled PDFs + federal & state cover sheets + 1040-V / IT-201-V vouchers

### Phase 2 — Extended forms + NiceGUI
- Add Schedule D, 8949, 1099-B
- Add Schedule SE, self-employment income
- NiceGUI web UI wrapping the same core logic
- Session management UI

### Phase 3 — Credits + deductions
- Child Tax Credit (8812)
- Education credits (8863)
- QBI deduction (Form 8995)
- Itemized deductions (Schedule A)

### Phase 4 — TurboTax import + multi-year
- Ingest TurboTax PDF exports to pre-populate a session
- Multi-year support (2024+)
- AMT (Form 6251)

---

## Tech Stack

| Concern | Library |
|---------|---------|
| CLI | Typer |
| Terminal output | Rich |
| CLI prompts | Questionary |
| Data models | Pydantic v2 |
| PDF parsing | pdfplumber |
| PDF → images (LLM) | pdf2image |
| PDF filling | pypdf |
| PDF generation (cover) | ReportLab |
| LLM | openai (GPT-4o) |
| Session storage | JSON (`~/.pfile/`) |
| Package manager | Poetry |
| Testing | pytest |
| Phase 2 UI | NiceGUI |

---

## Open Source

License: MIT
