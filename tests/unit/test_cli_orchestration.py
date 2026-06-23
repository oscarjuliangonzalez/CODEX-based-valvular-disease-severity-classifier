import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_ar_orchestration_cli import (
    CliConfig,
    build_codex_command,
    discover_batch_cases,
    render_case_prompt,
    run_cases,
)


ROOT = Path(__file__).resolve().parents[2]


def write_required_repo_files(root: Path) -> None:
    (root / "AGENTS.md").write_text("# AGENTS\n")
    (root / "prompts").mkdir()
    (root / "prompts" / "MAIN_AR_ORCHESTRATOR.md").write_text("# Orchestrator\n")
    (root / "prompts" / "CLI_AR_EXECUTION_TEMPLATE.md").write_text(
        "Case {case_id} at {case_dir}\n"
        "Run {run_dir}\n"
        "Mode {mode}\n"
        "Read {agents_path} {skills_path} {schemas_path}\n"
        "Use {orchestrator_prompt_path}\n"
    )
    (root / ".codex" / "agents").mkdir(parents=True)
    (root / ".agents" / "skills" / "ar-case-orchestration").mkdir(parents=True)
    (root / "schemas").mkdir()


def test_render_case_prompt_bootstraps_without_conversation_context(tmp_path):
    write_required_repo_files(tmp_path)
    case_dir = tmp_path / "case_data" / "case_001"
    case_dir.mkdir(parents=True)

    prompt = render_case_prompt(
        repo_root=tmp_path,
        case_dir=case_dir,
        mode="single",
    )

    assert "Case case_001" in prompt
    assert "case_data/case_001" in prompt
    assert "runs/case_001" in prompt
    assert "AGENTS.md" in prompt
    assert "$ar-case-orchestration" in prompt
    assert "fresh Codex session" in prompt
    assert "Do not rely on conversation memory" in prompt


def test_build_codex_command_uses_workspace_write_and_prompt_argument(tmp_path):
    command = build_codex_command("case prompt")

    assert command == ["codex", "exec", "--sandbox", "workspace-write", "case prompt"]


def test_single_mode_dry_run_builds_one_fresh_codex_command(tmp_path):
    write_required_repo_files(tmp_path)
    case_dir = tmp_path / "case_data" / "case_001"
    case_dir.mkdir(parents=True)

    results = run_cases(
        CliConfig(mode="single", case_dir=case_dir, repo_root=tmp_path, dry_run=True)
    )

    assert len(results) == 1
    assert results[0].case_id == "case_001"
    assert results[0].returncode == 0
    assert results[0].command[:4] == ["codex", "exec", "--sandbox", "workspace-write"]
    assert "case_data/case_001" in results[0].prompt


def test_batch_mode_discovers_cases_and_runs_one_command_per_case(tmp_path):
    write_required_repo_files(tmp_path)
    cases_root = tmp_path / "case_data"
    (cases_root / "case_a").mkdir(parents=True)
    (cases_root / "case_b").mkdir()
    (cases_root / ".hidden").mkdir()

    cases = discover_batch_cases(cases_root)
    results = run_cases(
        CliConfig(mode="batch", cases_root=cases_root, repo_root=tmp_path, dry_run=True)
    )

    assert [path.name for path in cases] == ["case_a", "case_b"]
    assert [result.case_id for result in results] == ["case_a", "case_b"]
    assert results[0].prompt != results[1].prompt
    assert all(result.command[0:2] == ["codex", "exec"] for result in results)


def test_missing_case_directory_fails_before_codex_invocation(tmp_path):
    write_required_repo_files(tmp_path)

    with pytest.raises(FileNotFoundError, match="case directory"):
        run_cases(
            CliConfig(
                mode="single",
                case_dir=tmp_path / "case_data" / "missing",
                repo_root=tmp_path,
                dry_run=True,
            )
        )


def test_batch_stop_on_failure_controls_later_cases(tmp_path):
    write_required_repo_files(tmp_path)
    cases_root = tmp_path / "case_data"
    (cases_root / "case_a").mkdir(parents=True)
    (cases_root / "case_b").mkdir()
    calls = []

    def fake_runner(command, cwd, text):
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode=1)

    results = run_cases(
        CliConfig(
            mode="batch",
            cases_root=cases_root,
            repo_root=tmp_path,
            dry_run=False,
            continue_on_failure=False,
        ),
        runner=fake_runner,
    )

    assert len(results) == 1
    assert len(calls) == 1


def test_cli_script_runs_directly_in_dry_run_mode(tmp_path):
    write_required_repo_files(tmp_path)
    case_dir = tmp_path / "case_data" / "case_001"
    case_dir.mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_ar_orchestration_cli.py",
            "--mode",
            "single",
            "--case-dir",
            str(case_dir),
            "--repo-root",
            str(tmp_path),
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "case_001" in result.stdout


def test_cli_source_does_not_use_forbidden_orchestration_frameworks():
    source = Path("scripts/run_ar_orchestration_cli.py").read_text().lower()

    for forbidden in ["langgraph", "langchain", "openai_api_key", "openai agents sdk"]:
        assert forbidden not in source
