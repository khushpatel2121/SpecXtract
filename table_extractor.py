"""
table_extractor.py  —  Layer 1
-------------------------------
Extracts tables from text-native PDF pages using:
  1. camelot lattice  (ruled tables — most spec sheets)
  2. camelot stream   (whitespace-separated tables — fallback)
  3. pdfplumber       (final fallback)

Each table is a list of rows; each row is [label, value].
Labels are normalised through FIELD_VOCAB to map every vendor's
wording ("Ie", "rated current", "ampere rating") to the same
SpecSheet field name ("electrical.current_rating").

Writes directly into a SpecSheet instance and records source="table".
"""

from __future__ import annotations
import re
import logging
from pathlib import Path

import camelot
import pdfplumber

from src.schema import SpecSheet

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary — maps every known vendor label → SpecSheet dotted field
# ─────────────────────────────────────────────────────────────────────────────
FIELD_VOCAB: dict[str, str] = {
    # product identity
    "catalog number":              "catalog_number",
    "catalog no":                  "catalog_number",
    "cat no":                      "catalog_number",
    "cat. no":                     "catalog_number",
    "catalog no.":                 "catalog_number",
    "part number":                 "part_number",
    "part no":                     "part_number",
    "part no.":                    "part_number",
    "model":                       "part_number",
    "model number":                "part_number",
    "item number":                 "part_number",
    "product":                     "product_name",
    "product name":                "product_name",
    "name":                        "product_name",
    "description":                 "description",
    "product description":         "description",
    "product line":                "product_line",
    "series":                      "product_line",
    "family":                      "product_line",
    "manufacturer":                "manufacturer",
    "brand":                       "manufacturer",
    "made by":                     "manufacturer",
    "product type":                "product_type",
    "type":                        "product_type",

    # electrical
    "rated current":                    "electrical.current_rating",
    "rated operational current":        "electrical.current_rating",
    "rated operational current ie":     "electrical.current_rating",
    "ampere rating":                    "electrical.current_rating",
    "frame amperes":                    "electrical.current_rating",
    "continuous current":               "electrical.current_rating",
    "in":                               "electrical.current_rating",
    "ie":                               "electrical.current_rating",
    "ith":                              "electrical.current_rating",
    "current rating":                   "electrical.current_rating",
    "current":                          "electrical.current_rating",

    "rated voltage":                    "electrical.voltage_rating",
    "rated operational voltage":        "electrical.voltage_rating",
    "rated operational voltage ue":     "electrical.voltage_rating",
    "voltage rating":                   "electrical.voltage_rating",
    "operating voltage":                "electrical.voltage_rating",
    "voltage":                          "electrical.voltage_rating",
    "ue":                               "electrical.voltage_rating",
    "maximum voltage":                  "electrical.voltage_rating",
    "system voltage":                   "electrical.voltage_rating",

    "rated frequency":                  "electrical.frequency",
    "frequency":                        "electrical.frequency",

    "interrupting capacity":            "electrical.interrupting_capacity",
    "rated ultimate breaking capacity": "electrical.interrupting_capacity",
    "icu":                              "electrical.interrupting_capacity",
    "aic":                              "electrical.interrupting_capacity",
    "aic rating":                       "electrical.interrupting_capacity",
    "ampere interrupting capacity":     "electrical.interrupting_capacity",

    "short circuit rating":             "electrical.short_circuit_rating",
    "short-circuit rating":             "electrical.short_circuit_rating",
    "sccr":                             "electrical.short_circuit_rating",
    "withstand rating":                 "electrical.short_circuit_rating",

    "poles":                            "electrical.pole_configuration",
    "pole":                             "electrical.pole_configuration",
    "number of poles":                  "electrical.pole_configuration",
    "pole configuration":               "electrical.pole_configuration",
    "no. of poles":                     "electrical.pole_configuration",

    "trip type":                        "electrical.trip_type",
    "trip unit":                        "electrical.trip_type",
    "trip curve":                       "electrical.trip_type",
    "trip class":                       "electrical.trip_type",
    "tripping characteristic":          "electrical.trip_type",
    "overcurrent trip":                 "electrical.trip_type",

    "rated insulation voltage":         "electrical.insulation_voltage",
    "insulation voltage":               "electrical.insulation_voltage",
    "ui":                               "electrical.insulation_voltage",

    "rated impulse withstand voltage":  "electrical.impulse_voltage",
    "impulse withstand voltage":        "electrical.impulse_voltage",
    "uimp":                             "electrical.impulse_voltage",

    # physical
    "width":                    "physical.width_mm",
    "overall width":            "physical.width_mm",
    "height":                   "physical.height_mm",
    "overall height":           "physical.height_mm",
    "depth":                    "physical.depth_mm",
    "overall depth":            "physical.depth_mm",
    "weight":                   "physical.weight_kg",
    "net weight":               "physical.weight_kg",
    "shipping weight":          "physical.weight_kg",
    "mounting":                 "physical.mounting_type",
    "mounting type":            "physical.mounting_type",
    "installation":             "physical.mounting_type",
    "enclosure":                "physical.enclosure_rating",
    "enclosure rating":         "physical.enclosure_rating",
    "degree of protection":     "physical.enclosure_rating",
    "ip rating":                "physical.enclosure_rating",
    "wire size":                "physical.wire_size_max",
    "wire range":               "physical.wire_size_max",
    "conductor size":           "physical.wire_size_max",
    "wire size min":            "physical.wire_size_min",
    "wire size max":            "physical.wire_size_max",
    "terminal":                 "physical.terminal_type",
    "terminal type":            "physical.terminal_type",
    "connection type":          "physical.terminal_type",
    "lug type":                 "physical.terminal_type",

    # environmental
    "operating temperature":        "environmental.operating_temp_max",
    "ambient temperature":          "environmental.operating_temp_max",
    "temperature range":            "environmental.operating_temp_max",
    "operating temp":               "environmental.operating_temp_max",
    "storage temperature":          "environmental.storage_temp_max",
    "humidity":                     "environmental.humidity_max",
    "relative humidity":            "environmental.humidity_max",
    "max humidity":                 "environmental.humidity_max",
    "altitude":                     "environmental.altitude_max",
    "maximum altitude":             "environmental.altitude_max",
    "max altitude":                 "environmental.altitude_max",
    "pollution degree":             "environmental.pollution_degree",
    "degree of pollution":          "environmental.pollution_degree",
    "overvoltage category":         "environmental.overvoltage_cat",
    "installation category":        "environmental.overvoltage_cat",
}


