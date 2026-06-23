---
name: ar-pwd-reversal
description: Use when analyzing PWD aortic flow reversal. Do not interpret severity when sample site is unknown.
---

# ar-pwd-reversal

## Purpose

Measure aortic flow reversal timing, duration, velocity envelope, and sample-site provenance for descending or abdominal aorta PWD. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Measure aortic flow reversal timing, duration, velocity envelope, and sample-site provenance for descending or abdominal aorta PWD.

## Required Inputs

PWD spectral images/video, sample-site metadata/labels, spectral calibration, baseline, and phase/cycle timing.

## Calibration And Units

Report reversal duration in ms or percent diastole, velocities in cm/s or m/s, VTI in cm, and cite sample-site/calibration provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

PWD envelope overlay, baseline/axis overlay, sample-site evidence crop, reversal timing plot, and QC table. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If sample site, axes, or reversal envelope cannot be parsed, request metadata/spectral adapter repair and rerun PWD analysis.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

A calibrated reversal result with site-specific ASE interpretation and inspectable envelope artifact is present.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
