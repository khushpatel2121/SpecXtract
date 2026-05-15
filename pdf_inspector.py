"""
pdf_inspector.py
----------------
Reads every page of a PDF and decides whether each page can be
extracted with pdfplumber/camelot (text-native) or needs OCR (scanned).

Returns a PDFProfile the pipeline uses to route each page correctly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import logging

import pdfplumber
from pypdf import PdfReader

log = logging.getLogger(__name__)


class Strategy(str, Enum):
    TEXT_NATIVE = "text_native"
    SCANNED     = "scanned"
    MIXED       = "mixed"


@dataclass
class PageInfo:
    number:       int
    strategy:     Strategy
    char_count:   int
    has_images:   bool
    table_count:  int


@dataclass
class PDFProfile:
    path:            Path
    page_count:      int
    file_size_kb:    float
    is_encrypted:    bool
    strategy:        Strategy
    pages:           list[PageInfo]  = field(default_factory=list)
    text_pages:      int             = 0
    scanned_pages:   int             = 0
    # PDF metadata
    title:           Optional[str]   = None
    author:          Optional[str]   = None
    creator:         Optional[str]   = None

    def scanned_page_numbers(self) -> list[int]:
        return [p.number for p in self.pages if p.strategy == Strategy.SCANNED]

    def text_page_numbers(self) -> list[int]:
        return [p.number for p in self.pages if p.strategy == Strategy.TEXT_NATIVE]


MIN_CHARS = 40   # pages with fewer characters are treated as scanned


def inspect(pdf_path: str | Path) -> PDFProfile:
    path = Path(pdf_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    reader    = PdfReader(str(path))
    info      = reader.metadata or {}
    encrypted = reader.is_encrypted

    profile = PDFProfile(
        path         = path,
        page_count   = len(reader.pages),
        file_size_kb = path.stat().st_size / 1024,
        is_encrypted = encrypted,
        strategy     = Strategy.SCANNED,   # updated below
        title        = _clean(info.get("/Title")),
        author       = _clean(info.get("/Author")),
        creator      = _clean(info.get("/Creator")),
        pages        = [],
    )

    if encrypted:
        log.warning(f"{path.name}: encrypted — will require OCR")
        return profile

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            num   = page.page_number          # 1-based
            text  = page.extract_text() or ""
            imgs  = page.images or []
            tbls  = page.find_tables() or []

            strat = Strategy.TEXT_NATIVE if len(text) >= MIN_CHARS else Strategy.SCANNED

            profile.pages.append(PageInfo(
                number      = num,
                strategy    = strat,
                char_count  = len(text),
                has_images  = len(imgs) > 0,
                table_count = len(tbls),
            ))
            if strat == Strategy.TEXT_NATIVE:
                profile.text_pages += 1
            else:
                profile.scanned_pages += 1

    # Roll up overall strategy
    if profile.scanned_pages == 0:
        profile.strategy = Strategy.TEXT_NATIVE
    elif profile.text_pages == 0:
        profile.strategy = Strategy.SCANNED
    else:
        profile.strategy = Strategy.MIXED

    log.info(
        f"{path.name}: {profile.page_count}p  "
        f"strategy={profile.strategy.value}  "
        f"text={profile.text_pages}  scanned={profile.scanned_pages}"
    )
    return profile


def _clean(v) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip()
    return s or None
