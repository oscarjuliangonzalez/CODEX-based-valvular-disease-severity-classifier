# CLI Orchestration

Use `scripts/run_ar_orchestration_cli.py` to launch fresh non-interactive Codex sessions for AR case orchestration. The wrapper does not analyze patient data itself; it builds a self-contained per-case prompt and invokes `codex exec --sandbox workspace-write`.

Each case prompt treats the supplied case directory as a complete high-quality exam for the research pipeline. The fresh Codex session must obtain quantitative AR-relevant measurements with units, calibration provenance, frame/source provenance, quality flags, and inspectable artifacts. Failed extraction paths are repair tasks for adapters/tools; a run that reaches reporting without required quantitative measurements must fail as an engineering failure.

## Single Case

```bash
python scripts/run_ar_orchestration_cli.py --mode single --case-dir case_data/<case_id>
```

## Batch Cases

```bash
python scripts/run_ar_orchestration_cli.py --mode batch --cases-root case_data/
```

Batch mode starts one new `codex exec` process per case directory. It stops after the first failed case by default. Continue through later cases with:

```bash
python scripts/run_ar_orchestration_cli.py --mode batch --cases-root case_data/ --continue-on-failure
```

## Dry Run

Use dry run to inspect the generated commands without invoking Codex:

```bash
python scripts/run_ar_orchestration_cli.py --mode single --case-dir case_data/<case_id> --dry-run
```

## No Shared Session Context

Every case prompt tells Codex to rebuild context from repository files: `AGENTS.md`, `$ar-case-orchestration`, `prompts/MAIN_AR_ORCHESTRATOR.md`, `.codex/agents/`, `.agents/skills/`, and `schemas/`. This keeps batch execution independent across patients/cases.

The generated prompt explicitly says not to rely on previous chat context, hidden context, or prior interactive prompts.

## Outputs And Privacy

Outputs are written under `runs/<case_id>/`. Patient inputs under `case_data/` and generated run artifacts remain git-ignored. Do not stage or commit patient data, generated masks, reports, overlays, plots, or PHI.
