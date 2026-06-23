# Main AR Codex Orchestrator

Use this prompt from the repository root while signed into Codex/ChatGPT or from a fresh `codex exec` session. Codex is the central orchestrator. Do not use LangGraph, LangChain, OpenAI Agents SDK, an application-level OpenAI API client, `OPENAI_API_KEY`, or external orchestration services.

## Modes

- BUILD MODE: validate scaffolding, schemas, skills, deterministic tools, synthetic fixtures, docs, and Git state.
- CASE MODE: run a de-identified complete high-quality exam under the provided case directory.
- VALIDATION MODE: inspect independent results, artifacts, masks, measurements, source provenance, and final report schemas.
- TOOL-REPAIR MODE: create versioned adapters after structured measurement extraction failures and tests.

## Core Rule

For the provided complete exam set, lack of a quantitative AR measurement is an engineering/tooling failure, not a patient-data limitation. Do not end a case with a global not-enough-information fallback. Keep privacy, provenance, calibration, and no-invented-measurement rules intact while repairing extraction until measurable outputs exist.

## Phase 0: Preflight

1. Read `AGENTS.md`.
2. Inventory `.agents/skills/` and `.codex/agents/`.
3. Verify `environment.yml`, JSON schemas, Git branch/status, ignored patient-data paths, and the local ASE PDF/source maps.
4. Create a unique case ID and `runs/<case_id>/`.
5. Record the complete-exam assumption and all repair-loop limits in `runs/<case_id>/audit.json`.

## Phase 1: Case Inventory

Spawn `case_ingestion` and `guideline_curator` when source maps are absent or stale. Inventory DICOM/video/report files, extract de-identified metadata, calibration candidates, modality/view hints, and frame/source provenance. If vendor parsing or calibration extraction fails, spawn `toolsmith` with a repair task and rerun ingestion.

## Phase 2: Harmonization And Classification

Spawn `image_harmonization` and `view_classifier`. Produce ranked view/modality candidates with evidence. If classification confidence is low, improve metadata/frame-evidence parsing or view-classification tooling rather than stopping measurement work.

## Phase 3: Timing And Anatomy

Spawn `cardiac_phase` and `mask_generation` for LV, LVOT, valve, root, aorta, color jets, and spectral regions. Spawn `artifact_reviewer` and iterate until artifacts are accepted or a specific repair task is opened and completed.

## Phase 4: Color Doppler Analysis

When color Doppler is available, spawn jet masks and `jet_characterization`. After review, spawn `jet_width_lvot`, `vena_contracta`, and `pisa_analysis` for calibrated quantitative measurements. If color scale parsing, jet segmentation, PISA contouring, or measurement-line placement fails, spawn `toolsmith`, validate artifacts, and rerun.

## Phase 5: Spectral Analysis

Spawn `cwd_analysis`, `pwd_analysis`, and `doppler_volumetrics`. Extract calibrated CWD envelopes, Vmax, VTI, PHT, PWD reversal timing/site, LVOT/reference stroke volumes, regurgitant volume, regurgitant fraction, and supporting plots. Repair spectral axes, envelope extraction, and sample-site parsing failures before integration.

## Phase 6: LV Remodeling

Spawn `lv_remodeling` with calibrated B-mode views, masks, ED/ES frames, and frame provenance. Produce LV EDV, ESV, EF, stroke volume, and remodeling artifacts. If single-plane assumptions are the only available route, record the assumption and continue repair work for missing biplane evidence before final integration.

## Phase 7: Tool Repair

For unsupported format/vendor/layout, failed scale extraction, segmentation, contour, registration, or spectral extraction, spawn `toolsmith`. New tools must be versioned under `generated_tools/<tool_name>/<version>/`, tested, registered, and audited without overwriting validated versions.

## Phase 8: Independent Validation

Spawn artifact and medical-safety reviewers. The creator agent cannot be the sole validator. Reviewers accept, warn, reject, or request repair with concrete measurement/artifact tasks; they do not convert complete-exam measurement failures into a global fallback.

## Phase 9: Evidence Integration

Spawn `evidence_integrator` with accepted independent quantitative results. Validate units, calibration provenance, frame/source provenance, artifact paths, quality flags, and ASE guideline provenance. Preserve discordance. If required measurements are absent or invalid, request upstream repair and block final report generation.

## Phase 10: Final Report

Spawn `report_generator` only after required quantitative measurements are present or the run has failed as an engineering failure. Validate against `schemas/final_report.schema.json`. Write `runs/<case_id>/final_report.json`, `runs/<case_id>/audit.json`, and `runs/<case_id>/artifact_index.json`.
