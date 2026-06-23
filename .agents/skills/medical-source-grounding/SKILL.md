---
name: medical-source-grounding
description: Use when indexing ASE, EasyPISA, EchoPedia, or supplied medical references for AR logic. Do not use to invent medical rules.
---

# medical-source-grounding

## Purpose

Produce or verify source-map artifacts for thresholds, formulas, limitations, and integrative AR interpretation rules. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Produce or verify source-map artifacts for thresholds, formulas, limitations, and integrative AR interpretation rules.

## Required Inputs

Local ASE PDF, repository source maps, threshold YAML, deterministic interpretation helpers, and any supplied local references.

## Calibration And Units

Verify units exactly as stated by the source, including cm, cm2, ml/beat, percent, ms, cm/s, and m/s. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Source-map YAML/JSON updates, citation/provenance table, threshold verification notes, and unsupported-source audit. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If a source cannot be read or a threshold is unsupported, request repair_required for source indexing and block threshold changes.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

All threshold and limitation logic used by measurement/integration code maps to local source provenance without invented rules.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
