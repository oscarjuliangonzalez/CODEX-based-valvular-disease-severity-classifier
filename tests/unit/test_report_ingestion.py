from pathlib import Path

from ar_core.report_ingestion import extract_report_data_from_pages
from ar_core.report_validation_runner import build_validation_outputs


def test_extracts_ai_pressure_half_time_as_report_derived_measurement():
    extraction = extract_report_data_from_pages(
        patient_id="A2",
        report_path=Path("REPORTS/A2/RPT00000.PDF"),
        pages=[
            {
                "page_number": 2,
                "text": "\n".join(
                    [
                        "Aortic Insufficiency:",
                        "AI Half-time: 341 msec",
                        "AI Decel Rate: 3.18 m/s2",
                    ]
                ),
            }
        ],
        run_dir=Path("runs/severity_reasoning_validation/A2"),
    )

    assert extraction["report_stated_ar_severity"] is None
    measurement = extraction["measurements"][0]
    assert measurement["metric"] == "pressure_half_time_ms"
    assert measurement["value"] == 341
    assert measurement["unit"] == "ms"
    assert measurement["report_unit"] == "msec"
    assert measurement["ase_interpretation"] == "intermediate"
    assert measurement["technical_validity"] == "valid"
    assert measurement["provenance"]["source_type"] == "report_pdf_extracted_validation_input"
    assert measurement["provenance"]["page_number"] == 2
    assert "AI Half-time: 341 msec" in measurement["provenance"]["extracted_text_snippet"]
    assert "load_dependent_metric" in measurement["quality_flags"]


def test_extracts_explicit_report_stated_ar_severity_without_grading():
    extraction = extract_report_data_from_pages(
        patient_id="case",
        report_path=Path("REPORTS/case/RPT00000.PDF"),
        pages=[
            {
                "page_number": 1,
                "text": "Aortic Valve: There is moderate aortic regurgitation.",
            }
        ],
        run_dir=Path("runs/severity_reasoning_validation/case"),
    )

    assert extraction["report_stated_ar_severity"] == "moderate"
    assert extraction["measurements"][0]["metric"] == "report_stated_ar_severity"
    assert extraction["measurements"][0]["report_value"] == "moderate"
    assert extraction["measurements"][0]["value"] == 2
    assert extraction["measurements"][0]["evidence_role"] == "severity_evidence"
    assert extraction["limitations"] == []


def test_maps_report_stated_ar_severity_as_report_derived_input():
    extraction = extract_report_data_from_pages(
        patient_id="A9",
        report_path=Path("REPORTS/A9/RPT00000.PDF"),
        pages=[
            {
                "page_number": 3,
                "text": "Aortic Valve: Color flow PW Doppler reveals mild aortic valve regurgitation.",
            }
        ],
        run_dir=Path("runs/severity_reasoning_validation/A9"),
    )

    assert extraction["report_stated_ar_severity"] == "mild"
    measurement = extraction["measurements"][0]
    assert measurement["metric"] == "report_stated_ar_severity"
    assert measurement["value"] == 1
    assert measurement["unit"] == "ordinal_report_label"
    assert measurement["report_value"] == "mild"
    assert measurement["ase_interpretation"] == "mild_supporting"
    assert measurement["technical_validity"] == "limited"
    assert measurement["evidence_role"] == "severity_evidence"
    assert "direct_report_stated_severity" in measurement["quality_flags"]
    assert measurement["provenance"]["page_number"] == 3
    assert "mild aortic valve regurgitation" in measurement["provenance"]["extracted_text_snippet"]


def test_extracts_split_lv_biplane_volume_rows_as_context():
    extraction = extract_report_data_from_pages(
        patient_id="A5",
        report_path=Path("REPORTS/A5/RPT00000.PDF"),
        pages=[
            {
                "page_number": 1,
                "text": "\n".join(
                    [
                        "LV Volume:",
                        "A4C- Diast A4C-Syst A2C-Diast A2C-Syst Biplane-Diast Biplane-Syst",
                        "286.5 ml 184.5 ml 317.0 ml 204.0 ml 304.8 ml 196.4 ml",
                    ]
                ),
            }
        ],
        run_dir=Path("runs/severity_reasoning_validation/A5"),
    )

    measurements = {measurement["metric"]: measurement for measurement in extraction["measurements"]}
    assert measurements["lv_edv_biplane_ml"]["value"] == 304.8
    assert measurements["lv_esv_biplane_ml"]["value"] == 196.4
    assert measurements["lv_edv_biplane_ml"]["evidence_role"] == "remodeling_context"
    assert measurements["lv_edv_biplane_ml"]["ase_interpretation"] == "context_only_not_integrated"
    assert measurements["lv_edv_biplane_ml"]["provenance"]["page_number"] == 1


