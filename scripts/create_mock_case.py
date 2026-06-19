"""Create a de-identified synthetic manifest for build-phase tests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    output = ROOT / "examples" / "mock_case" / "case_manifest.json"
    payload = json.loads(output.read_text()) if output.exists() else {}
    payload.setdefault("case_id", "mock_case_indeterminate")
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"status": "created", "path": str(output.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
