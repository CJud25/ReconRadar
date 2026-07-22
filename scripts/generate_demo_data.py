from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tens_hq.synthetic import export_demo_data, generate_demo_data


if __name__ == "__main__":
    dataset = generate_demo_data()
    manifest = export_demo_data(dataset, ROOT / "data" / "generated")
    print(f"Generated {len(manifest['datasets'])} synthetic datasets in {ROOT / 'data' / 'generated'}")
