# CODEX-based Valvular Disease Severity Classifier

This repository contains a native Codex multi-agent scaffold for research-oriented assessment of aortic regurgitation from echocardiography studies.

It is not an autonomous diagnostic device and is not clinically validated. The build phase supplies deterministic physics, ASE-grounded JSON contracts, project-scoped Codex agents, repository skills, synthetic fixtures, and a CPU-compatible mock workflow.

## Quick Start

    conda env create -f environment.yml
    conda activate ar-codex-agents
    pytest
    python scripts/smoke_test.py

For future cases, place de-identified data under case_data/<case_id>/, invoke $ar-case-orchestration, and inspect outputs under runs/<case_id>/.

## CLI Orchestration

Run one fresh Codex session per case from the command line:

    python scripts/run_ar_orchestration_cli.py --mode single --case-dir case_data/<case_id>
    python scripts/run_ar_orchestration_cli.py --mode batch --cases-root case_data/

Use `--dry-run` to inspect generated `codex exec --sandbox workspace-write` commands without invoking Codex.
