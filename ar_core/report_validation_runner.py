"""Run report-derived AR reasoning validation through the existing evaluator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ar_core.evidence.integrator import (
    DEFAULT_REQUIRED_COMPLETE_EXAM_METRICS,
    MeasurementRepairRequired,
    integrate_complete_exam,
)
from ar_core.report_ingestion import severity_evidence_measurements

GUIDELINE_SOURCE_ID = "ase_2017_native_valvular_regurgitation"

_SOURCE_MAP_ENTRIES = {
    "ar_integrative_assessment": {
        "rule_id": "ar_integrative_assessment",
        "source_id": GUIDELINE_SOURCE_ID,
        "source_file": "2017VavularRegurgitationGuideline.pdf",
        "section": "Aortic Regurgitation",
        "table_or_figure": "Table 11 and Figure 25",
        "pages": [38, 42, 43],
        "implementation_use": "AR severity thresholds, specific mild/severe criteria, and integrative handling of discordant quantitative findings without changing thresholds.",
    },
    "vena_contracta_width": {
        "rule_id": "vena_contracta_width",
        "source_id": GUIDELINE_SOURCE_ID,
        "source_file": "2017VavularRegurgitationGuideline.pdf",
        "section": "Aortic Regurgitation",
        "table_or_figure": "Table 11",
        "pages": [38],
        "implementation_use": "VCW severity-support thresholds.",
    },
    "pht_load_dependence": {
        "rule_id": "pht_load_dependence",
        "source_id": GUIDELINE_SOURCE_ID,
        "source_file": "2017VavularRegurgitationGuideline.pdf",
        "section": "Aortic Regurgitation",
        "table_or_figure": "Table 11 and surrounding discussion",
        "pages": [36, 37, 38],
        "implementation_use": "PHT categories and load-dependent limitation.",
    },
    "flow_reversal": {
        "rule_id": "flow_reversal",
        "source_id": GUIDELINE_SOURCE_ID,
        "source_file": "2017VavularRegurgitationGuideline.pdf",
        "section": "Aortic Regurgitation",
        "table_or_figure": "Figure 22 and Table 11",
        "pages": [34, 38, 42],
        "implementation_use": "Brief reversal nonspecific; holodiastolic reversal supports significant/severe AR depending site.",
    },
}


def build_validation_outputs(
    *,
    patient_id: str,
    run_dir: Path,
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Build per-patient evaluator outputs from report-derived measurements."""

    measurements = list(extraction.get("measurements") or [])
    integratable_measurements = severity_evidence_measurements(measurements)
    required_metrics = _unique_preserving_order(measurement["metric"] for measurement in integratable_measurements)
    default_missing = [
        metric for metric in DEFAULT_REQUIRED_COMPLETE_EXAM_METRICS if metric not in set(required_metrics)
    ]
    source_map_entries = _source_map_entries_for_measurements(integratable_measurements)
    evaluator_record: dict[str, Any] = {
        "module": "ar_core.evidence.integrator",
        "function": "integrate_complete_exam",
        "required_metrics_argument": required_metrics,
        "default_complete_exam_required_metrics": list(DEFAULT_REQUIRED_COMPLETE_EXAM_METRICS),
        "default_complete_exam_missing_metrics_from_report": default_missing,
        "severity_result_produced": False,
    }

    try:
        evidence = integrate_complete_exam(integratable_measurements, required_metrics=required_metrics)
        evidence_result = {
            "case_id": patient_id,
            **evidence,
            "guideline_provenance": source_map_entries,
        }
        evaluator_record["severity_result_produced"] = True
    except MeasurementRepairRequired as exc:
        evidence_result = _repair_required_evidence_result(
            patient_id=patient_id,
            message=str(exc),
            repair_requests=exc.repair_tasks,
            measurements=integratable_measurements,
            guideline_provenance=source_map_entries,
        )

    final_report = _build_final_report(
        patient_id=patient_id,
        run_dir=run_dir,
        extraction=extraction,
        evidence_result=evidence_result,
        measurements=measurements,
        integratable_measurements=integratable_measurements,
        required_metrics=required_metrics,
        default_missing=default_missing,
        guideline_provenance=source_map_entries,
    )
    audit = _build_audit(
        patient_id=patient_id,
        run_dir=run_dir,
        extraction=extraction,
        evidence_result=evidence_result,
        evaluator_record=evaluator_record,
        source_map_entries=source_map_entries,
    )
    artifact_index = {
        "case_id": patient_id,
        "mode": "severity_reasoning_validation",
        "artifacts": [
            str(run_dir / "report_extraction.json"),
            str(run_dir / "measurements_from_report.json"),
            str(run_dir / "evidence_result.json"),
            str(run_dir / "final_report.json"),
            str(run_dir / "severity_reasoning_audit.json"),
        ],
        "notes": [
            "Report-derived validation inputs only; no image measurements were performed.",
            "Artifacts may contain report snippets and must remain under ignored run paths.",
        ],
    }
    return {
        "evidence_result": evidence_result,
        "final_report": final_report,
        "audit": audit,
        "artifact_index": artifact_index,
    }


