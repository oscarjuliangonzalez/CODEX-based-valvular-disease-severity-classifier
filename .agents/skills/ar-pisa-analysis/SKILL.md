---
name: ar-pisa-analysis
description: Use when analyzing proximal flow convergence, PISA radius/contours, aliasing velocity, Q(t), RVol, and EROA. Do not treat reconstructed contours as measured 3D geometry.
---

# ar-pisa-analysis

## Purpose

Measure PISA radius/contours, aliasing velocity, flow rate, EROA, and PISA-derived regurgitant volume when geometry is supportable. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Measure PISA radius/contours, aliasing velocity, flow rate, EROA, and PISA-derived regurgitant volume when geometry is supportable.

## Required Inputs

Color Doppler PISA frames, color scale/Nyquist provenance, valve/orifice masks, CWD Vmax/VTI, phase timing, and spatial calibration.

## Calibration And Units

Report radius in cm, aliasing velocity in cm/s, flow in ml/s, EROA in cm2, and RVol in ml/beat with formula provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

PISA contour/radius overlays, color-scale crop, Q(t) plot, EROA/RVol calculation table, and geometry-assumption notes. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If aliasing velocity, contour geometry, or CWD linkage fails, request color-scale/contour/spectral adapter repair and rerun.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

PISA-derived quantitative results either validate as measurements or produce a repair_required task tied to the failed component.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
