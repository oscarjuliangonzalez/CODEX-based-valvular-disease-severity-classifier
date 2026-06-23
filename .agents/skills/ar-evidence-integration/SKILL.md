---
name: ar-evidence-integration
description: Use when integrating accepted independent AR evidence. Do not use a simple unweighted average or let one weak metric control severity.
---

# ar-evidence-integration

## Purpose

Integrate accepted quantitative AR measurements into severity support while preserving discordance, quality, and repair requests. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Integrate accepted quantitative AR measurements into severity support while preserving discordance, quality, and repair requests.

## Required Inputs

Accepted measurement_result objects, artifact review results, safety review results, ASE source maps, and required metric list.

## Calibration And Units

Validate every measurement unit, calibration source, formula, selected frame/source, and artifact path before integration. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Evidence result JSON, metric contribution table, discordance table, repair request list, and guideline provenance record. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If a required measurement is absent, invalid, uncalibrated, or lacks artifacts, emit repair_required with a concrete upstream task and block final report generation.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Evidence result status is complete only when required quantitative measurements pass unit, provenance, and artifact checks.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