def write_patient_outputs(
    *,
    run_dir: Path,
    extraction: dict[str, Any],
    outputs: dict[str, Any],
) -> dict[str, str]:
    """Write required per-patient validation artifacts."""

    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report_extraction": run_dir / "report_extraction.json",
        "measurements_from_report": run_dir / "measurements_from_report.json",
        "evidence_result": run_dir / "evidence_result.json",
        "final_report": run_dir / "final_report.json",
        "severity_reasoning_audit": run_dir / "severity_reasoning_audit.json",
        "artifact_index": run_dir / "artifact_index.json",
    }
    _write_json(paths["report_extraction"], extraction)
    _write_json(
        paths["measurements_from_report"],
        {
            "case_id": extraction["patient_id"],
            "source_type": extraction["source_type"],
            "report_filename": extraction["report_filename"],
            "measurements": extraction["measurements"],
            "schema": "schemas/measurement_result.schema.json per measurement item",
            "limitations": extraction["limitations"],
        },
    )
    _write_json(paths["evidence_result"], outputs["evidence_result"])
    _write_json(paths["final_report"], outputs["final_report"])
    _write_json(paths["severity_reasoning_audit"], outputs["audit"])
    _write_json(paths["artifact_index"], outputs["artifact_index"])
    return {key: str(path) for key, path in paths.items()}


def _repair_required_evidence_result(
    *,
    patient_id: str,
    message: str,
    repair_requests: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    guideline_provenance: list[dict[str, Any]],
) -> dict[str, Any]:
    contributions = [
        {
            "metric": measurement["metric"],
            "raw_value": measurement["value"],
            "unit": measurement["unit"],
            "raw_class": measurement.get("ase_interpretation"),
            "included": False,
            "reason": "evaluator requested repair before final severity generation",
            "artifact_paths": measurement.get("artifact_paths", []),
        }
        for measurement in measurements
    ]
    if not contributions:
        contributions = [
            {
                "metric": "report_pdf_extracted_validation_input",
                "included": False,
                "reason": "no explicit AR severity measurement was extracted from the report",
            }
        ]
    return {
        "case_id": patient_id,
        "status": "repair_required",
        "severity": {
            "label": None,
            "confidence": None,
            "evidence_vector": {},
            "reasoning_summary": [message],
        },
        "evidence_vector": {},
        "metric_contributions": contributions,
        "trusted_metrics": [],
        "downweighted_metrics": [],
        "excluded_metrics": [contribution["metric"] for contribution in contributions],
        "discordances": [],
        "missing_information": [],
        "repair_requests": repair_requests
        or [
            {
                "metric": "report_pdf_extracted_validation_input",
                "failure_mode": "no_integratable_ar_severity_measurements",
                "reason": "report did not contain explicit AR measurements mapped to implemented severity evidence fields",
                "repair_action": "provide additional report-derived AR measurements or run image-based measurement agents",
            }
        ],
        "guideline_provenance": guideline_provenance,
    }


