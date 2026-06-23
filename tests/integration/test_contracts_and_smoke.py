import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_json_outputs import validate_file


ROOT = Path(__file__).resolve().parents[2]


def test_example_final_report_validates_against_schema():
    schema_path = ROOT / "schemas" / "final_report.schema.json"
    example_path = ROOT / "examples" / "expected_outputs" / "final_report_complete.json"

    validate_file(example_path, schema_path)


def test_final_report_schema_enforces_research_disclaimer_and_severity_label(tmp_path):
    schema_path = ROOT / "schemas" / "final_report.schema.json"
    example_path = ROOT / "examples" / "expected_outputs" / "final_report_complete.json"
    payload = json.loads(example_path.read_text())

    unsafe = dict(payload)
    unsafe["research_use_only"] = False
    unsafe_path = tmp_path / "unsafe_report.json"
    unsafe_path.write_text(json.dumps(unsafe))
    with pytest.raises(Exception):
        validate_file(unsafe_path, schema_path)

    missing_label = json.loads(example_path.read_text())
    del missing_label["severity"]["label"]
    missing_label_path = tmp_path / "missing_label_report.json"
    missing_label_path.write_text(json.dumps(missing_label))
    with pytest.raises(Exception):
        validate_file(missing_label_path, schema_path)


def test_smoke_test_creates_complete_quantitative_mock_run():
    result = subprocess.run(
        [sys.executable, "scripts/smoke_test.py", "--case-id", "pytest_mock_case"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "success"
    report_path = ROOT / payload["final_report_path"]
    assert report_path.exists()

    report = json.loads(report_path.read_text())
    assert report["analysis_status"] == "complete"
    assert report["severity"]["label"] == "severe"
    assert report["research_use_only"] is True
    assert report["missing_information"] == []
    assert report["measurements"]
    assert all(item["artifact_paths"] for item in report["measurements"])


def test_no_external_orchestration_frameworks_are_declared():
    forbidden = {"langgraph", "langchain", "openai-agents", "openai_agents"}
    dependency_files = [ROOT / "environment.yml", ROOT / "requirements.txt"]
    declared = "\n".join(path.read_text().lower() for path in dependency_files if path.exists())

    assert forbidden.isdisjoint(set(declared.replace("-", "_").split()))
    for name in forbidden:
        assert name not in declared
