# Main AR Codex Orchestrator

Use this prompt from the repository root while signed into Codex/ChatGPT. Codex is the central orchestrator. Do not use LangGraph, LangChain, OpenAI Agents SDK, an application-level OpenAI API client, OPENAI_API_KEY, or external orchestration services.

## Modes

- BUILD MODE: validate scaffolding, schemas, skills, deterministic tools, synthetic fixtures, docs, and Git state.
- CASE MODE: run a de-identified case under case_data/<case_id>/.
- VALIDATION MODE: inspect independent results, artifacts, masks, measurements, source provenance, and final report schemas.
- TOOL-REPAIR MODE: create versioned adapters only after structured tool failures and tests.

## Phase 0: Preflight

1. Read AGENTS.md.
2. Inventory .agents/skills/ and .codex/agents/.
3. Verify environment.yml, JSON schemas, Git branch/status, and ignored patient-data paths.
4. Create a unique case ID and runs/<case_id>/.

## Phase 1: Case Inventory

Spawn case_ingestion and guideline_curator when source maps are absent or stale. Validate case_manifest.json.

## Phase 2: Harmonization And Classification

Spawn image_harmonization and view_classifier. Spawn toolsmith for unsupported vendor/layout adapters. Do not run view-specific measurements while view remains unresolved.

## Phase 3: Timing And Anatomy

Spawn cardiac_phase and mask_generation for LV, LVOT, valve, root, and aorta. Spawn artifact_reviewer and iterate until accepted, accepted with warning, or abandoned with abstention.

## Phase 4: Color Doppler Analysis

When color Doppler is available, spawn jet masks and jet_characterization. After review, conditionally spawn jet_width_lvot, vena_contracta, and pisa_analysis.

## Phase 5: Spectral Analysis

Spawn cwd_analysis, pwd_analysis, and doppler_volumetrics only when inputs and calibration permit.

## Phase 6: LV Remodeling

Spawn lv_remodeling only with valid B-mode views, masks, frames, and calibration.

## Phase 7: Tool Repair

For unsupported format/vendor/layout, failed scale extraction, segmentation, contour, or spectral extraction, decide whether to spawn toolsmith. Limit loops and return insufficient data after the limit.

## Phase 8: Independent Validation

Spawn artifact and medical-safety reviewers. The creator agent cannot be the sole validator.

## Phase 9: Evidence Integration

Spawn evidence_integrator with accepted independent results. Preserve discordance and return indeterminate when evidence is inadequate.

## Phase 10: Final Report

Spawn report_generator. Validate against schemas/final_report.schema.json. Write runs/<case_id>/final_report.json, runs/<case_id>/audit.json, and runs/<case_id>/artifact_index.json.
