---
name: cardiac-phase-detection
description: Use when identifying ED, ES, systole, diastole, and AR-usable frames. Do not rely on unsmoothed single-frame derivatives.
---

# cardiac-phase-detection

## Purpose

Produce ED, ES, systolic, diastolic, and AR-usable frame selections with cycle timing and validation evidence. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Produce ED, ES, systolic, diastolic, and AR-usable frame selections with cycle timing and validation evidence.

## Required Inputs

ECG traces when available, frame timestamps, LV masks/area curves, CWD/PWD spectra, and case manifest timing metadata.

## Calibration And Units

Use seconds or milliseconds for time and cite the timestamp/ECG/calibrated frame-rate source. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Phase timeline JSON, selected-frame list, ECG/area curve plots, smoothing parameters, and QC overlays. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If ECG or frame timing extraction fails, request a timing/metadata adapter repair and rerun phase detection.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Measurement agents receive auditable frame/time windows for diastolic AR jets, CWD envelopes, and ED/ES LV measurements.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
