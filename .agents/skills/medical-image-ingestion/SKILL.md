---
name: medical-image-ingestion
description: Use when inventorying de-identified echo case files and extracting calibration. Do not use for severity grading.
---

# medical-image-ingestion

## Purpose

Produce a case manifest with source file inventory, DICOM/video metadata, calibration candidates, view/modality hints, frame counts, and de-identification status. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Produce a case manifest with source file inventory, DICOM/video metadata, calibration candidates, view/modality hints, frame counts, and de-identification status.

## Required Inputs

Case directory, DICOM/video/report files, ViewSummary outputs when present, and any supplied case manifest.

## Calibration And Units

Record pixel spacing in cm/px or mm/px, Doppler velocity scale in cm/s or m/s, time scale in s/px or ms/px, Nyquist velocity in cm/s, and the metadata/source field used for each value. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

case_manifest.json, file inventory JSON, metadata extraction log, calibration provenance table, and redaction/audit notes. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If vendor metadata, file layout, compression, or calibration extraction fails, open a repair_required task for a parser/calibration adapter and rerun ingestion.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

A schema-valid manifest lists every usable exam file and calibration provenance required by downstream measurement agents.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
