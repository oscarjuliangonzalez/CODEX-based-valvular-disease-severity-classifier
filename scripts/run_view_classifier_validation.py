"""Run local echo view-classifier validation for one or more case folders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_core.view_validation import run_validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        default="/Users/general/Library/CloudStorage/Box-Box/Purdue-HackensackUMH/4-Data",
    )
    parser.add_argument("--output-root", default=str(ROOT / "runs" / "view_classifier_validation"))
    parser.add_argument("--cases", nargs="+", default=["A1", "A2", "A3", "A4", "A5"])
    parser.add_argument("--max-video-frames", type=int, default=80)
    args = parser.parse_args()

    summary = run_validation(
        case_ids=args.cases,
        source_root=Path(args.source_root),
        output_root=Path(args.output_root),
        max_video_frames=args.max_video_frames,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
