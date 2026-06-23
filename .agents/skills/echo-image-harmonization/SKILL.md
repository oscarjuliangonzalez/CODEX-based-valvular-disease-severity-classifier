---
name: echo-image-harmonization
description: Use when normalizing echo image geometry, overlays, color bars, or spectral axes. Do not use to make cross-image measurements without calibration.
---

# echo-image-harmonization

## Purpose

Produce harmonized frames/spectra with transforms that preserve original coordinates, overlays, color bars, and calibration evidence. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Produce harmonized frames/spectra with transforms that preserve original coordinates, overlays, color bars, and calibration evidence.

## Required Inputs

Raw images/video/DICOM frames, metadata, calibration candidates, color bars, spectral axes, and prior ingestion results.

## Calibration And Units

Carry spatial cm/px, spectral time and velocity scales, color Doppler velocity scale, and transform matrices from original to working coordinates. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Harmonized image/spectral files, transform JSON, calibration overlay, color/spectral scale crops, and QC plots. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If layout, overlay removal, color scale parsing, or spectral axis parsing fails, request a versioned adapter repair and rerun harmonization.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Downstream agents can map every measurement point and artifact back to original source pixels and calibrated units.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
