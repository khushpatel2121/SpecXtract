# Conduit

> Automated vendor spec sheet extraction pipeline for construction and electrical equipment.
> Converts raw vendor PDFs into structured, validated JSON — ready for AI agents to reason over.

---

## What It Does

Construction contractors and electrical distributors work with hundreds of vendor
spec sheets from manufacturers like Siemens, Schneider Electric, and Eaton. Every
sheet contains critical product data — voltage ratings, current ratings, certifications,
dimensions, operating temperatures — locked inside an unstructured PDF.

Conduit unlocks it automatically. Drop a PDF in, get structured JSON out.

```
siemens_3VA1_circuit_breaker.pdf  →  siemens_3VA1_circuit_breaker.json
schneider_QBL32100_breaker.pdf    →  schneider_QBL32100_breaker.json
eaton_HJD3100_breaker.pdf         →  eaton_HJD3100_breaker.json
```

---

## How It Works

Conduit runs a three-layer extraction pipeline. Exact methods run first,
intelligent fallback runs last.

```
PDF
 │
 ├── pdf_inspector     Profiles each page — text-native or scanned?
 │
 ├── ocr_engine        Rasterises + OCRs scanned pages (pytesseract)
 │
 ├── Layer 1           camelot + pdfplumber — exact table extraction
 │                     Reads what is literally in table cells. No inference.
 │
 ├── Layer 2           Regex patterns — catches fields outside tables
 │                     Part numbers, certifications, temperatures in prose.
 │
 └── Layer 3           Groq LLM (llama-3.3-70b) — fills remaining gaps
                       Only runs for fields still missing after Layers 1 & 2.
                       Free API, no credit card needed.
```

Every extracted field is tagged with its source layer so you can audit
exactly where each value came from.

---

## Project Structure

```
conduit/
│
├── main.py                      CLI entry point
├── requirements.txt
├── .env.example                 Environment variable template
│
├── src/
│   ├── schema.py                Data model — SpecSheet dataclass, 29 core fields
│   ├── pdf_inspector.py         Detects text-native vs scanned per page
│   ├── ocr_engine.py            pytesseract OCR for scanned pages
│   ├── table_extractor.py       Layer 1 — camelot + pdfplumber
│   ├── regex_extractor.py       Layer 2 — 28 targeted regex patterns
│   ├── llm_extractor.py         Layer 3 — Groq LLM fallback
│   └── pipeline.py              Orchestrator
│
├── data/
│   ├── raw_pdfs/                Input  — drop vendor PDFs here
│   ├── extracted_text/          Intermediate — plain text from pdfplumber/OCR
│   └── structured_json/         Output — one JSON file per processed PDF
│
├── tests/
│   ├── make_scanned_pdf.py      Generates synthetic scanned PDF for OCR testing
│   └── ...
│
└── logs/
    └── pipeline.log
```

---

## Quickstart

### 1. Clone and set up environment

```bash
git clone https://github.com/your-org/conduit.git
cd conduit

python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. Install system dependencies

**Ubuntu / Debian**
```bash
sudo apt install tesseract-ocr poppler-utils
```

**macOS**
```bash
brew install tesseract poppler
```

**Windows**
- Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
- Poppler: https://github.com/oschwartz10612/poppler-windows/releases
- Add both to your system `PATH`

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and add your Groq API key:

```
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

Get a free key at **console.groq.com** — no credit card required.

### 4. Add vendor PDFs

Drop any vendor spec sheet PDFs into `data/raw_pdfs/`.

Tested with spec sheets from:
- Siemens (3VA series molded case circuit breakers)
- Schneider Electric / Square D (QBL series)
- Eaton (HJD series)
- ABB (AF series contactors — scanned)

### 5. Run

**Single PDF**
```bash
python main.py run data/raw_pdfs/siemens_3VA1_circuit_breaker.pdf
```

**Entire folder**
```bash
python main.py batch data/raw_pdfs/
```

---

## Output

Each processed PDF produces a JSON file in `data/structured_json/`.

