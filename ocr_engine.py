"""
ocr_engine.py
-------------
Rasterises scanned PDF pages with pdf2image and runs pytesseract.
Only called for pages the inspector flagged as SCANNED.
Returns plain text that feeds into the regex and LLM layers.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import logging

from PIL import Image, ImageFilter, ImageOps, ImageEnhance
from pdf2image import convert_from_path
import pytesseract

log = logging.getLogger(__name__)

DPI            = 300
TESSERACT_CFG  = "--oem 3 --psm 6"


def _preprocess(img: Image.Image) -> Image.Image:
    """Light pre-processing: greyscale → autocontrast → sharpen."""
    img = img.convert("L")
    img = ImageOps.autocontrast(img, cutoff=2)
    img = ImageEnhance.Sharpness(img).enhance(1.5)
    return img


def ocr_pages(
    pdf_path: str | Path,
    page_numbers: Optional[list[int]] = None,   # 1-based; None = all pages
) -> str:
    """
    OCR the requested pages of a PDF and return combined plain text.
    page_numbers — 1-based list; if None every page is OCR'd.
    """
    path = Path(pdf_path).resolve()
    log.info(f"OCR: {path.name}  pages={page_numbers or 'all'}  dpi={DPI}")

    images = convert_from_path(str(path), dpi=DPI)

    if page_numbers:
        # convert to 0-based indices, keep only requested
        images = [img for i, img in enumerate(images, 1) if i in page_numbers]

    parts = []
    for i, img in enumerate(images, 1):
        img = _preprocess(img)
        text = pytesseract.image_to_string(img, lang="eng", config=TESSERACT_CFG)
        if text.strip():
            parts.append(f"--- Page {i} (OCR) ---\n{text.strip()}")
        else:
            log.warning(f"  Page {i}: OCR returned no text")

    combined = "\n\n".join(parts)
    log.info(f"  OCR complete: {len(combined):,} chars across {len(images)} page(s)")
    return combined
