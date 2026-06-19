"""Build-phase smoke test for the Codex AR agent scaffold."""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_core.evidence.integrator import conservative_integrate
from scripts.validate_json_outputs import validate_file


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def run(case_id: str) -> dict:
    run_dir = ROOT / "runs" / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    agents_dir = run_dir / "agents"
    agent_names = ["case_ingestion", "evidence_integrator", "medical_safety_reviewer", "report_generator"]
    agent_results = []
    for agent_name in agent_names:
        result = {
            "task_id": f"{case_id}_{agent_name}",
            "case_id": case_id,
            "agent_name": agent_name,
            "status": "insufficient_data" if agent_name != "medical_safety_reviewer" else "success",
            "tool_ids": ["deterministic_mock_tools:1.0.0"],
            "skills_used": ["ar-case-orchestration"],
            "input_artifacts": [],
            "output_artifacts": [],
            "measurements": [],
            "evidence": {},
            "confidence": 0.0,
            "quality_flags": ["synthetic_build_phase"],
            "assumptions": [],
            "limitations": ["No patient data supplied."],
            "errors": [],
            "medical_sources": ["ase_2017_native_valvular_regurgitation"],
            "provenance": {"created_at": datetime.now(timezone.utc).isoformat()},
            "review_required": agent_name not in {"medical_safety_reviewer"},
        }
        path = agents_dir / agent_name / "result.json"
        _write_json(path, result)
        validate_file(path, ROOT / "schemas" / "agent_result.schema.json")
        agent_results.append(str(path.relative_to(ROOT)))

    report = deepcopy(json.loads((ROOT / "examples" / "expected_outputs" / "final_report_indeterminate.json").read_text()))
    report["case_id"] = case_id
    report["audit_path"] = f"runs/{case_id}/audit.json"
    report["agent_results"] = agent_results
    report["severity"] = conservative_integrate([], report["missing_information"])
    final_report_path = run_dir / "final_report.json"
    _write_json(final_report_path, report)
    validate_file(final_report_path, ROOT / "schemas" / "final_report.schema.json")

    _write_json(run_dir / "artifact_index.json", {"case_id": case_id, "artifacts": [], "notes": ["No masks generated in mock build-phase smoke test."]})
    _write_json(
        run_dir / "audit.json",
        {
            "case_id": case_id,
            "mode": "build_smoke",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git": {
                "branch": _git_value("branch", "--show-current"),
                "commit": _git_value("rev-parse", "HEAD"),
                "status_short": _git_value("status", "--short"),
            },
            "native_subagents": "not_invoked_by_script",
            "external_services": [],
            "source_approvals": ["2017VavularRegurgitationGuideline.pdf"],
            "handoff_audit_path": "docs/HANDOFF_AUDIT.md",
            "prompts": [
                "prompts/MAIN_AR_ORCHESTRATOR.md",
                "prompts/RUN_AR_CASE.md",
                "prompts/VALIDATE_AR_CASE.md",
                "prompts/TOOL_REPAIR.md",
            ],
            "validation_steps": [
                "agent_result.schema.json validation for mock agent outputs",
                "final_report.schema.json validation for final report",
                "indeterminate output for missing calibration/evidence",
            ],
            "research_use_only": True,
        },
    )
    return {"status": "success", "case_id": case_id, "final_report_path": str(final_report_path.relative_to(ROOT))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default="mock_case_indeterminate")
    args = parser.parse_args()
    print(json.dumps(run(args.case_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
