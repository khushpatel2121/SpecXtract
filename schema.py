"""
schema.py
---------
Single data model for a vendor spec sheet record.
Every extraction layer (table, regex, LLM) writes into the same
SpecSheet object.  The metadata block tracks which layer found
each field so you can audit the pipeline later.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class ElectricalSpecs:
    voltage_rating:         Optional[str] = None   # "480V AC"
    current_rating:         Optional[str] = None   # "100A"
    frequency:              Optional[str] = None   # "50/60 Hz"
    interrupting_capacity:  Optional[str] = None   # "65 kA"
    short_circuit_rating:   Optional[str] = None   # "65 kA @ 480V"
    pole_configuration:     Optional[str] = None   # "3-pole"
    trip_type:              Optional[str] = None   # "Thermal-magnetic"
    insulation_voltage:     Optional[str] = None   # "690V"
    impulse_voltage:        Optional[str] = None   # "8 kV"


@dataclass
class PhysicalSpecs:
    width_mm:         Optional[str] = None
    height_mm:        Optional[str] = None
    depth_mm:         Optional[str] = None
    weight_kg:        Optional[str] = None
    mounting_type:    Optional[str] = None   # "DIN rail / bolt-on"
    enclosure_rating: Optional[str] = None   # "IP20"
    wire_size_min:    Optional[str] = None   # "14 AWG"
    wire_size_max:    Optional[str] = None   # "1/0 AWG"
    terminal_type:    Optional[str] = None   # "Box lug"


@dataclass
class EnvironmentalSpecs:
    operating_temp_min: Optional[str] = None   # "-25°C"
    operating_temp_max: Optional[str] = None   # "+70°C"
    storage_temp_min:   Optional[str] = None
    storage_temp_max:   Optional[str] = None
    humidity_max:       Optional[str] = None   # "95% non-condensing"
    altitude_max:       Optional[str] = None   # "2000 m"
    pollution_degree:   Optional[str] = None   # "Pollution Degree 3"
    overvoltage_cat:    Optional[str] = None   # "Category III"


@dataclass
class ExtractionMetadata:
    source_file:        str   = ""
    strategy:           str   = ""    # "text_native" | "scanned" | "mixed"
    fields_from_table:  int   = 0
    fields_from_regex:  int   = 0
    fields_from_llm:    int   = 0
    confidence:         float = 0.0   # 0.0 – 1.0
    missing_fields:     list  = field(default_factory=list)
    warnings:           list  = field(default_factory=list)
    # field_name → "table" | "regex" | "llm"
    field_sources:      dict  = field(default_factory=dict)


@dataclass
class SpecSheet:
    # ── Product identity ──────────────────────────────────────────────────
    manufacturer:   Optional[str] = None
    product_name:   Optional[str] = None
    part_number:    Optional[str] = None
    catalog_number: Optional[str] = None
    product_line:   Optional[str] = None
    product_type:   Optional[str] = None
    description:    Optional[str] = None

    # ── Nested specs ──────────────────────────────────────────────────────
    electrical:    ElectricalSpecs    = field(default_factory=ElectricalSpecs)
    physical:      PhysicalSpecs      = field(default_factory=PhysicalSpecs)
    environmental: EnvironmentalSpecs = field(default_factory=EnvironmentalSpecs)

    # ── Lists ─────────────────────────────────────────────────────────────
    certifications:       list[str] = field(default_factory=list)
    compliance_standards: list[str] = field(default_factory=list)

    # ── Pricing ───────────────────────────────────────────────────────────
    list_price: Optional[str] = None
    currency:   str = "USD"

    # ── How it was built ──────────────────────────────────────────────────
    metadata: ExtractionMetadata = field(default_factory=ExtractionMetadata)

    # ─────────────────────────────────────────────────────────────────────

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, ensure_ascii=False)

    def get_field(self, dotted: str) -> Optional[str]:
        """Read a nested field:  'electrical.voltage_rating'"""
        parts = dotted.split(".")
        obj = self
        for p in parts:
            obj = getattr(obj, p, None)
            if obj is None:
                return None
        return obj

    def set_field(self, dotted: str, value: str, source: str) -> None:
        """
        Write a value into a nested field and record which layer set it.
        dotted  — 'electrical.voltage_rating'
        source  — 'table' | 'regex' | 'llm'
        """
        parts = dotted.split(".")
        obj = self
        for p in parts[:-1]:
            obj = getattr(obj, p)
        # Only write if field is currently empty
        if getattr(obj, parts[-1]) is None:
            setattr(obj, parts[-1], value)
            self.metadata.field_sources[dotted] = source

    def missing(self) -> list[str]:
        """Return dotted names of all core fields that are still None."""
        empty = []
        for dotted in CORE_FIELDS:
            if self.get_field(dotted) is None:
                empty.append(dotted)
        return empty

    def completeness(self) -> float:
        """Fraction of core fields that are filled (0.0 – 1.0)."""
        filled = sum(1 for d in CORE_FIELDS if self.get_field(d) is not None)
        return round(filled / len(CORE_FIELDS), 3)


# ── Ordered list of fields the pipeline tries to fill ────────────────────────
CORE_FIELDS = [
    "manufacturer",
    "product_name",
    "part_number",
    "catalog_number",
    "product_line",
    "product_type",
    "electrical.voltage_rating",
    "electrical.current_rating",
    "electrical.frequency",
    "electrical.interrupting_capacity",
    "electrical.short_circuit_rating",
    "electrical.pole_configuration",
    "electrical.trip_type",
    "electrical.insulation_voltage",
    "physical.width_mm",
    "physical.height_mm",
    "physical.depth_mm",
    "physical.weight_kg",
    "physical.mounting_type",
    "physical.enclosure_rating",
    "physical.wire_size_min",
    "physical.wire_size_max",
    "physical.terminal_type",
    "environmental.operating_temp_min",
    "environmental.operating_temp_max",
    "environmental.humidity_max",
    "environmental.altitude_max",
    "environmental.pollution_degree",
    "environmental.overvoltage_cat",
]
