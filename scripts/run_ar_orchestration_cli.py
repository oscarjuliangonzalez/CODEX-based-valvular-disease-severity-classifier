"""Command-line wrapper for fresh-session Codex AR orchestration runs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_json_outputs import validate_file

TEMPLATE_PATH = ROOT / "prompts" / "CLI_AR_EXECUTION_TEMPLATE.md"


@dataclass(frozen=True)
class CliConfig:
    mode: str
    repo_root: Path = ROOT
    case_dir: Path | None = None
    cases_root: Path | None = None
    dry_run: bool = False
    continue_on_failure: bool = False
    codex_bin: str = "codex"
    sandbox: str = "workspace-write"


@dataclass(frozen=True)
class CaseRunResult:
    case_id: str
    case_dir: str
    run_dir: str
    command: list[str]
    prompt: str
    returncode: int
    dry_run: bool
    error_message: str | None = None


Runner = Callable[..., subprocess.CompletedProcess]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _require_repo_file(repo_root: Path, path: str) -> None:
    if not (repo_root / path).exists():
        raise FileNotFoundError(f"required repository file or directory is missing: {path}")


def validate_repo_bootstrap(repo_root: Path) -> None:
    for required in [
        "AGENTS.md",
        "prompts/MAIN_AR_ORCHESTRATOR.md",
        "prompts/CLI_AR_EXECUTION_TEMPLATE.md",
        ".codex/agents",
        ".agents/skills",
        "schemas",
    ]:
        _require_repo_file(repo_root, required)


def discover_batch_cases(cases_root: Path) -> list[Path]:
    if not cases_root.exists() or not cases_root.is_dir():
        raise FileNotFoundError(f"cases root does not exist or is not a directory: {cases_root}")
    cases = [
        path
        for path in sorted(cases_root.iterdir(), key=lambda item: item.name)
        if path.is_dir() and not path.name.startswith(".")
    ]
    if not cases:
        raise FileNotFoundError(f"no case directories found under: {cases_root}")
    return cases


def render_case_prompt(repo_root: Path, case_dir: Path, mode: str) -> str:
    repo_root = repo_root.resolve()
    case_dir = case_dir.resolve()
    if not case_dir.exists() or not case_dir.is_dir():
        raise FileNotFoundError(f"case directory does not exist or is not a directory: {case_dir}")
    validate_repo_bootstrap(repo_root)

    case_id = case_dir.name
    run_dir = repo_root / "runs" / case_id
    template = (repo_root / "prompts" / "CLI_AR_EXECUTION_TEMPLATE.md").read_text()
    values = {
        "mode": mode,
        "case_id": case_id,
        "case_dir": _relative(case_dir, repo_root),
        "run_dir": _relative(run_dir, repo_root),
        "agents_path": ".codex/agents",
        "skills_path": ".agents/skills",
        "schemas_path": "schemas",
        "orchestrator_prompt_path": "prompts/MAIN_AR_ORCHESTRATOR.md",
    }
    bootstrap = (
        "fresh Codex session bootstrap:\n"
        "Do not rely on conversation memory or prior session context.\n"
        "Read AGENTS.md, activate $ar-case-orchestration, read {orchestrator_prompt_path}, "
        "inspect {agents_path}, inspect {skills_path}, validate {schemas_path}, "
        "run case {case_id} from {case_dir}, and write outputs to {run_dir}.\n\n"
    ).format(**values)
    return bootstrap + template.format(
        **values,
    )


def build_codex_command(prompt: str, *, codex_bin: str = "codex", sandbox: str = "workspace-write") -> list[str]:
    return [codex_bin, "exec", "--sandbox", sandbox, prompt]


def _artifact_path(repo_root: Path, artifact_path: str) -> Path:
    path = Path(artifact_path)
    return path if path.is_absolute() else repo_root / path


def validate_completed_case_outputs(repo_root: Path, case_id: str) -> None:
    run_dir = repo_root / "runs" / case_id
    final_report = run_dir / "final_report.json"
    audit = run_dir / "audit.json"
    artifact_index = run_dir / "artifact_index.json"
    agents_dir = run_dir / "agents"
    for path in [final_report, audit, artifact_index, agents_dir]:
        if not path.exists():
            raise FileNotFoundError(f"case run did not produce required output: {_relative(path, repo_root)}")

    report = validate_file(final_report, repo_root / "schemas" / "final_report.schema.json")
    measurements = report.get("measurements") or []
    if not measurements:
        raise ValueError(f"case {case_id} completed without quantitative measurements")
    for measurement in measurements:
        for artifact in measurement.get("artifact_paths", []):
            if not _artifact_path(repo_root, artifact).exists():
                raise FileNotFoundError(f"measurement artifact is missing: {artifact}")


def _case_dirs_for_config(config: CliConfig) -> Iterable[Path]:
    if config.mode == "single":
        if config.case_dir is None:
            raise ValueError("--case-dir is required for single mode")
        return [config.case_dir]
    if config.mode == "batch":
        if config.cases_root is None:
            raise ValueError("--cases-root is required for batch mode")
        return discover_batch_cases(config.cases_root)
    raise ValueError(f"unsupported mode: {config.mode}")


def run_cases(config: CliConfig, runner: Runner = subprocess.run) -> list[CaseRunResult]:
    repo_root = config.repo_root.resolve()
    results: list[CaseRunResult] = []
    for case_dir in _case_dirs_for_config(config):
        prompt = render_case_prompt(repo_root=repo_root, case_dir=case_dir, mode=config.mode)
        command = build_codex_command(prompt, codex_bin=config.codex_bin, sandbox=config.sandbox)
        if config.dry_run:
            returncode = 0
            error_message = None
        else:
            completed = runner(command, cwd=repo_root, text=True)
            returncode = completed.returncode
            error_message = None
            if returncode == 0:
                try:
                    validate_completed_case_outputs(repo_root, case_dir.name)
                except Exception as exc:
                    returncode = 1
                    error_message = str(exc)
        result = CaseRunResult(
            case_id=case_dir.name,
            case_dir=_relative(case_dir, repo_root),
            run_dir=_relative(repo_root / "runs" / case_dir.name, repo_root),
            command=command,
            prompt=prompt,
            returncode=returncode,
            dry_run=config.dry_run,
            error_message=error_message,
        )
        results.append(result)
        if returncode != 0 and not config.continue_on_failure:
            break
    return results


def _parse_args(argv: list[str]) -> CliConfig:
    parser = argparse.ArgumentParser(description="Run Codex AR orchestration in fresh CLI sessions.")
    parser.add_argument("--mode", choices=["single", "batch"], required=True)
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--cases-root", type=Path)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true", help="Print planned Codex commands without invoking Codex.")
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="In batch mode, continue with later cases after a failed Codex run.",
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--sandbox", default="workspace-write")
    args = parser.parse_args(argv)
    return CliConfig(
        mode=args.mode,
        repo_root=args.repo_root,
        case_dir=args.case_dir,
        cases_root=args.cases_root,
        dry_run=args.dry_run,
        continue_on_failure=args.continue_on_failure,
        codex_bin=args.codex_bin,
        sandbox=args.sandbox,
    )


def main(argv: list[str] | None = None) -> int:
    config = _parse_args(sys.argv[1:] if argv is None else argv)
    results = run_cases(config)
    payload = {
        "mode": config.mode,
        "dry_run": config.dry_run,
        "continue_on_failure": config.continue_on_failure,
        "results": [
            {
                "case_id": item.case_id,
                "case_dir": item.case_dir,
                "run_dir": item.run_dir,
                "returncode": item.returncode,
                "command": item.command,
                "error_message": item.error_message,
            }
            for item in results
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if all(item.returncode == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
