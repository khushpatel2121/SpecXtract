"""
main.py — CLI for the spec sheet extraction pipeline

Usage:
    python main.py run   data/raw_pdfs/siemens_3VA1.pdf
    python main.py batch data/raw_pdfs/
"""

from __future__ import annotations
import json
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline.log", mode="a"),
    ],
)

from src.pipeline import run, run_batch


def _print_result(spec) -> None:
    from dataclasses import asdict
    d = asdict(spec)
    meta = d.pop("metadata")

    print("\n" + "─" * 60)
    print(f"  File        : {meta['source_file']}")
    print(f"  Strategy    : {meta['strategy']}")
    print(f"  Completeness: {meta['confidence']*100:.0f}%")
    print(f"  Fields      : table={meta['fields_from_table']}  "
          f"regex={meta['fields_from_regex']}  llm={meta['fields_from_llm']}")

    print("\n  Extracted fields:")
    for k, v in d.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                if sv:
                    print(f"    {k}.{sk}: {sv}")
        elif isinstance(v, list) and v:
            print(f"    {k}: {', '.join(v)}")
        elif v and not isinstance(v, (dict, list)):
            print(f"    {k}: {v}")

    if meta["missing_fields"]:
        print(f"\n  Missing: {', '.join(meta['missing_fields'])}")
    if meta["warnings"]:
        print(f"\n  Warnings:")
        for w in meta["warnings"]:
            print(f"    ! {w}")
    print("─" * 60)


USAGE = """
Spec Sheet Extraction Pipeline

Commands:
  run   <pdf_path>     Process a single PDF
  batch <directory>    Process all PDFs in a folder

Options:
  --no-save    Do not write JSON output

Examples:
  python main.py run   data/raw_pdfs/siemens_3VA1.pdf
  python main.py batch data/raw_pdfs/
"""


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(USAGE)
        sys.exit(0)

    cmd  = sys.argv[1].lower()
    path = sys.argv[2]
    save = "--no-save" not in sys.argv

    if cmd == "run":
        spec = run(path, save=save)
        _print_result(spec)

    elif cmd == "batch":
        results = run_batch(path, save=save)
        print(f"\n{'─'*60}")
        print(f"  Batch complete: {len(results)} PDFs processed")
        print(f"{'─'*60}")
        for name, spec in results:
            pct = spec.metadata.confidence * 100
            src = (f"t={spec.metadata.fields_from_table} "
                   f"r={spec.metadata.fields_from_regex} "
                   f"l={spec.metadata.fields_from_llm}")
            print(f"  {'✓' if pct > 50 else '⚠'} {name:<45} {pct:5.0f}%  [{src}]")

    else:
        print(f"Unknown command: {cmd}")
        print(USAGE)
        sys.exit(1)