def _build_final_report(
    *,
    patient_id: str,
    run_dir: Path,
    extraction: dict[str, Any],
    evidence_result: dict[str, Any],
    measurements: list[dict[str, Any]],
    integratable_measurements: list[dict[str, Any]],
    required_metrics: list[str],
    default_missing: list[str],
    guideline_provenance: list[dict[str, Any]],
) -> dict[str, Any]:
    if evidence_result["status"] != "complete":
        return {
            "case_id": patient_id,
            "analysis_status": "engineering_failure",
            "ar_presence": "unknown",
            "severity": evidence_result["severity"],
            "measurements": measurements,
            "trusted_metrics": [],
            "downweighted_metrics": [],
            "excluded_metrics": evidence_result["excluded_metrics"],
            "discordances": [],
            "missing_information": [],
            "repair_requests": evidence_result["repair_requests"],
            "quality_summary": {
                "report_derived_validation": True,
                "failure_reason": evidence_result["severity"]["reasoning_summary"],
                "blocked_reason": _blocked_reason(extraction=extraction, evidence_result=evidence_result),
                "final_report_schema_validation": "not_validated_existing_schema_requires_complete_analysis_status",
            },
            "recommendations": [
                "Do not use this run as image-measurement validation.",
                "Provide explicit report AR measurements or run upstream image-based measurement agents before final severity reporting.",
            ],
            "guideline_provenance": guideline_provenance,
            "audit_path": str(run_dir / "severity_reasoning_audit.json"),
            "artifact_index_path": str(run_dir / "artifact_index.json"),
            "research_use_only": True,
        }

    return {
        "case_id": patient_id,
        "analysis_status": "complete",
        "ar_presence": "present",
        "probable_mechanism": {
            "label": "not_assessed_report_derived_validation_input",
            "confidence": 0.0,
            "limitations": ["Mechanism was not assessed from images in this report-derived reasoning validation run."],
        },
        "severity": evidence_result["severity"],
        "measurements": measurements or integratable_measurements,
        "trusted_metrics": evidence_result["trusted_metrics"],
        "downweighted_metrics": evidence_result["downweighted_metrics"],
        "excluded_metrics": evidence_result["excluded_metrics"],
        "discordances": evidence_result["discordances"],
        "missing_information": [],
        "quality_summary": {
            "report_derived_validation": True,
            "image_measurements_performed": False,
            "complete_exam_default_missing_metrics_from_report": default_missing,
            "report_extraction_limitations": extraction.get("limitations", []),
        },
        "recommendations": [
            "Use only to validate implemented AR severity reasoning from report-derived inputs.",
            "Do not claim image measurement accuracy or clinical validation from this run.",
        ],
        "guideline_provenance": guideline_provenance,
        "agent_results": [
            {
                "agent_name": "report_pdf_ingestion_handle",
                "artifact_path": str(run_dir / "report_extraction.json"),
                "source_type": extraction["source_type"],
            },
            {
                "agent_name": "existing_ar_evidence_integrator",
                "module": "ar_core.evidence.integrator",
                "function": "integrate_complete_exam",
            },
        ],
        "tool_versions": [
            {
                "tool_id": "scripts/extract_report_measurements.py",
                "version": "1.0.0",
                "clinical_validation": False,
            }
        ],
        "audit_path": str(run_dir / "severity_reasoning_audit.json"),
        "artifact_index_path": str(run_dir / "artifact_index.json"),
        "measurement_completeness": {
            "required_metrics": required_metrics,
            "default_complete_exam_required_metrics": list(DEFAULT_REQUIRED_COMPLETE_EXAM_METRICS),
            "default_complete_exam_missing_metrics_from_report": default_missing,
            "repair_history": [],
            "complete_exam_assumption": True,
            "report_derived_validation_not_image_complete_exam": True,
        },
        "research_use_only": True,
    }


