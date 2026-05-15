"""
llm_extractor.py  —  Layer 3
------------------------------
Sends only the fields still missing after Layers 1 and 2 to Groq.
The LLM receives:
  - the raw extracted text (or OCR text)
  - the exact list of fields it needs to find
  - strict JSON output instructions

Using llama-3.3-70b-versatile on Groq for free, fast inference.
"""

from __future__ import annotations
import json
import logging
import os
import re
import time
from typing import Optional

import requests

from src.schema import SpecSheet, CORE_FIELDS

log = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_TOKENS   = 1024
TEMPERATURE  = 0.0     # deterministic output for extraction tasks


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a precise data extraction engine for electrical and construction
equipment vendor spec sheets.

Rules:
- Return ONLY a valid JSON object — no markdown fences, no explanation.
- Extract values EXACTLY as written in the document. Do not infer or guess.
- If a field is genuinely not present in the text, set its value to null.
- Include units in every measurement: "480V AC", "100A", "65 kA", "-25°C".
- For temperature ranges in one string (e.g. "-25°C to +70°C"), split them.
"""


def _build_prompt(text: str, missing_fields: list[str]) -> str:
    """
    Build the user prompt.  Only asks for fields still missing.
    Keeps the prompt concise to save tokens.
    """
    field_list = "\n".join(f"  - {f}" for f in missing_fields)

    # Truncate text to avoid hitting context limits (keep first 6000 chars)
    excerpt = text[:6000]
    if len(text) > 6000:
        excerpt += "\n... [truncated]"

    return f"""\
Extract the following fields from the spec sheet text below.
Return a flat JSON object with these exact keys:

{field_list}

Spec sheet text:
---
{excerpt}
---

Return JSON only. Use null for any field not found.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Groq API call with retry
# ─────────────────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, api_key: str, retries: int = 3) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       GROQ_MODEL,
        "temperature": TEMPERATURE,
        "max_tokens":  MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(GROQ_API_URL, headers=headers,
                                 json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.HTTPError as e:
            if resp.status_code == 429:
                wait = 2 ** attempt
                log.warning(f"  Groq rate limit — retrying in {wait}s")
                time.sleep(wait)
            else:
                log.error(f"  Groq HTTP error: {e}")
                break
        except Exception as e:
            log.error(f"  Groq call failed (attempt {attempt}): {e}")
            if attempt < retries:
                time.sleep(2)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Response parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"  JSON parse failed: {e}\n  Raw: {raw[:200]}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_llm(text: str, spec: SpecSheet) -> int:
    """
    Layer 3: use Groq to fill fields still missing after Layers 1 & 2.
    Returns number of new fields written.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        log.warning("GROQ_API_KEY not set — skipping Layer 3")
        spec.metadata.warnings.append("GROQ_API_KEY not set — LLM layer skipped")
        return 0

    missing = spec.missing()
    if not missing:
        log.info("Layer 3: all fields already filled — skipping LLM call")
        return 0

    log.info(f"Layer 3 (Groq LLM): filling {len(missing)} missing fields")

    prompt   = _build_prompt(text, missing)
    raw_resp = _call_groq(prompt, api_key)

    if not raw_resp:
        spec.metadata.warnings.append("Groq API call failed — LLM layer produced no output")
        return 0

    data    = _parse_response(raw_resp)
    written = 0

    for field_key, value in data.items():
        if value is None:
            continue
        value = str(value).strip()
        if not value or value.lower() == "null":
            continue

        # Accept both dotted keys ("electrical.voltage_rating") and
        # flat keys ("voltage_rating") — match against CORE_FIELDS
        matched = None
        if field_key in CORE_FIELDS:
            matched = field_key
        else:
            # Try matching the last segment
            for cf in CORE_FIELDS:
                if cf.split(".")[-1] == field_key:
                    matched = cf
                    break

        if matched and spec.get_field(matched) is None:
            spec.set_field(matched, value, source="llm")
            written += 1
            log.debug(f"  llm → {matched}: {value!r}")

    spec.metadata.fields_from_llm = written
    log.info(f"  Layer 3 complete: {written} new fields written")
    return written
