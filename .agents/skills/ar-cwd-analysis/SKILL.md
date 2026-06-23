---
name: ar-cwd-analysis
description: Use when extracting CWD AR spectral envelopes, Vmax, VTI, and pressure half-time. Do not report values without time and velocity calibration.
---

# ar-cwd-analysis

## Purpose

Extract calibrated AR CWD baseline, envelope, Vmax, VTI, deceleration slope, and pressure half-time. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Extract calibrated AR CWD baseline, envelope, Vmax, VTI, deceleration slope, and pressure half-time.

## Required Inputs

CWD spectral images/video frames, spectral masks, time/velocity axis calibration, baseline location, and phase/cycle metadata.

## Calibration And Units

Report Vmax in m/s or cm/s, VTI in cm, PHT in ms, deceleration slope with units, and cite spectral calibration provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Envelope overlay, baseline/axis overlay, sampled envelope CSV/JSON, VTI/PHT plot, and QC image. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If baseline, spectral axes, or envelope extraction fails, request spectral-layout/envelope adapter repair and rerun CWD analysis.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Accepted calibrated CWD measurements and envelope artifacts are available for evidence integration and PISA linkage.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
