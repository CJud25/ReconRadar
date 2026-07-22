from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tens_hq.synthetic import generate_demo_data
from tens_hq.validation import validate_demo_data


if __name__ == "__main__":
    result = validate_demo_data(generate_demo_data())
    if result.errors:
        for error in result.errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    print("Synthetic demo validation passed.")
