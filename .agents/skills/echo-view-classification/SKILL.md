---
name: echo-view-classification
description: Use when classifying echo modality or view from metadata, geometry, masks, or image reasoning. Do not force a label when confidence is low.
---

# echo-view-classification

## Purpose

Produce ranked modality/view candidates for each medical image or series with confidence, evidence, and measurement suitability.

## Measurable Job

Produce ranked modality/view candidates for each medical image or series with confidence, evidence, and measurement suitability.

## Required Inputs

Case manifest, metadata, representative frames, harmonized geometry, masks when available, and ViewSummary records when present.

## Calibration And Units

No physical measurement is reported by this skill, but it must preserve frame/source provenance and calibration references used by downstream measurements. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

View classification JSON, representative frame contact sheet, evidence table, and rejected-candidate notes. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## Evidence Requirements

For every usable image or series, write one machine-readable record with source file provenance, frame count, series/SOP UIDs when present, derived media paths, selected view, selected modality, ranked candidates, confidence, metadata evidence, visual evidence paths, limitations, repair history, and measurement suitability. Use DICOM ultrasound region tags, frame geometry, color/spectral layout, on-image evidence artifacts, and any safe structured-report view hints when available. Spectral Doppler classification must preserve time/velocity calibration provenance from DICOM region tags when present, including baseline/reference pixels and physical deltas.

## First Failed Attempt

If confidence is low, add metadata/frame-evidence features or a view-classification adapter repair, then rerun classification instead of stopping the case.

## Repair-Loop Behavior

Do not leave `unknown` or unable-to-classify as a terminal result for complete high-quality exam validation. Low confidence, missing pixel decode support, absent media artifacts, unsupported vendor layout, missing DICOM calibration, or failed spectral-region parsing is a tooling defect: record a structured repair_required event, improve the parser/decoder/layout/classifier adapter, rerun the affected source objects, and preserve both the original failure and repaired result in the audit. Do not force a label when the evidence is weak; improve the evidence path until ranked candidates and a selected view are defensible, or record engineering_failure with a concrete next repair task.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Required AR measurement agents receive view/modality candidates sufficient to attempt calibrated measurements with documented uncertainty.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
