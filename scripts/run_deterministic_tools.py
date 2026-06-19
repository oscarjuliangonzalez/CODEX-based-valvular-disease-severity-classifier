"""Run stable deterministic AR calculations on synthetic values."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_core.measurements.physics import classic_pisa_surface_area_cm2, eroa_peak_cm2, stroke_volume_ml


def main() -> int:
    surface = classic_pisa_surface_area_cm2(1.0)
    payload = {
        "pisa_surface_area_cm2": surface,
        "eroa_peak_cm2": eroa_peak_cm2(40.0, surface, 400.0),
        "stroke_volume_ml": stroke_volume_ml(2.0, 20.0),
        "clinical_validation": False,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
