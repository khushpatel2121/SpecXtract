"""
regex_extractor.py  —  Layer 2
--------------------------------
Scans the full extracted text with targeted regex patterns to catch
fields that live outside tables — product names in headers, part numbers
in title blocks, certifications scattered through paragraphs, etc.

Only writes fields that are still None after Layer 1.
Records source="regex" for every field it fills.
"""

from __future__ import annotations
import re
import logging
from typing import Optional

from src.schema import SpecSheet

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern definitions
# Each entry:  (dotted_field,  compiled_regex,  capture_group_index)
# The regex must have at least one capture group containing the value.
# ─────────────────────────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern, int]] = []


def _p(field: str, pattern: str, group: int = 1, flags=re.IGNORECASE) -> None:
    _PATTERNS.append((field, re.compile(pattern, flags), group))


# ── Part / catalog numbers ────────────────────────────────────────────────────
_p("part_number",
   r"(?:part\s*no\.?|model\s*no\.?|item\s*no\.?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/\.]{3,})")

_p("catalog_number",
   r"(?:cat(?:alog)?\s*(?:no\.?|number|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\/\.]{3,})")

# ── Manufacturer name from header lines ───────────────────────────────────────
_p("manufacturer",
   r"^(Siemens|Schneider\s+Electric|Eaton|ABB|Square\s+D|Hubbell|Leviton|GE|General\s+Electric|Legrand)",
   flags=re.IGNORECASE | re.MULTILINE)

# ── Voltage rating ────────────────────────────────────────────────────────────
_p("electrical.voltage_rating",
   r"(?:rated\s+voltage|voltage\s+rating|operating\s+voltage|ue)\s*[:\-]?\s*"
   r"((?:\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*V(?:\s*AC|\s*DC)?)")

_p("electrical.voltage_rating",
   r"\b(\d{2,4})\s*(?:V\s*AC|VAC|V\s*DC|VDC)\b")

# ── Current rating ────────────────────────────────────────────────────────────
_p("electrical.current_rating",
   r"(?:rated\s+current|current\s+rating|ampere\s+rating|frame\s+size|in|ie)\s*[:\-]?\s*"
   r"(\d+(?:\.\d+)?)\s*A(?:\s|$|,)")

_p("electrical.current_rating",
   r"\b(\d{1,4})\s*(?:amperes?|amps?)\b")

# ── Frequency ─────────────────────────────────────────────────────────────────
_p("electrical.frequency",
   r"(?:rated\s+frequency|frequency)\s*[:\-]?\s*((?:\d+\s*/\s*\d+|\d+)\s*Hz)")

_p("electrical.frequency",
   r"\b((?:50\s*/\s*60|60\s*/\s*50|50|60))\s*Hz\b")

# ── Interrupting / AIC capacity ───────────────────────────────────────────────
_p("electrical.interrupting_capacity",
   r"(?:interrupting\s+capacity|aic|icu|breaking\s+capacity)\s*[:\-]?\s*"
   r"(\d+(?:\.\d+)?)\s*k?A")

# ── Poles ─────────────────────────────────────────────────────────────────────
_p("electrical.pole_configuration",
   r"(?:number\s+of\s+poles?|poles?|pole\s+config)\s*[:\-]?\s*([123](?:-?pole)?)")

_p("electrical.pole_configuration",
   r"\b([123])\s*[-\s]?pole\b")

# ── Trip type ─────────────────────────────────────────────────────────────────
_p("electrical.trip_type",
   r"(?:trip\s+(?:type|unit|class|curve))\s*[:\-]?\s*"
   r"(thermal.{0,5}magnetic|electronic|magnetic\s+only|Class\s+\d+)")

# ── Dimensions ────────────────────────────────────────────────────────────────
_p("physical.width_mm",
   r"(?:width|w)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mm")

_p("physical.height_mm",
   r"(?:height|h)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mm")

_p("physical.depth_mm",
   r"(?:depth|d)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mm")

_p("physical.weight_kg",
   r"(?:weight|net\s+weight)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*kg")

# ── Mounting ──────────────────────────────────────────────────────────────────
_p("physical.mounting_type",
   r"(?:mounting|installation)\s*[:\-]?\s*(DIN\s*rail[^,\n]{0,40}|bolt.{0,10}on[^,\n]{0,20}|panel\s+mount[^,\n]{0,20})",
   flags=re.IGNORECASE)

# ── Enclosure / IP rating ─────────────────────────────────────────────────────
_p("physical.enclosure_rating",
   r"\b(IP\s*\d{2}[A-Z]?)\b")

# ── Wire size ─────────────────────────────────────────────────────────────────
_p("physical.wire_size_max",
   r"(?:wire\s+(?:size|range)|conductor)\s*[:\-]?\s*"
   r"(?:up\s+to\s+)?(\d+(?:/\d+)?\s*(?:AWG|kcmil|mm²))")

_p("physical.wire_size_min",
   r"(?:wire\s+(?:size|range)|conductor)\s*[:\-]?\s*"
   r"(\d+(?:/\d+)?\s*(?:AWG|mm²))\s*(?:to|–|-)")

