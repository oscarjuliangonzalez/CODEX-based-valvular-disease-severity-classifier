#!/usr/bin/env python3
"""Extract report-derived AR inputs and run existing severity reasoning logic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_core.report_ingestion import discover_report_pdfs, extract_report_data
from ar_core.report_validation_runner import build_validation_outputs, write_patient_outputs
from scripts.validate_json_outputs import _fallback_validate, validate_file


def validate_payload(payload: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    try:
        import jsonschema  # type: ignore
    except Exception:
        jsonschema = None
    if jsonschema is not None:
        jsonschema.validate(instance=payload, schema=schema)
    else:
        _fallback_validate(payload, schema)


def validate_written_outputs(paths: dict[str, str], extraction: dict[str, Any], final_status: str) -> list[dict[str, str]]:
    validations: list[dict[str, str]] = []
    evidence_path = Path(paths["evidence_result"])
    validate_file(evidence_path, ROOT / "schemas" / "evidence_result.schema.json")
    validations.append({"artifact": str(evidence_path), "schema": "schemas/evidence_result.schema.json", "status": "valid"})

    for measurement in extraction.get("measurements", []):
        validate_payload(measurement, ROOT / "schemas" / "measurement_result.schema.json")
    validations.append(
        {
            "artifact": paths["measurements_from_report"],
            "schema": "schemas/measurement_result.schema.json per measurement item",
            "status": "valid",
        }
    )

    final_path = Path(paths["final_report"])
    if final_status == "complete":
        validate_file(final_path, ROOT / "schemas" / "final_report.schema.json")
        status = "valid"
    else:
        status = "not_validated_existing_schema_requires_complete_analysis_status"
    validations.append({"artifact": str(final_path), "schema": "schemas/final_report.schema.json", "status": status})
    return validations


def patient_id_for_report(report_path: Path, reports_dir: Path) -> str:
    try:
        relative = report_path.relative_to(reports_dir)
    except ValueError:
        return report_path.parent.name
    return relative.parts[0] if len(relative.parts) > 1 else report_path.stem


def run(args: argparse.Namespace) -> dict[str, Any]:
    reports_dir = Path(args.reports_dir)
    output_root = Path(args.output_root)
    report_pdfs = discover_report_pdfs(reports_dir)
    pdf_patient_ids = {patient_id_for_report(path, reports_dir) for path in report_pdfs}
    patient_dirs_without_pdf = sorted(
        path.name for path in reports_dir.iterdir() if path.is_dir() and path.name not in pdf_patient_ids
    )

    summary: dict[str, Any] = {
        "mode": "severity_reasoning_validation",
        "source_type": "report_pdf_extracted_validation_input",
        "reports_dir": str(reports_dir),
        "output_root": str(output_root),
        "expected_report_count": args.expected_report_count,
        "reports_found": len(report_pdfs),
        "report_count_matches_expected": len(report_pdfs) == args.expected_report_count,
        "patient_dirs_without_pdf": patient_dirs_without_pdf,
        "patients": [],
        "limitations": [],
    }
    if len(report_pdfs) != args.expected_report_count:
        summary["limitations"].append(
            f"expected {args.expected_report_count} report PDFs but found {len(report_pdfs)} local PDF files"
        )
    if patient_dirs_without_pdf:
        summary["limitations"].append("one or more patient directories under REPORTS did not contain a PDF")

    output_root.mkdir(parents=True, exist_ok=True)
    for report_path in report_pdfs:
        patient_id = patient_id_for_report(report_path, reports_dir)
        run_dir = output_root / patient_id
        extraction = extract_report_data(patient_id=patient_id, report_path=report_path, run_dir=run_dir)
        outputs = build_validation_outputs(patient_id=patient_id, run_dir=run_dir, extraction=extraction)
        paths = write_patient_outputs(run_dir=run_dir, extraction=extraction, outputs=outputs)
        validations = validate_written_outputs(paths, extraction, outputs["evidence_result"]["status"])
        summary["patients"].append(
            {
                "patient_id": patient_id,
                "report_path": str(report_path),
                "measurements_extracted": len(extraction["measurements"]),
                "integrator_status": outputs["evidence_result"]["status"],
                "system_severity": outputs["evidence_result"]["severity"].get("label"),
                "report_stated_ar_severity": extraction.get("report_stated_ar_severity"),
                "agreement_status": outputs["audit"]["report_severity_agreement"]["status"],
                "output_dir": str(run_dir),
                "validations": validations,
            }
        )

    summary_path = output_root / "validation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", default="REPORTS")
    parser.add_argument("--output-root", default="runs/severity_reasoning_validation")
    parser.add_argument("--expected-report-count", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
