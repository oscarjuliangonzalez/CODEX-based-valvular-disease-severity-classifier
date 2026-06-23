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

from ar_core.evidence.integrator import integrate_complete_exam
from scripts.validate_json_outputs import validate_file


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _synthetic_measurements(case_id: str) -> list[dict]:
    return [
        {
            "measurement_id": f"{case_id}_vcw",
            "metric": "vena_contracta_width_cm",
            "value": 0.72,
            "unit": "cm",
            "per_frame_values": [{"frame_index": 3, "value": 0.72}],
            "selected_frames": [{"source_file": "examples/mock_case/synthetic_color_doppler.dcm", "frame_index": 3}],
            "calibration_source": "synthetic_pixel_spacing:0.01_cm_per_px",
            "formula": "direct calibrated measurement line",
            "uncertainty": {"absolute": 0.02, "unit": "cm"},
            "ase_interpretation": "severe_supporting",
            "technical_validity": "valid",
            "reliability_weight_proposal": 0.9,
            "reliability_reason": "synthetic complete-exam fixture",
            "artifact_paths": [f"runs/{case_id}/agents/vena_contracta/artifacts/vcw_overlay.txt"],
            "quality_flags": [],
        },
        {
            "measurement_id": f"{case_id}_pht",
            "metric": "pressure_half_time_ms",
            "value": 180,
            "unit": "ms",
            "per_frame_values": [],
            "selected_frames": [{"source_file": "examples/mock_case/synthetic_cwd.dcm", "frame_index": 0}],
            "calibration_source": "synthetic_spectral_scale:time_velocity_axes",
            "formula": "pressure half-time from calibrated AR CWD envelope",
            "uncertainty": {"absolute": 8, "unit": "ms"},
            "ase_interpretation": "severe_supporting",
            "technical_validity": "valid",
            "reliability_weight_proposal": 0.75,
            "reliability_reason": "synthetic complete-exam fixture; PHT is load dependent",
            "artifact_paths": [f"runs/{case_id}/agents/cwd_analysis/artifacts/cwd_envelope_overlay.txt"],
            "quality_flags": ["load_dependent_metric"],
        },
    ]


def run(case_id: str) -> dict:
    run_dir = ROOT / "runs" / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    measurements = _synthetic_measurements(case_id)
    for measurement in measurements:
        for artifact_path in measurement["artifact_paths"]:
            artifact = ROOT / artifact_path
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(f"synthetic inspectable artifact for {measurement['metric']}\n")

    agents_dir = run_dir / "agents"
    agent_names = ["case_ingestion", "evidence_integrator", "medical_safety_reviewer", "report_generator"]
    agent_results = []
    for agent_name in agent_names:
        result = {
            "task_id": f"{case_id}_{agent_name}",
            "case_id": case_id,
            "agent_name": agent_name,
            "status": "success",
            "tool_ids": ["deterministic_mock_tools:1.0.0"],
            "skills_used": ["ar-case-orchestration"],
            "input_artifacts": [],
            "output_artifacts": [path for measurement in measurements for path in measurement["artifact_paths"]],
            "measurements": measurements if agent_name in {"evidence_integrator", "report_generator"} else [],
            "evidence": {},
            "confidence": 0.8,
            "quality_flags": ["synthetic_complete_exam"],
            "assumptions": [],
            "limitations": ["Synthetic fixture; no clinical validation claimed."],
            "errors": [],
            "medical_sources": ["ase_2017_native_valvular_regurgitation"],
            "provenance": {"created_at": datetime.now(timezone.utc).isoformat()},
            "review_required": agent_name not in {"medical_safety_reviewer"},
        }
        path = agents_dir / agent_name / "result.json"
        _write_json(path, result)
        validate_file(path, ROOT / "schemas" / "agent_result.schema.json")
        agent_results.append(str(path.relative_to(ROOT)))

    report = deepcopy(json.loads((ROOT / "examples" / "expected_outputs" / "final_report_complete.json").read_text()))
    report["case_id"] = case_id
    report["audit_path"] = f"runs/{case_id}/audit.json"
    report["artifact_index_path"] = f"runs/{case_id}/artifact_index.json"
    report["agent_results"] = agent_results
    report["measurements"] = measurements
    evidence = integrate_complete_exam(measurements, required_metrics=report["measurement_completeness"]["required_metrics"])
    report["severity"] = evidence["severity"]
    report["trusted_metrics"] = evidence["trusted_metrics"]
    report["downweighted_metrics"] = evidence["downweighted_metrics"]
    report["excluded_metrics"] = evidence["excluded_metrics"]
    report["discordances"] = evidence["discordances"]
    report["missing_information"] = evidence["missing_information"]
    final_report_path = run_dir / "final_report.json"
    _write_json(final_report_path, report)
    validate_file(final_report_path, ROOT / "schemas" / "final_report.schema.json")

    _write_json(
        run_dir / "artifact_index.json",
        {
            "case_id": case_id,
            "artifacts": [path for measurement in measurements for path in measurement["artifact_paths"]],
            "notes": ["Synthetic artifacts exercise measurable complete-exam contracts without patient data."],
        },
    )
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
                "complete output with quantitative calibrated measurements",
            ],
            "research_use_only": True,
        },
    )
    return {"status": "success", "case_id": case_id, "final_report_path": str(final_report_path.relative_to(ROOT))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default="mock_case_complete")
    args = parser.parse_args()
    print(json.dumps(run(args.case_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