def _norm_key(raw: str) -> str:
    """Lowercase, strip punctuation/whitespace for vocab lookup."""
    s = raw.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)   # remove punctuation
    s = re.sub(r"\s+", " ", s)      # collapse spaces
    return s.strip()


def _norm_val(raw: str) -> str:
    """Clean up a raw cell value."""
    if raw is None:
        return ""
    s = str(raw).strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[¹²³⁴†‡§]+$", "", s).strip()
    return s


def _lookup(raw_key: str) -> str | None:
    """Return the SpecSheet field name for a raw label, or None."""
    return FIELD_VOCAB.get(_norm_key(raw_key))


# ─────────────────────────────────────────────────────────────────────────────
# camelot helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_camelot(pdf_path: str, flavor: str) -> list[list[list[str]]]:
    """
    Run camelot on all pages.  Returns a list of tables, each table
    being a list of rows, each row a list of cell strings.
    flavor: "lattice" or "stream"
    """
    try:
        tables = camelot.read_pdf(pdf_path, pages="all", flavor=flavor)
        result = []
        for t in tables:
            if t.accuracy < 60:       # skip very low-confidence tables
                log.debug(f"  camelot {flavor}: skipping table (accuracy={t.accuracy:.0f})")
                continue
            rows = t.df.values.tolist()
            rows = [[str(c) for c in row] for row in rows]
            result.append(rows)
        log.info(f"  camelot {flavor}: {len(result)} usable tables")
        return result
    except Exception as e:
        log.debug(f"  camelot {flavor} failed: {e}")
        return []


def _extract_pdfplumber(pdf_path: str) -> list[list[list[str]]]:
    """Run pdfplumber table extraction on all pages."""
    result = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for tbl in (page.extract_tables() or []):
                    rows = [[str(c or "") for c in row] for row in tbl]
                    result.append(rows)
        log.info(f"  pdfplumber: {len(result)} tables")
    except Exception as e:
        log.debug(f"  pdfplumber failed: {e}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Map tables → SpecSheet fields
# ─────────────────────────────────────────────────────────────────────────────

def _apply_tables(tables: list[list[list[str]]], spec: SpecSheet) -> int:
    """
    Walk every row of every table.
    If a row looks like [label, value], look the label up in FIELD_VOCAB
    and write the value into the SpecSheet.
    Returns the number of fields written.
    """
    written = 0
    for table in tables:
        for row in table:
            # We only care about 2-column rows (label | value)
            # For wider tables, treat col0 as label, col1 as value
            if len(row) < 2:
                continue

            label = _norm_val(row[0])
            value = _norm_val(row[1])

            if not label or not value:
                continue
            # Skip rows that are clearly headers (both cells look like labels)
            if value.lower() in ("value", "specification", "unit", "parameter"):
                continue

            field = _lookup(label)
            if field:
                spec.set_field(field, value, source="table")
                written += 1
                log.debug(f"  table → {field}: {value!r}")

            # Handle temperature range in one cell: "-25°C to +70°C"
            if field and "temp" in field:
                _split_temp_range(value, spec)

    return written


def _split_temp_range(value: str, spec: SpecSheet) -> None:
    """
    If a temperature value contains a range like '-25°C to +70°C',
    split it into min and max fields.
    """
    m = re.search(
        r"([+-]?\d+(?:\.\d+)?)\s*°?[CF]?\s*(?:to|~|–|-)\s*([+-]?\d+(?:\.\d+)?)\s*°?[CF]?",
        value, re.IGNORECASE
    )
    if m:
        spec.set_field("environmental.operating_temp_min", m.group(1) + "°C", "table")
        spec.set_field("environmental.operating_temp_max", m.group(2) + "°C", "table")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_tables(pdf_path: str | Path, spec: SpecSheet) -> int:
    """
    Layer 1: extract all tables from a text-native PDF and populate spec.

    Strategy:
      1. camelot lattice  — best for bordered tables
      2. camelot stream   — fallback for whitespace tables
      3. pdfplumber       — last resort

    Returns total number of fields written into spec.
    """
    path = str(Path(pdf_path).resolve())
    log.info(f"Layer 1 (table extraction): {Path(path).name}")

    # 1 — camelot lattice
    tables = _extract_camelot(path, "lattice")

    # 2 — camelot stream (if lattice got nothing)
    if not tables:
        tables = _extract_camelot(path, "stream")

    # 3 — pdfplumber fallback
    if not tables:
        tables = _extract_pdfplumber(path)

    if not tables:
        log.warning("  No tables found by any extractor")
        return 0

    written = _apply_tables(tables, spec)
    spec.metadata.fields_from_table = written
    log.info(f"  Layer 1 complete: {written} fields written from {len(tables)} tables")
    return written
