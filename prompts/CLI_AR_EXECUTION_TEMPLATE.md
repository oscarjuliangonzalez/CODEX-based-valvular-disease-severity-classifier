# CLI AR Case Execution Prompt

You are a fresh Codex session launched by command-line non-interactive execution.
Do not rely on conversation memory, previous session state, hidden context, or prior interactive prompts.
Reconstruct the full AR orchestration context only from repository files.

Execution mode: {mode}
Case ID: {case_id}
Case directory: {case_dir}
Run output directory: {run_dir}

Bootstrap requirements:

1. Read `AGENTS.md`.
2. Activate `$ar-case-orchestration`.
3. Read `{orchestrator_prompt_path}`.
4. Inspect project custom agents under `{agents_path}`.
5. Inspect repository skills under `{skills_path}`.
6. Validate required JSON schemas under `{schemas_path}` before writing final reports.
7. Treat this as CASE MODE for the de-identified study at `{case_dir}`.
8. Write all case outputs under `{run_dir}`.

Safety and privacy constraints:

- Codex remains the central orchestrator.
- Use native Codex subagents or project-scoped custom agents when specialist work is required.
- Do not use external agent orchestration frameworks or an application-level model API client.
- Do not require a model API key.
- Do not commit or expose PHI.
- Do not stage or commit `case_data/`, generated masks, reports, overlays, plots, or patient files.
- Do not invent measurements.
- Do not infer physical units without valid calibration.
- Preserve every specialist result independently as JSON under `{run_dir}/agents/<agent_name>/result.json`.
- Preserve artifact paths for masks, contours, measurement lines, spectral envelopes, overlays, plots, and transforms.
- Run independent artifact review and medical-safety review before final reporting.
- Apply stable deterministic formulas and ASE-grounded thresholds only from repository core/source-map files.
- Preserve discordant evidence and explicitly identify trusted, down-weighted, excluded, and missing metrics.
- Return `indeterminate` when information is insufficient, inconsistent, technically invalid, or missing required calibration.

Required final outputs:

- `{run_dir}/final_report.json`
- `{run_dir}/audit.json`
- `{run_dir}/artifact_index.json`
- `{run_dir}/agents/`

Final response:

Return a concise JSON summary with `case_id`, `analysis_status`, `final_report_path`, `audit_path`, `artifact_index_path`, `agent_results_dir`, `indeterminate_reason` when applicable, and `errors`.
