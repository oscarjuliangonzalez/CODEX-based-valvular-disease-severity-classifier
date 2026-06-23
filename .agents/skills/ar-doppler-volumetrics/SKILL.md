---
name: ar-doppler-volumetrics
description: Use when calculating LVOT/reference stroke volumes, regurgitant volume, and regurgitant fraction. Do not report valid values when reference-flow assumptions fail.
---

# ar-doppler-volumetrics

## Purpose

Calculate LVOT stroke volume, reference stroke volume, regurgitant volume, and regurgitant fraction from calibrated diameters and VTIs. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Calculate LVOT stroke volume, reference stroke volume, regurgitant volume, and regurgitant fraction from calibrated diameters and VTIs.

## Required Inputs

LVOT diameter, LVOT VTI, reference-flow diameter/VTI or volumetric stroke volume, rhythm/cycle metadata, and calibration provenance.

## Calibration And Units

Report diameters and VTIs in cm, stroke volumes and RVol in ml/beat, RF in percent, and formula provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Diameter-line overlays, VTI envelope overlays, calculation table, uncertainty propagation table, and assumption audit. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If diameter, VTI, or reference-flow extraction fails, request measurement/spectral/volumetric adapter repair and rerun.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

RVol and RF are computed from accepted calibrated inputs or a repair_required task identifies the invalid upstream assumption.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
