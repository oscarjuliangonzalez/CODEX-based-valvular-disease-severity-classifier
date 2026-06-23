---
name: ar-jet-width-lvot
description: Use when measuring color AR jet width and LVOT width. Do not apply central-jet thresholds to eccentric or multiple jets without down-weighting.
---

# ar-jet-width-lvot

## Purpose

Measure AR jet width, LVOT width at the same level, and jet-width/LVOT ratio across selected diastolic color frames. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Measure AR jet width, LVOT width at the same level, and jet-width/LVOT ratio across selected diastolic color frames.

## Required Inputs

Color Doppler frames, LVOT masks/lines, jet masks, phase selections, jet characterization, and spatial calibration.

## Calibration And Units

Report jet width and LVOT width in cm and ratio as unitless; cite pixel spacing and measurement-line provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Measurement-line overlays, per-frame values, selected-frame list, ratio plot/table, and QC image. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If LVOT line placement, jet mask, or spatial calibration fails, request mask/calibration/line-placement repair and rerun.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

At least one accepted calibrated ratio measurement is saved with ASE interpretation and applicability limitations.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
