You are Codex working in this repository:

/Users/general/Library/CloudStorage/Box-Box/aether.lab/people/Oscar/Methods/codex-based-valvular-severity-classifier/CODEX-based-valvular-disease-severity-classifier

Goal: modify the existing Codex-native AR/aortic regurgitation orchestration implementation so that the agent skills, prompts, tools, and CLI execution path are explicit, measurable, and non-abstaining for the provided high-quality exams. The current implementation contains conservative failsafe/indeterminate behavior. That must be removed or narrowed so it cannot be used as a fallback when the exams contain complete diagnosable information.

This is a research software pipeline, not a clinical diagnostic device. Keep privacy, auditability, provenance, and no-invented-measurement rules. But do not allow the agent to stop with “not enough information” for the provided exam set. The exams are complete, high-quality, and diagnosable. The job is to FIND OUT the quantitative measurements by improving tools, adapters, parsing, calibration, segmentation, spectral extraction, or measurement logic until measurable results are obtained.

Handoff / Current Implementation Context

The repository already contains a Codex-native multi-agent scaffold for AR severity assessment. It was built on branch:

feat/codex-ar-agentic-system

Important existing files and directories:

- `2017VavularRegurgitationGuideline.pdf`
  - Local ASE 2017 valvular regurgitation guideline PDF.
  - Read it directly and use it as the primary medical source.
- `AGENTS.md`
  - Repo-level Codex operating instructions.
  - Currently includes conservative indeterminate/insufficient evidence behavior that must be revised for this complete-exam execution model.
- `.codex/agents/`
  - Project-scoped custom agent definitions.
- `.agents/skills/`
  - Repository skills for orchestration, ingestion, image harmonization, view classification, phase detection, masks, AR jet metrics, vena contracta, PISA, CWD, PWD, Doppler volumetrics, LV remodeling, evidence integration, adaptive toolsmithing, and independent validation.
- `prompts/`
  - Existing orchestration prompts.
  - Relevant files include `MAIN_AR_ORCHESTRATOR.md`, `RUN_AR_CASE.md`, `VALIDATE_AR_CASE.md`, `TOOL_REPAIR.md`, and `CLI_AR_EXECUTION_TEMPLATE.md`.
- `ar_core/`
  - Deterministic core for measurement physics, evidence integration, thresholds, and stable calculations.
- `schemas/`
  - JSON contracts for case manifests, agent tasks/results, measurement artifacts, evidence results, final reports, tool manifests, and tool evolution.
- `generated_tools/`
  - Registry and generated/evolvable tools.
- `medical_references/`
  - Existing source maps derived from the ASE guideline.
- `docs/HANDOFF_AUDIT.md`
  - Existing audit from the initial build. It records that no original `handoff/` directory was present.
- `docs/CLI_ORCHESTRATION.md`
  - Existing CLI orchestration documentation.
- `scripts/run_ar_orchestration_cli.py`
  - Existing CLI wrapper for fresh non-interactive Codex sessions.
- `scripts/smoke_test.py`
- `scripts/validate_json_outputs.py`
- `tests/`
  - Unit and integration tests.

Before editing, run:

```bash
git status --short --branch
```

Preserve any existing user changes. Do not overwrite uncommitted work. Do not stage or commit patient data, PHI, exam files, generated masks, overlays, reports, plots, caches, or model weights.

Required Source Review

1. Read `AGENTS.md`.
2. Read `docs/HANDOFF_AUDIT.md`.
3. Read `docs/CLI_ORCHESTRATION.md`.
4. Read all relevant files under `prompts/`.
5. Inspect every skill under `.agents/skills/`.
6. Inspect every custom agent under `.codex/agents/`.
7. Read `2017VavularRegurgitationGuideline.pdf`.
8. Inspect the existing deterministic core under `ar_core/`.
9. Inspect the schemas under `schemas/`.
10. Inspect `scripts/run_ar_orchestration_cli.py`.
11. Locate and inspect the real exam input folder, expected to be `/Users/general/Library/CloudStorage/Box-Box/Purdue-HackensackUMH/4-Data`. You are only allowed to read from this source. You must save information to the current operating directory. Exams are inside each folder, are a summary information generator is provide.

