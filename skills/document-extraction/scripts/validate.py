#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4.21"]
# ///
"""Validate an extraction output JSON file against a JSON Schema.

Exit 0 and print "VALID" when the document conforms; otherwise print each
violation with its JSON path and exit 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", type=Path, help="extraction output JSON")
    ap.add_argument("--schema", type=Path, required=True, help="JSON Schema file")
    args = ap.parse_args()

    try:
        instance = json.loads(args.output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"INVALID: output is not valid JSON: {e}")
        return 1
    schema = json.loads(args.schema.read_text(encoding="utf-8"))

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if not errors:
        print("VALID")
        return 0
    for err in errors:
        path = "/" + "/".join(str(p) for p in err.absolute_path)
        print(f"INVALID at {path or '/'}: {err.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
