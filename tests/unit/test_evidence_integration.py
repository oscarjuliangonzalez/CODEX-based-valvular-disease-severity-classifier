import pytest

from ar_core.evidence.integrator import MeasurementRepairRequired, integrate_complete_exam


def measurement(metric: str, value: float, ase_interpretation: str) -> dict:
    return {
        "measurement_id": f"{metric}_synthetic",
        "metric": metric,
        "value": value,
        "unit": "cm",
        "per_frame_values": [],
        "selected_frames": [{"source_file": "synthetic.dcm", "frame_index": 3}],
        "calibration_source": "synthetic_calibration:pixel_spacing",
        "formula": "direct calibrated measurement",
        "uncertainty": {"absolute": 0.01, "unit": "cm"},
        "ase_interpretation": ase_interpretation,
        "technical_validity": "valid",
        "reliability_weight_proposal": 0.9,
        "reliability_reason": "synthetic complete-exam fixture",
        "artifact_paths": ["runs/synthetic/artifacts/overlay.png"],
        "quality_flags": [],
    }


def test_complete_exam_integration_rejects_missing_required_measurements_as_repair_failure():
    with pytest.raises(MeasurementRepairRequired) as exc:
        integrate_complete_exam(
            [measurement("vena_contracta_width_cm", 0.72, "severe_supporting")],
            required_metrics=["vena_contracta_width_cm", "pressure_half_time_ms"],
        )

    assert "pressure_half_time_ms" in str(exc.value)
    assert exc.value.repair_tasks[0]["failure_mode"] == "missing_required_measurement"


def test_complete_exam_integration_rejects_measurements_without_artifact_provenance():
    bad = measurement("pressure_half_time_ms", 180, "severe_supporting")
    bad["artifact_paths"] = []

    with pytest.raises(MeasurementRepairRequired) as exc:
        integrate_complete_exam([bad], required_metrics=["pressure_half_time_ms"])

    assert exc.value.repair_tasks[0]["failure_mode"] == "invalid_measurement_contract"
    assert "artifact_paths" in exc.value.repair_tasks[0]["reason"]


def test_complete_exam_integration_returns_quantitative_non_indeterminate_result():
    result = integrate_complete_exam(
        [
            measurement("vena_contracta_width_cm", 0.72, "severe_supporting"),
            measurement("pressure_half_time_ms", 180, "severe_supporting"),
        ],
        required_metrics=["vena_contracta_width_cm", "pressure_half_time_ms"],
    )

    assert result["status"] == "complete"
    assert result["severity"]["label"] == "severe"
    assert result["severity"]["confidence"] in {"moderate", "high"}
    assert result["missing_information"] == []
    assert result["repair_requests"] == []
