"""Generate the SYNTHETIC sample Radar-handoff JSON for the demo (A2).

Writes ``data/samples/sample_radar_handoff.json`` -- a small, clearly-labeled
EXAMPLE ``radar-handoff/v1`` snapshot the Opportunity Packet's Origin intake
can load so the caveat-first Origin section renders out of the box. It is
NOT real GovConRadar output; every value is invented, ``synthetic_sample`` is
``true``, and the PIID is an obviously-fake ``SYNTH-A2-0001``. Denver, CO
matches the demo narrative (R2b's bundled sample worksite is also Denver).

``type_of_set_aside_code`` is deliberately ``null`` here (not simply absent)
so the bundled example exercises the honesty-critical "not reported in
snapshot (null)" render path -- distinct from a claimed unrestricted set-aside
-- out of the box.

Run once and commit the artifact:

    py scripts/make_sample_radar_handoff.py
"""

from __future__ import annotations

import json
from pathlib import Path

HANDOFF: dict = {
    "schema_version": "radar-handoff/v1",
    "snapshot_date": "2026-07-15",
    "piid": "SYNTH-A2-0001",
    "radar_source_label": "GovConRadar 2.8.0 (SYNTHETIC sample)",
    "synthetic_sample": True,
    "claims": {
        "referenced_idv_piid": None,
        "recipient_name": "SYNTHETIC EXAMPLE SERVICES LLC",
        "recipient_uei": "SYNTHUEI0001A",
        "awarding_subagency": "SYNTHETIC Public Buildings Service",
        "naics_code": "561720",
        "psc_code": "S201",
        "type_of_set_aside_code": None,
        "extent_competed_code": "D",
        "number_of_offers_received": 4,
        "total_obligation": 180000.0,
        "base_and_all_options": 420000.0,
        "pop_start_date": "2024-06-01",
        "pop_current_end_date": "2025-05-31",
        "pop_potential_end_date": "2028-05-31",
        "place_of_performance": {
            "city": "Denver",
            "county": "Denver",
            "state": "co",
        },
    },
}


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_radar_handoff.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(HANDOFF, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target} ({target.stat().st_size} bytes).")


if __name__ == "__main__":
    main()