Main Requirement

Modify the implementation so the job of every relevant agent and skill is clearly stated as:

- obtain quantitative AR-relevant measurements from the provided exam data;
- create or refine tools when existing tools cannot extract a measurement;
- never use “insufficient information,” “missing information,” “indeterminate,” or similar abstention as an easy fallback for the provided complete exam set;
- treat failure to measure as a tooling defect to fix, not as a patient-data limitation;
- preserve audit trails showing what was tried, what tool was improved, and what measurement was finally produced;
- produce quantitative outputs with units, calibration provenance, image/frame provenance, quality flags, and inspectable artifacts.

The model must not fabricate measurements. But it also must not stop before extracting measurements. If a direct path fails, it must iterate:

1. inspect the source exam data;
2. identify modality/view/frame/calibration;
3. run existing deterministic or generated tools;
4. if a tool fails, improve or replace the adapter/tool;
5. validate the measurement artifact visually or structurally;
6. rerun the measurement;
7. repeat until the needed quantitative reading is obtained.

Delete Or Replace Failsafe Behavior

Find and remove or rewrite failsafe implementations that allow the pipeline to end with “not enough information” for complete exams.

This likely includes changes in:

- `AGENTS.md`
- `.agents/skills/*/SKILL.md`
- `.codex/agents/*.toml`
- `prompts/*.md`
- `ar_core/evidence/integrator.py`
- `ar_core/evidence/interpretation.py`
- `ar_core/evidence/ase_ar_thresholds.yaml` if needed only for wording/metadata, not threshold manipulation
- `schemas/final_report.schema.json`
- `schemas/evidence_result.schema.json`
- `scripts/run_ar_orchestration_cli.py`
- `prompts/CLI_AR_EXECUTION_TEMPLATE.md`
- tests that currently expect an indeterminate result

Do not weaken medical safety by inventing values. Instead, replace abstention with mandatory tool-improvement loops, explicit measurement attempts, and hard failure only when the software implementation itself cannot complete. If the pipeline cannot obtain a measurement, the run should fail as an engineering failure with actionable logs, not classify the case as non-diagnostic.

Expected Behavioral Change

Old behavior to remove:

- “Return indeterminate when information is insufficient.”
- “If calibration is missing, stop.”
- “If artifact extraction fails, report missing data.”
- “If evidence is incomplete, final report may be indeterminate.”

New behavior to implement:

- For the provided complete exams, all core AR measurements must be attempted until quantitative values are obtained.
- If calibration is not immediately available, build/refine calibration extraction.
- If DICOM/vendor metadata parsing fails, build/refine the parser.
- If view classification fails, improve classification or use metadata/frame evidence.
- If segmentation fails, build/refine masks/contours or adapter calls.
- If spectral envelope extraction fails, improve the envelope extraction tool.
- If color Doppler scale parsing fails, build/refine color scale extraction.
- If PISA/VC/LVOT/jet-width/CWD/PWD/Doppler volumetrics cannot be measured initially, create a specific tool-improvement task and rerun.
- A final report must contain quantitative measurement results and artifacts for each diagnosable case.

The final report may include uncertainty, quality flags, discordance, or limitations of a specific measurement. It may not use global insufficient-information fallback for these complete cases.

CLI Requirement

Ensure command-line orchestration works in two modes only:

- single case
- batch cases

Every case run must happen in a fresh Codex session, with no reliance on prior chat context. The CLI prompt generated per case must be self-contained and must force the new Codex session to rebuild context from repo files.

Expected commands should remain similar to:

```bash
python scripts/run_ar_orchestration_cli.py --mode single --case-dir exams/<case_id>
python scripts/run_ar_orchestration_cli.py --mode batch --cases-root exams/
```

The CLI must:

- launch one fresh `codex exec --sandbox workspace-write` process per case;
- pass a self-contained prompt generated from repository instructions;
- write outputs under `runs/<case_id>/`;
- preserve per-agent JSON results;
- preserve measurement artifacts, overlays, contours, masks, plots, and audit files;
- avoid committing patient/exam/run data;
- support dry-run/testing without invoking Codex;
- fail loudly if a case completes without required quantitative measurements.