def test_does_not_invent_ar_measurements_from_unrelated_aortic_valve_values():
    extraction = extract_report_data_from_pages(
        patient_id="A57",
        report_path=Path("REPORTS/A57/RPT00000.PDF"),
        pages=[
            {
                "page_number": 2,
                "text": "\n".join(
                    [
                        "Aortic Valve:",
                        "AoV Max Vel: 4 m/s AoV Peak PG: 76 mmHg AoV Mean PG: 43.0 mmHg",
                        "AoV VTI: 96.200 cm",
                    ]
                ),
            }
        ],
        run_dir=Path("runs/severity_reasoning_validation/A57"),
    )

    assert extraction["measurements"] == []
    assert "no_explicit_ar_measurements_extracted" in extraction["limitations"]


def test_validation_outputs_use_existing_integrator_for_available_report_evidence():
    extraction = extract_report_data_from_pages(
        patient_id="A2",
        report_path=Path("REPORTS/A2/RPT00000.PDF"),
        pages=[{"page_number": 2, "text": "Aortic Insufficiency:\nAI Half-time: 341 msec"}],
        run_dir=Path("runs/severity_reasoning_validation/A2"),
    )

    outputs = build_validation_outputs(
        patient_id="A2",
        run_dir=Path("runs/severity_reasoning_validation/A2"),
        extraction=extraction,
    )

    assert outputs["evidence_result"]["status"] == "complete"
    assert outputs["evidence_result"]["severity"]["label"] == "moderate"
    assert outputs["final_report"]["severity"]["label"] == "moderate"
    assert outputs["audit"]["severity_evaluator"]["module"] == "ar_core.evidence.integrator"
    assert outputs["audit"]["severity_evaluator"]["function"] == "integrate_complete_exam"
    assert outputs["audit"]["report_severity_agreement"]["status"] == "no_report_stated_ar_severity"


def test_validation_outputs_integrate_report_stated_ar_severity_through_existing_evaluator():
    extraction = extract_report_data_from_pages(
        patient_id="A9",
        report_path=Path("REPORTS/A9/RPT00000.PDF"),
        pages=[{"page_number": 3, "text": "Color flow PW Doppler reveals mild aortic valve regurgitation."}],
        run_dir=Path("runs/severity_reasoning_validation/A9"),
    )

    outputs = build_validation_outputs(
        patient_id="A9",
        run_dir=Path("runs/severity_reasoning_validation/A9"),
        extraction=extraction,
    )

    assert outputs["evidence_result"]["status"] == "complete"
    assert outputs["evidence_result"]["severity"]["label"] == "mild"
    assert outputs["audit"]["severity_evaluator"]["module"] == "ar_core.evidence.integrator"
    assert outputs["audit"]["report_severity_agreement"]["status"] == "agreement"


def test_validation_outputs_record_repair_required_when_report_has_no_integratable_ar_evidence():
    extraction = extract_report_data_from_pages(
        patient_id="A57",
        report_path=Path("REPORTS/A57/RPT00000.PDF"),
        pages=[{"page_number": 2, "text": "Aortic Valve:\nAoV Max Vel: 4 m/s"}],
        run_dir=Path("runs/severity_reasoning_validation/A57"),
    )

    outputs = build_validation_outputs(
        patient_id="A57",
        run_dir=Path("runs/severity_reasoning_validation/A57"),
        extraction=extraction,
    )

    assert outputs["evidence_result"]["status"] == "repair_required"
    assert outputs["evidence_result"]["severity"]["label"] is None
    assert outputs["final_report"]["analysis_status"] == "engineering_failure"
    assert outputs["audit"]["severity_evaluator"]["severity_result_produced"] is False
    assert outputs["audit"]["blocked_reason"]["category"] == "missing_report_metric"