# ── Operating temperature ─────────────────────────────────────────────────────
_p("environmental.operating_temp_min",
   r"(?:operating|ambient)\s+temp(?:erature)?\s*[:\-]?\s*"
   r"([+-]?\d+(?:\.\d+)?)\s*°?C\s*(?:to|~|–)")

_p("environmental.operating_temp_max",
   r"(?:operating|ambient)\s+temp(?:erature)?\s*[:\-]?\s*"
   r"[+-]?\d+(?:\.\d+)?\s*°?C\s*(?:to|~|–)\s*"
   r"([+-]?\d+(?:\.\d+)?)\s*°?C")

# ── Storage temperature ───────────────────────────────────────────────────────
_p("environmental.storage_temp_max",
   r"storage\s+temp(?:erature)?\s*[:\-]?\s*"
   r"[+-]?\d+(?:\.\d+)?\s*°?C\s*(?:to|~|–)\s*"
   r"([+-]?\d+(?:\.\d+)?)\s*°?C")

# ── Humidity ──────────────────────────────────────────────────────────────────
_p("environmental.humidity_max",
   r"(?:relative\s+)?humidity\s*[:\-]?\s*"
   r"(?:up\s+to\s+|≤\s*|max\.?\s*)?(\d+\s*%[^,\n]{0,30})")

# ── Altitude ──────────────────────────────────────────────────────────────────
_p("environmental.altitude_max",
   r"(?:max(?:imum)?\s+)?altitude\s*[:\-]?\s*(\d[\d,]*\s*m(?:\s*\(\d[\d,]*\s*ft\))?)")

# ── Pollution degree ──────────────────────────────────────────────────────────
_p("environmental.pollution_degree",
   r"(pollution\s+degree\s+\d)",
   flags=re.IGNORECASE)

# ── Overvoltage category ──────────────────────────────────────────────────────
_p("environmental.overvoltage_cat",
   r"(?:overvoltage|installation)\s+category\s*[:\-]?\s*((?:CAT\.?\s*)?[IV]{1,4})")


# ─────────────────────────────────────────────────────────────────────────────
# Certification patterns (collected into a list, not a single field)
# ─────────────────────────────────────────────────────────────────────────────

_CERT_PATTERNS = [
    re.compile(r"\bUL\s*\d{2,4}\b",           re.IGNORECASE),
    re.compile(r"\bCSA\s*C[\d\.]+(?:[^,\s]*)?",re.IGNORECASE),
    re.compile(r"\bIEC\s*(?:EN\s*)?\d{4,6}(?:[:\-]\d+)?",re.IGNORECASE),
    re.compile(r"\bEN\s*\d{4,6}(?:[:\-]\d+)?",re.IGNORECASE),
    re.compile(r"\bNEMA\s*[A-Z]{1,3}\d*",      re.IGNORECASE),
    re.compile(r"\bCE\b"),
    re.compile(r"\bRoHS\b",                    re.IGNORECASE),
    re.compile(r"\bATEX\b",                    re.IGNORECASE),
]

_STANDARD_PATTERNS = [
    re.compile(r"\bNEC\s*20\d{2}(?:\s+Article\s+\d+)?", re.IGNORECASE),
    re.compile(r"\bNEMA\s*AB\d\b",             re.IGNORECASE),
    re.compile(r"\bANSI[/ ][A-Z\d\.]+",        re.IGNORECASE),
    re.compile(r"\bIEEE\s*\d{2,4}\b",          re.IGNORECASE),
]


def _extract_certs(text: str) -> tuple[list[str], list[str]]:
    certs, standards = set(), set()
    for pat in _CERT_PATTERNS:
        for m in pat.finditer(text):
            certs.add(m.group(0).strip())
    for pat in _STANDARD_PATTERNS:
        for m in pat.finditer(text):
            standards.add(m.group(0).strip())
    return sorted(certs), sorted(standards)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_regex(text: str, spec: SpecSheet) -> int:
    """
    Layer 2: scan extracted text with regex patterns.
    Only fills fields still None after Layer 1.
    Returns number of new fields written.
    """
    log.info("Layer 2 (regex extraction)")
    written = 0

    for field, pattern, group in _PATTERNS:
        if spec.get_field(field) is not None:
            continue                    # already filled by table extractor
        m = pattern.search(text)
        if m:
            try:
                value = m.group(group).strip()
                if value:
                    spec.set_field(field, value, source="regex")
                    written += 1
                    log.debug(f"  regex → {field}: {value!r}")
            except IndexError:
                pass

    # Certifications
    certs, standards = _extract_certs(text)
    new_certs = [c for c in certs if c not in spec.certifications]
    new_stds  = [s for s in standards if s not in spec.compliance_standards]
    spec.certifications.extend(new_certs)
    spec.compliance_standards.extend(new_stds)
    if new_certs or new_stds:
        log.debug(f"  regex → {len(new_certs)} certs, {len(new_stds)} standards")

    spec.metadata.fields_from_regex = written
    log.info(f"  Layer 2 complete: {written} new fields written")
    return written
