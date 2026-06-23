---
name: ar-mask-generation
description: Use when generating AR-relevant masks, contours, overlays, and mask metadata. Do not merely describe anatomy without artifacts.
---

# ar-mask-generation

## Purpose

Produce masks and contours for LV, LVOT, aortic valve/root, aorta, color AR jets, PISA regions, and spectral envelopes as assigned. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Produce masks and contours for LV, LVOT, aortic valve/root, aorta, color AR jets, PISA regions, and spectral envelopes as assigned.

## Required Inputs

Harmonized frames/spectra, view labels, phase selections, calibration metadata, and requested anatomy/jet/spectral target.

## Calibration And Units

Masks remain in pixels but must include original image shape, working shape, transforms, and spatial/spectral calibration references. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Mask files, contour files, overlays, uncertainty maps when available, connected-component summaries, and transform JSON. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If segmentation, contour extraction, or envelope mask creation fails, request a segmentation/contour adapter repair and rerun mask generation.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Artifacts are inspectable, accepted or repair-requested by review, and sufficient for calibrated measurement-line or envelope extraction.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
