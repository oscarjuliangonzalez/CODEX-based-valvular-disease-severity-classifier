"""Deterministic evidence integration for complete AR exam workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_REQUIRED_COMPLETE_EXAM_METRICS = (
    "vena_contracta_width_cm",
    "jet_width_lvot_ratio",
    "ar_cwd_vmax_m_s",
    "ar_cwd_vti_cm",
    "pressure_half_time_ms",
    "diastolic_flow_reversal",
    "regurgitant_volume_ml_per_beat",
    "regurgitant_fraction_percent",
    "eroa_cm2",
)


@dataclass
class MeasurementRepairRequired(RuntimeError):
    """Raised when complete-exam quantitative evidence is missing or invalid."""

    message: str
    repair_tasks: list[dict[str, Any]]

    def __str__(self) -> str:
        return self.message


def _class_bucket(classification: str | None) -> str:
    if not classification:
        return "unclassified_support"
    if "mild" in classification:
        return "mild_support"
    if "severe" in classification:
        return "severe_support"
    if "moderate" in classification or "intermediate" in classification:
        return "moderate_support"
    return "unclassified_support"


def _severity_label(classification: str | None) -> str | None:
    if not classification:
        return None
    if "mild" in classification:
        return "mild"
    if "severe" in classification:
        return "severe"
    if "moderate" in classification or "intermediate" in classification:
        return "moderate"
    return None


def _metric_name(measurement: dict[str, Any]) -> str:
    return str(measurement.get("metric") or "unknown_metric")


def _invalid_contract_reasons(measurement: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not isinstance(measurement.get("value"), (int, float)) or isinstance(measurement.get("value"), bool):
        reasons.append("value must be numeric")
    if not measurement.get("unit"):
        reasons.append("unit is required")
    if not measurement.get("calibration_source"):
        reasons.append("calibration_source is required")
    if not measurement.get("artifact_paths"):
        reasons.append("artifact_paths must contain at least one inspectable artifact")
    if not measurement.get("ase_interpretation"):
        reasons.append("ase_interpretation is required")
    if measurement.get("technical_validity") == "invalid":
        reasons.append("technical_validity is invalid")
    return reasons


def _repair_failure(message: str, repair_tasks: list[dict[str, Any]]) -> MeasurementRepairRequired:
    return MeasurementRepairRequired(message=message, repair_tasks=repair_tasks)


def _validate_required_measurements(
    measurements: list[dict[str, Any]],
    required_metrics: Iterable[str],
) -> None:
    by_metric = {_metric_name(measurement): measurement for measurement in measurements}
    repair_tasks: list[dict[str, Any]] = []
    for metric in required_metrics:
        if metric not in by_metric:
            repair_tasks.append(
                {
                    "metric": metric,
                    "failure_mode": "missing_required_measurement",
                    "reason": "required complete-exam metric was not produced",
                    "repair_action": "inspect source exam data, improve extraction/calibration/segmentation/spectral adapter, and rerun measurement",
                }
            )
            continue
        reasons = _invalid_contract_reasons(by_metric[metric])
        if reasons:
            repair_tasks.append(
                {
                    "metric": metric,
                    "failure_mode": "invalid_measurement_contract",
                    "reason": "; ".join(reasons),
                    "repair_action": "repair measurement provenance/artifacts/calibration and rerun before evidence integration",
                }
            )
    if repair_tasks:
        missing = ", ".join(task["metric"] for task in repair_tasks)
        raise _repair_failure(
            f"complete exam requires quantitative measurement repair before integration: {missing}",
            repair_tasks,
        )


def integrate_complete_exam(
    measurements: list[dict[str, Any]],
    required_metrics: Iterable[str] = DEFAULT_REQUIRED_COMPLETE_EXAM_METRICS,
) -> dict[str, Any]:
    """Integrate complete-exam quantitative AR measurements.

    Missing or invalid required metrics are engineering/tooling failures. This
    function does not emit a terminal clinical fallback for complete exams.
    """

    _validate_required_measurements(measurements, required_metrics)

    contributions = []
    trusted_metrics = []
    downweighted_metrics = []
    excluded_metrics = []
    evidence_vector = {
        "mild_support": 0.0,
        "moderate_support": 0.0,
        "severe_support": 0.0,
        "unclassified_support": 0.0,
    }

    for measurement in measurements:
        metric = _metric_name(measurement)
        validity = measurement.get("technical_validity", "invalid")
        raw_class = measurement.get("ase_interpretation")
        base_reliability = float(measurement.get("reliability_weight_proposal", 0.5))
        adjusted_reliability = max(0.0, min(1.0, base_reliability))
        included = validity != "invalid"
        adjustment_reason = measurement.get("reliability_reason", "")

        if validity == "limited":
            adjusted_reliability *= 0.5
            downweighted_metrics.append(metric)
            adjustment_reason = adjustment_reason or "technical validity is limited"
        elif validity == "invalid":
            adjusted_reliability = 0.0
            excluded_metrics.append(metric)
            adjustment_reason = adjustment_reason or "technical validity is invalid"
        else:
            trusted_metrics.append(metric)

        bucket = _class_bucket(raw_class)
        evidence_vector[bucket] += adjusted_reliability
        contributions.append(
            {
                "metric": metric,
                "raw_value": measurement.get("value"),
                "unit": measurement.get("unit"),
                "raw_class": raw_class,
                "base_reliability": base_reliability,
                "adjusted_reliability": adjusted_reliability,
                "adjustment_reason": adjustment_reason,
                "included": included,
                "artifact_paths": measurement.get("artifact_paths", []),
                "calibration_source": measurement.get("calibration_source"),
            }
        )

    included_labels = {
        label
        for label in (_severity_label(item["raw_class"]) for item in contributions if item["included"] and item["adjusted_reliability"] > 0)
        if label
    }
    discordances = []
    if len(included_labels) > 1:
        discordances.append({"classes": sorted(included_labels), "reason": "included metrics cross severity-support categories"})

    total = sum(evidence_vector.values())
    if total <= 0:
        raise _repair_failure(
            "complete exam produced no usable weighted AR evidence",
            [
                {
                    "metric": "all_required_metrics",
                    "failure_mode": "no_usable_weighted_evidence",
                    "reason": "all measurements were invalid or unclassified",
                    "repair_action": "repair rejected measurements and rerun evidence integration",
                }
            ],
        )

    normalized_vector = {key: value / total for key, value in evidence_vector.items()}
    dominant_bucket, dominant_support = max(normalized_vector.items(), key=lambda item: item[1])
    severity_label = dominant_bucket.replace("_support", "")
    if severity_label == "unclassified":
        raise _repair_failure(
            "complete exam measurements lack ASE severity interpretations",
            [
                {
                    "metric": "ase_interpretation",
                    "failure_mode": "missing_guideline_interpretation",
                    "reason": "dominant evidence is unclassified",
                    "repair_action": "apply ASE-grounded interpretation to calibrated measurements and rerun",
                }
            ],
        )

    confidence = "high" if dominant_support >= 0.75 and not discordances else "moderate"
    if discordances or dominant_support < 0.55:
        confidence = "low"

    return {
        "status": "complete",
        "severity": {
            "label": severity_label,
            "confidence": confidence,
            "evidence_vector": normalized_vector,
            "reasoning_summary": [
                "Complete-exam quantitative measurements were integrated after unit, calibration, and artifact provenance checks."
            ],
        },
        "evidence_vector": normalized_vector,
        "metric_contributions": contributions,
        "trusted_metrics": trusted_metrics,
        "downweighted_metrics": downweighted_metrics,
        "excluded_metrics": excluded_metrics,
        "discordances": discordances,
        "missing_information": [],
        "repair_requests": [],
    }


def conservative_integrate(measurements: list[dict[str, Any]], missing_information: list[str]) -> dict[str, Any]:
    """Backward-compatible entry point now enforcing complete-exam repair.

    For the provided complete exams, missing information is an upstream tooling
    defect, so callers must repair extraction before integration.
    """

    if missing_information:
        raise _repair_failure(
            "complete exam cannot be integrated while required information is marked missing",
            [
                {
                    "metric": item,
                    "failure_mode": "missing_required_information",
                    "reason": "caller supplied missing_information for a complete exam",
                    "repair_action": "create or refine the relevant extraction adapter and rerun measurement",
                }
                for item in missing_information
            ],
        )
    required_metrics = tuple(_metric_name(measurement) for measurement in measurements)
    return integrate_complete_exam(measurements, required_metrics=required_metrics)
