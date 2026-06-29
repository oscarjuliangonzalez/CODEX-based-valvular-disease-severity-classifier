"""Run local cardiac timing validation for view-classified echo cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_core.timing_validation import run_validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        default="/Users/general/Library/CloudStorage/Box-Box/Purdue-HackensackUMH/4-Data",
    )
    parser.add_argument("--output-root", default=str(ROOT / "runs" / "timing_classifier_validation"))
    parser.add_argument("--view-output-root", default=str(ROOT / "runs" / "agentic_view_classifier_validation"))
    parser.add_argument("--cases", nargs="+", default=["A1", "A2", "A3", "A4", "A5"])
    parser.add_argument("--max-video-frames", type=int, default=80)
    parser.add_argument("--force-view-refresh", action="store_true")
    args = parser.parse_args()

    summary = run_validation(
        case_ids=args.cases,
        source_root=Path(args.source_root),
        output_root=Path(args.output_root),
        view_output_root=Path(args.view_output_root),
        max_video_frames=args.max_video_frames,
        force_view_refresh=args.force_view_refresh,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
