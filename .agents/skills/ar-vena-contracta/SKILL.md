---
name: ar-vena-contracta
description: Use when measuring vena contracta width. Do not label circular area inferred from VCW as EROA.
---

# ar-vena-contracta

## Purpose

Measure vena contracta width in cm across AR diastolic color frames and summarize the accepted representative value. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Measure vena contracta width in cm across AR diastolic color frames and summarize the accepted representative value.

## Required Inputs

Zoomed color Doppler frames, jet neck masks/contours, aortic valve/LVOT anatomy, phase selections, and spatial calibration.

## Calibration And Units

Report VCW in cm with pixel spacing provenance and frame/source provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

VCW measurement-line overlays, per-frame table, contour/neck crop, uncertainty notes, and QC plot. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If the jet neck or measurement line cannot be extracted, request jet-neck segmentation or line-placement adapter repair and rerun.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

A calibrated VCW measurement with ASE Table 11 interpretation, quality flags, and inspectable overlay is present.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