Skill And Agent Rewrite Requirements

For every relevant skill in `.agents/skills/`, make the job explicit. Each skill should answer:

- What quantitative measurement or artifact must this skill produce?
- Which input files/views/modalities does it require?
- What units and calibration provenance are required?
- What artifacts must be saved?
- What to do if the first tool attempt fails?
- What adapter/tool-improvement loop must be triggered?
- What JSON schema must the result satisfy?
- What constitutes success?

Do not leave vague instructions such as “assess,” “review,” or “determine” without measurable outputs.

For every relevant `.codex/agents/*.toml`, ensure the agent’s role is concrete and non-abstaining for complete exams. The agent must be instructed to improve tools or request toolsmith work rather than stop.

Evidence Integration Requirement

The evidence integrator must not average weak evidence or invent values. But it must expect that quantitative evidence can be obtained for the complete exam set.

Modify integration behavior so that missing measurements are treated as upstream extraction failures requiring repair, not as acceptable terminal clinical indeterminacy.

The integrator should:

- validate units and provenance;
- compare measurements against ASE guideline thresholds;
- preserve discordance;
- report measurement confidence/quality;
- request repair of missing/failed measurements before final report generation;
- only allow final output once required quantitative measurements are present or the run has failed as an engineering failure.

Medical Reference Requirement

Read `2017VavularRegurgitationGuideline.pdf` directly. Update or verify `medical_references/` mappings as needed.

Do not invent thresholds. Use the PDF for AR severity-relevant thresholds, measurement cautions, and integrative interpretation.

Tests And Verification

Use test-driven changes. Add or update tests before or alongside implementation.

Required tests should cover:

- CLI single mode generates a self-contained no-context Codex prompt.
- CLI batch mode launches one fresh session per case.
- The generated prompt forbids insufficient-information fallback for complete exams.
- Skills contain explicit measurable job definitions.
- Final report schema requires quantitative measurements and artifact provenance.
- Evidence integration rejects missing required measurements as an engineering/tooling failure, not as indeterminate.
- Any previous mock/fixture expecting `indeterminate` is rewritten to expect measurable outputs or a hard tool failure.
- No patient/exam/run data is staged by git.
- Existing deterministic physics tests still pass.

Run verification:

```bash
pytest -q
python scripts/smoke_test.py
```

If the Conda environment is needed, use the existing environment instructions in `environment.yml`, `requirements.txt`, and `docs/ENVIRONMENT.md`.

Git / GitHub Version Control

Use Git carefully.

1. Start by checking branch and status.
2. If on `main`, create a feature branch.
3. Suggested branch name:

```bash
feat/force-measurable-exam-orchestration
```

4. Preserve existing user changes.
5. Make focused commits with clear messages.
6. Do not commit PHI, real exams, `runs/`, generated patient artifacts, caches, credentials, `.env`, model weights, or ignored files.
7. Run `git diff --check`.
8. Run tests before committing.
9. Push the feature branch to GitHub.
10. If GitHub CLI is available and authenticated, open a PR. If not, provide the PR creation URL.

Suggested commit structure:

- `docs: clarify measurable exam orchestration handoff`
- `feat: remove insufficient-data fallback from AR skills`
- `feat: require quantitative measurement repair loops`
- `test: cover non-abstaining CLI and evidence contracts`

Completion Criteria

The work is complete only when:

- The PDF has been read and used as the medical source.
- Skills clearly state measurable jobs.
- Agent definitions no longer permit easy insufficient-information fallback for complete exams.
- CLI prompts explicitly assume fresh sessions with no context.
- Single and batch CLI execution modes are preserved.
- The system attempts tool repair/refinement rather than stopping.
- Required quantitative measurements are enforced by schemas/tests/contracts.
- Tests pass.
- Git branch is committed and pushed.
- Final response includes:
  - branch name;
  - commit hashes;
  - files changed;
  - tests run and results;
  - whether PR was created or PR URL;
  - any remaining engineering limitations.

Important Principle

For these exams, “not enough information” is not an acceptable final answer. The data are complete and diagnosable. If the pipeline cannot measure, the pipeline is incomplete. Build or refine the tools until quantitative measurements are obtained.