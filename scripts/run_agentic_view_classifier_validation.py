"""Run local agentic echo view-classifier validation for case folders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_core.agentic_view_classifier import dry_run_plan, run_validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run agentic view-classifier validation.")
    parser.add_argument(
        "--source-root",
        default="/Users/general/Library/CloudStorage/Box-Box/Purdue-HackensackUMH/4-Data",
    )
    parser.add_argument("--output-root", default=str(ROOT / "runs" / "agentic_view_classifier_validation"))
    parser.add_argument("--cases", nargs="+", default=["A1", "A2", "A3", "A4", "A5"])
    parser.add_argument("--max-video-frames", type=int, default=80)
    parser.add_argument("--max-representative-frames", type=int, default=3)
    parser.add_argument("--reuse-existing-media", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--guidelines-dir", default=str(ROOT / "guidelines"))
    parser.add_argument("--guideline-output-dir", default=str(ROOT / "docs" / "guideline_summaries"))
    parser.add_argument("--agent-decisions-root", default=None)
    args = parser.parse_args()

    if args.dry_run:
        print(
            json.dumps(
                dry_run_plan(args.cases, Path(args.source_root), Path(args.output_root)),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    summary = run_validation(
        case_ids=args.cases,
        source_root=Path(args.source_root),
        output_root=Path(args.output_root),
        max_video_frames=args.max_video_frames,
        max_representative_frames=args.max_representative_frames,
        reuse_existing_media=args.reuse_existing_media,
        rerun=args.rerun,
        guidelines_dir=Path(args.guidelines_dir),
        guideline_output_dir=Path(args.guideline_output_dir),
        agent_decisions_root=Path(args.agent_decisions_root) if args.agent_decisions_root else None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
