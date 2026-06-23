import json
from pathlib import Path

import pytest

from scripts.validate_json_outputs import validate_file


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_TERMINAL_FALLBACKS = [
    "insufficient_data",
    "indeterminate",
    "abstained",
    "abstention_conditions",
    "return insufficient",
    "return `indeterminate`",
]


def test_cli_template_forbids_insufficient_information_fallback_for_complete_exams():
    text = (ROOT / "prompts" / "CLI_AR_EXECUTION_TEMPLATE.md").read_text().lower()

    assert "complete high-quality exam" in text
    assert "tooling defect" in text
    assert "engineering failure" in text
    for forbidden in ["return `indeterminate`", "insufficient information", "indeterminate_reason"]:
        assert forbidden not in text


def test_project_skills_define_measurable_success_and_repair_loop():
    for path in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")):
        if path.parts[-2] == "relay":
            continue
        text = path.read_text().lower()
        assert "## measurable job" in text, path
        assert "## required inputs" in text, path
        assert "## calibration and units" in text, path
        assert "## required artifacts" in text, path
        assert "## first failed attempt" in text, path
        assert "## success criteria" in text, path
        assert "repair_required" in text, path
        for forbidden in FORBIDDEN_TERMINAL_FALLBACKS:
            assert forbidden not in text, f"{path} still contains {forbidden!r}"


def test_custom_agents_have_repair_contract_instead_of_abstention_contract():
    for path in sorted((ROOT / ".codex" / "agents").glob("*.toml")):
        text = path.read_text().lower()
        assert "repair_triggers" in text, path
        assert "complete high-quality exams" in text, path
        assert "repair_required" in text, path
        assert "engineering_failure" in text, path
        for forbidden in ["abstention_conditions", "insufficient_data", "abstained", "do not force severity when evidence is insufficient"]:
            assert forbidden not in text, f"{path} still contains {forbidden!r}"


def test_final_report_schema_requires_quantitative_measurements_and_artifact_provenance(tmp_path):
    schema_path = ROOT / "schemas" / "final_report.schema.json"
    payload = json.loads((ROOT / "examples" / "expected_outputs" / "final_report_complete.json").read_text())

    payload["measurements"] = []
    empty_measurements = tmp_path / "empty_measurements.json"
    empty_measurements.write_text(json.dumps(payload))
    with pytest.raises(Exception):
        validate_file(empty_measurements, schema_path)

    payload = json.loads((ROOT / "examples" / "expected_outputs" / "final_report_complete.json").read_text())
    payload["measurements"][0]["artifact_paths"] = []
    no_artifacts = tmp_path / "no_artifacts.json"
    no_artifacts.write_text(json.dumps(payload))
    with pytest.raises(Exception):
        validate_file(no_artifacts, schema_path)
