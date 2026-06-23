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
7. Treat `{case_dir}` as a complete high-quality exam for research pipeline execution.
8. Write all case outputs under `{run_dir}`.

Complete-exam measurement contract:

- The provided exam is complete, high-quality, and diagnosable for this research workflow.
- Do not use not-enough-information language as a terminal fallback for this exam.
- A failed measurement is a tooling defect until proven otherwise.
- If calibration, metadata, view classification, segmentation, color scale parsing, Doppler scale parsing, spectral envelope extraction, or contour generation fails, create a specific repair task, improve or replace the relevant adapter/tool, and rerun the measurement.
- Continue inspect, measure, repair, validate, and rerun loops until quantitative AR-relevant measurements are produced or the run exits as an engineering failure with actionable logs.
- Do not invent measurements or infer units without calibration provenance.
- Preserve uncertainty, discordance, and quality flags without converting them into a global stop condition.

Constraints:

- Codex remains the central orchestrator.
- Use native Codex subagents or project-scoped custom agents when specialist work is required.
- Do not use external agent orchestration frameworks or an application-level model API client.
- Do not require or use `OPENAI_API_KEY` for orchestration.
- Do not commit, expose, copy, or write PHI outside the configured run directory.
- Do not stage or commit `case_data/`, `patient_data/`, `runs/`, generated masks, reports, overlays, plots, caches, model weights, or patient files.
- Preserve every specialist result independently as JSON under `{run_dir}/agents/<agent_name>/result.json`.
- Preserve artifact paths for masks, contours, measurement lines, spectral envelopes, overlays, plots, calibration evidence, and transforms.
- Run independent artifact review and medical-safety review before final reporting.
- Apply stable deterministic formulas and ASE-grounded thresholds only from repository core/source-map files.
- Preserve discordant evidence and explicitly identify trusted, down-weighted, excluded, and repaired metrics.
- A case run must fail loudly if it reaches report generation without required quantitative measurements, calibration provenance, frame/source provenance, units, quality flags, and inspectable artifacts.

Required final outputs:

- `{run_dir}/final_report.json`
- `{run_dir}/audit.json`
- `{run_dir}/artifact_index.json`
- `{run_dir}/agents/`

Final response:

Return a concise JSON summary with `case_id`, `analysis_status`, `final_report_path`, `audit_path`, `artifact_index_path`, `agent_results_dir`, `repair_requests`, and `errors`.
