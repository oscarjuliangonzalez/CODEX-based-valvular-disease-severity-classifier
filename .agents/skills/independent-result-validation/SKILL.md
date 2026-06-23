---
name: independent-result-validation
description: Use when reviewing artifacts, measurements, units, thresholds, safety language, or final reports independently. Do not inherit creator confidence.
---

# independent-result-validation

## Purpose

Accept, warn, reject, or request repair for measurements/artifacts by checking units, calibration, provenance, schema, and medical-source use. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Accept, warn, reject, or request repair for measurements/artifacts by checking units, calibration, provenance, schema, and medical-source use.

## Required Inputs

Agent result JSON, measurement artifacts, masks/contours/overlays/envelopes, final report draft, schemas, and source maps.

## Calibration And Units

Verify units and calibration provenance for every numeric result; do not create new numeric values during review. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Review result JSON, annotated review notes, accepted/rejected artifact list, and repair task list. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If evidence is unsupported or artifacts fail review, request repair_required for the creator/toolsmith and rerun review after repair.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Final reporting proceeds only after required measurements and artifacts are accepted or have documented warning-level limitations.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