```json
{
  "manufacturer": "Siemens",
  "product_name": "3VA1 Molded Case Circuit Breaker",
  "part_number": "3VA1110-4ED32-0AA0",
  "electrical": {
    "voltage_rating": "480V AC",
    "current_rating": "100A",
    "frequency": "50/60 Hz",
    "interrupting_capacity": "65 kA",
    "pole_configuration": "3-pole",
    "trip_type": "Thermal-magnetic"
  },
  "physical": {
    "width_mm": "76.2",
    "height_mm": "130",
    "depth_mm": "70",
    "weight_kg": "0.91",
    "mounting_type": "DIN rail / bolt-on",
    "enclosure_rating": "IP20"
  },
  "environmental": {
    "operating_temp_min": "-25°C",
    "operating_temp_max": "+70°C",
    "humidity_max": "95% non-condensing",
    "altitude_max": "2000 m",
    "pollution_degree": "Pollution Degree 3"
  },
  "certifications": ["UL 489", "CSA C22.2 No.5", "CE"],
  "compliance_standards": ["NEC 2023 Article 240"],
  "metadata": {
    "strategy": "text_native",
    "fields_from_table": 18,
    "fields_from_regex": 4,
    "fields_from_llm": 2,
    "confidence": 0.827,
    "missing_fields": ["catalog_number", "list_price"],
    "field_sources": {
      "electrical.voltage_rating": "table",
      "electrical.current_rating": "table",
      "manufacturer": "regex",
      "description": "llm"
    }
  }
}
```

---

## Extraction Layers

### Layer 1 — Tables (camelot + pdfplumber)

The primary extractor. Most electrical spec data lives in ruled tables.
Camelot uses computer vision edge detection to find table geometry and extract
cell values exactly as written — no inference, no guessing.

- **camelot lattice** — for tables with drawn borders (most vendor datasheets)
- **camelot stream** — fallback for whitespace-separated tables
- **pdfplumber** — final fallback using PDF geometry directly

A vocabulary of ~90 label variants maps every manufacturer's wording to the
correct field. `"In"`, `"Ie"`, `"Rated current"`, `"Ampere rating"` all map
to `electrical.current_rating`.

### Layer 2 — Regex

Catches fields outside tables — product names in headers, part numbers in
title blocks, certifications in paragraphs. 28 targeted patterns covering
voltages, currents, dimensions, temperatures, IP ratings, and certification codes.
Only fills fields Layer 1 missed.

### Layer 3 — Groq LLM

Fills whatever remains. Sends only the list of still-missing fields plus
the first 6,000 characters of extracted text to `llama-3.3-70b-versatile`
via Groq's free API. Temperature is set to 0 for deterministic output.
Never overwrites values found by Layers 1 or 2.

---

## Supported Document Types

| Type | How it is handled |
|------|------------------|
| Text-native PDF | pdfplumber + camelot direct extraction |
| Scanned PDF | pdf2image rasterise → pytesseract OCR → regex + LLM |
| Mixed PDF | Text pages via pdfplumber, scanned pages via OCR |
| Password-protected PDF | Flagged with warning, routed to OCR |

---

## Adding New Vendors

Conduit works out of the box on any vendor's spec sheet. If a label from a
new vendor is not being picked up by Layer 1, add it to the vocabulary in
`src/table_extractor.py`:

```python
FIELD_VOCAB: dict[str, str] = {
    ...
    "your new label": "electrical.current_rating",
    ...
}
```

If a field pattern is missing from Layer 2, add it to `src/regex_extractor.py`:

```python
_p("electrical.current_rating",
   r"your pattern here (\d+)\s*A")
```

---

## Tech Stack

| Library | Purpose |
|---------|---------|
| `pdfplumber` | Text and table extraction from text-native PDFs |
| `camelot-py` | Computer vision table detection |
| `pytesseract` | OCR engine for scanned pages |
| `pdf2image` | Rasterises PDF pages for OCR |
| `Pillow` | Image pre-processing before OCR |
| `requests` | Groq API calls |
| `python-dotenv` | Environment variable management |

---

## Requirements

- Python 3.10+
- Tesseract 5.x — verify with `tesseract --version`
- Poppler — verify with `pdftoppm -v`
- Groq API key — free at console.groq.com

---

## Built For

**Atreyus AI** — a construction industry AI startup whose agents reason across
customer data and pricing systems. Conduit solves the data layer problem: before
an agent can answer *"what is the best 200A circuit breaker under $150 that meets
NEC 2023 standards?"*, the product specifications need to exist in structured form.
Conduit creates that structured data automatically.

---

## Roadmap

- [ ] Output validation — check extracted values against expected formats
- [ ] Vendor comparison report — side-by-side JSON diff across manufacturers
- [ ] LayoutLM fine-tuning — use LLM outputs as training labels for a
      document understanding model that runs fully offline
- [ ] REST API endpoint — wrap the pipeline in a FastAPI service
- [ ] Confidence threshold alerts — flag documents below a set completeness score