def _build_audit(
    *,
    patient_id: str,
    run_dir: Path,
    extraction: dict[str, Any],
    evidence_result: dict[str, Any],
    evaluator_record: dict[str, Any],
    source_map_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "case_id": patient_id,
        "mode": "severity_reasoning_validation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_type": "report_derived_validation_input_not_image_measurement",
        "external_services": [],
        "report_filename": extraction["report_filename"],
        "report_stated_ar_severity": extraction.get("report_stated_ar_severity"),
        "extracted_values": extraction.get("mapping_audit", []),
        "measurement_mapping": extraction.get("mapping_audit", []),
        "severity_evaluator": evaluator_record,
        "ase_source_map_entries_used": source_map_entries,
        "report_severity_agreement": _agreement_record(
            report_stated=extraction.get("report_stated_ar_severity"),
            evidence_result=evidence_result,
        ),
        "blocked_reason": _blocked_reason(extraction=extraction, evidence_result=evidence_result),
        "validation_scope": {
            "validates": "implemented AR evidence interpretation/integration and final severity generation from report-derived measurements",
            "does_not_validate": "image acquisition, segmentation, calibration extraction, Doppler envelope extraction, or measurement accuracy",
        },
        "limitations": extraction.get("limitations", []),
        "repair_requests": evidence_result.get("repair_requests", []),
        "output_paths": {
            "report_extraction": str(run_dir / "report_extraction.json"),
            "measurements_from_report": str(run_dir / "measurements_from_report.json"),
            "evidence_result": str(run_dir / "evidence_result.json"),
            "final_report": str(run_dir / "final_report.json"),
            "severity_reasoning_audit": str(run_dir / "severity_reasoning_audit.json"),
        },
    }


def _agreement_record(*, report_stated: str | None, evidence_result: dict[str, Any]) -> dict[str, Any]:
    system_label = evidence_result.get("severity", {}).get("label")
    if not report_stated:
        return {
            "status": "no_report_stated_ar_severity",
            "report_stated_severity": None,
            "system_severity": system_label,
            "disagreement_category": None,
        }
    if not system_label:
        return {
            "status": "not_assessable_no_system_severity",
            "report_stated_severity": report_stated,
            "system_severity": None,
            "disagreement_category": "missing_report_metrics_or_evaluator_repair_required",
        }
    status = "agreement" if _normalize_label(report_stated) == _normalize_label(system_label) else "disagreement"
    return {
        "status": status,
        "report_stated_severity": report_stated,
        "system_severity": system_label,
        "disagreement_category": None if status == "agreement" else "evaluator_reasoning_or_report_input_mapping",
    }


def _blocked_reason(*, extraction: dict[str, Any], evidence_result: dict[str, Any]) -> dict[str, Any] | None:
    if evidence_result.get("status") == "complete":
        return None
    measurements = list(extraction.get("measurements") or [])
    integratable = severity_evidence_measurements(measurements)
    report_stated = extraction.get("report_stated_ar_severity")
    if not measurements:
        category = "missing_report_metric"
        detail = "No explicit AR measurement or report-stated AR severity was extracted from the report."
    elif not integratable and report_stated:
        category = "evaluator_reasoning"
        detail = "The report stated AR severity, but no implemented evaluator-compatible severity evidence was available."
    elif not integratable:
        category = "missing_report_metric"
        detail = "Extracted report values were remodeling/context or non-AR values, not implemented AR severity evidence."
    else:
        category = "evaluator_reasoning"
        detail = "Implemented evaluator requested repair for extracted AR severity evidence."
    return {
        "category": category,
        "detail": detail,
        "pdf_discovery": "local_pdf_found",
        "text_extraction": "pdf_text_available",
        "mapping": "report_ingestion_adapter",
        "evaluator": "ar_core.evidence.integrator.integrate_complete_exam",
    }


def _source_map_entries_for_measurements(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rule_ids = {"ar_integrative_assessment"}
    for measurement in measurements:
        rule_ids.update(measurement.get("source_map_rule_ids") or [])
    ordered_rule_ids = [rule_id for rule_id in _SOURCE_MAP_ENTRIES if rule_id in rule_ids]
    return [_SOURCE_MAP_ENTRIES[rule_id] for rule_id in ordered_rule_ids]


def _unique_preserving_order(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _normalize_label(label: str) -> str:
    return label.lower().replace(" ", "_").replace("-", "_")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
