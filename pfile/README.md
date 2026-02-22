# pFile

**pFile (paper-file)** is an open-source Python tool for automating US federal income tax preparation and paper filing.

Provide your tax documents (W-2s, K-1s, 1099s), answer a short interview, and receive a ready-to-mail package of filled IRS PDF forms with a cover sheet and payment instructions.

> **Status:** Early development. See [DESIGN.md](../DESIGN.md) for the full design.

## Features

- Extracts data from W-2s and 1099s automatically (pdfplumber)
- Parses K-1s using GPT-4o vision
- Fills official IRS PDF forms programmatically
- Supports Single, MFJ, MFS, HOH, and QSS filing statuses
- Outputs a ZIP with all filled forms, a cover sheet, and payment instructions

## Installation

```bash
pip install pfile
```

Requires an OpenAI API key for K-1 parsing:

```bash
export OPENAI_API_KEY=sk-...
```

## Usage

```bash
# Start a new filing session
pfile new

# Resume a saved session
pfile resume <session-id>

# List all sessions
pfile list

# Generate the output package
pfile generate <session-id>
```

## Supported forms (Phase 1)

- Form 1040
- Schedule B (interest & dividends)
- Schedule E (K-1 pass-through income)
- W-2, K-1 (Form 1065), K-1 (Form 1120S)
- 1099-INT, 1099-DIV, 1099-R, SSA-1099

## License

MIT
