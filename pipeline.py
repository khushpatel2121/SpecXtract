"""
pipeline.py
-----------
Orchestrates the full extraction flow for one PDF:

  inspect → (OCR if scanned) → Layer 1 tables → Layer 2 regex → Layer 3 LLM
           → compute metadata → save JSON

Call run(pdf_path) to process a single file.
Call run_batch(directory) to process a folder.
"""

from __future__ import annotations
import json
import logging
import time
from pathlib import Path

import pdfplumber

from src.schema       import SpecSheet, ExtractionMetadata, CORE_FIELDS
from src.pdf_inspector  import inspect as inspect_pdf, Strategy
from src.ocr_engine     import ocr_pages
from src.table_extractor import extract_tables
from src.regex_extractor import extract_regex
from src.llm_extractor   import extract_llm

log = logging.getLogger(__name__)

JSON_OUT = Path("data/structured_json")


# ─────────────────────────────────────────────────────────────────────────────
# Full text extraction (text-native pages)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_text(pdf_path: str) -> str:
    """Pull plain text from all pages using pdfplumber."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text(layout=True) or ""
            if t.strip():
                parts.append(t.strip())
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Single PDF
# ─────────────────────────────────────────────────────────────────────────────

def run(pdf_path: str | Path, save: bool = True) -> SpecSheet:
    """
    Full pipeline for one PDF.

    1. Inspect — decide strategy
    2. Extract text (pdfplumber) or OCR (pytesseract)
    3. Layer 1 — camelot + pdfplumber tables
    4. Layer 2 — regex patterns
    5. Layer 3 — Groq LLM for remaining gaps
    6. Finalise metadata and optionally save JSON
    """
    path  = Path(pdf_path).resolve()
    start = time.time()

    log.info(f"\n{'='*60}")
    log.info(f"Processing: {path.name}")
    log.info(f"{'='*60}")

    spec = SpecSheet(
        metadata=ExtractionMetadata(source_file=path.name)
    )

    # ── Step 1: inspect ────────────────────────────────────────────────────
    profile = inspect_pdf(path)
    spec.metadata.strategy = profile.strategy.value

    # Populate manufacturer from PDF metadata if available
    if profile.creator and not spec.manufacturer:
        for brand in ["Siemens","Schneider","Eaton","ABB","Square D","Hubbell"]:
            if brand.lower() in (profile.creator or "").lower():
                spec.set_field("manufacturer", brand, "table")
                break

    # ── Step 2: get raw text ───────────────────────────────────────────────
    raw_text = ""

    if profile.strategy == Strategy.SCANNED:
        log.info("Strategy: SCANNED — running OCR on all pages")
        raw_text = ocr_pages(path)

    elif profile.strategy == Strategy.TEXT_NATIVE:
        log.info("Strategy: TEXT_NATIVE — using pdfplumber")
        raw_text = _extract_text(str(path))

    elif profile.strategy == Strategy.MIXED:
        log.info("Strategy: MIXED — pdfplumber for text pages, OCR for scanned pages")
        text_part = _extract_text(str(path))
        ocr_part  = ocr_pages(path, page_numbers=profile.scanned_page_numbers())
        raw_text  = "\n\n".join(filter(None, [text_part, ocr_part]))

    if not raw_text.strip():
        msg = "No text could be extracted from this PDF"
        log.warning(msg)
        spec.metadata.warnings.append(msg)
        return spec

    log.info(f"Raw text: {len(raw_text):,} characters")

    # ── Step 3: Layer 1 — tables ───────────────────────────────────────────
    if profile.strategy != Strategy.SCANNED:
        # Table extraction only works on text-native pages
        extract_tables(path, spec)

    # ── Step 4: Layer 2 — regex ────────────────────────────────────────────
    extract_regex(raw_text, spec)

    # ── Step 5: Layer 3 — LLM ─────────────────────────────────────────────
    extract_llm(raw_text, spec)

    # ── Step 6: finalise metadata ──────────────────────────────────────────
    missing = spec.missing()
    spec.metadata.missing_fields = missing
    spec.metadata.confidence     = spec.completeness()

    elapsed = round(time.time() - start, 2)
    log.info(
        f"\nDone in {elapsed}s — "
        f"completeness={spec.metadata.confidence*100:.0f}%  "
        f"table={spec.metadata.fields_from_table}  "
        f"regex={spec.metadata.fields_from_regex}  "
        f"llm={spec.metadata.fields_from_llm}  "
        f"missing={len(missing)}"
    )

    if missing:
        log.info(f"Still missing: {', '.join(missing)}")

    # ── Step 7: save JSON ──────────────────────────────────────────────────
    if save:
        JSON_OUT.mkdir(parents=True, exist_ok=True)
        out_path = JSON_OUT / (path.stem + ".json")
        out_path.write_text(spec.to_json(), encoding="utf-8")
        log.info(f"Saved: {out_path}")

    return spec


# ─────────────────────────────────────────────────────────────────────────────
# Batch
# ─────────────────────────────────────────────────────────────────────────────

def run_batch(
    directory: str | Path,
    save: bool = True,
) -> list[tuple[str, SpecSheet]]:
    """
    Process all PDFs in a directory.
    Returns list of (filename, SpecSheet) tuples.
    """
    directory = Path(directory)
    pdfs      = sorted(directory.glob("*.pdf"))

    if not pdfs:
        log.warning(f"No PDFs found in {directory}")
        return []

    log.info(f"Batch: {len(pdfs)} PDFs in {directory}")
    results = []

    for pdf in pdfs:
        try:
            spec = run(pdf, save=save)
            results.append((pdf.name, spec))
        except Exception as e:
            log.error(f"Failed: {pdf.name} — {e}")
            results.append((pdf.name, SpecSheet(
                metadata=ExtractionMetadata(
                    source_file=pdf.name,
                    warnings=[f"Pipeline error: {e}"]
                )
            )))

    return results
