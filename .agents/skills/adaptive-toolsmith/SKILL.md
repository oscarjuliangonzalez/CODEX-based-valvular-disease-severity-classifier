---
name: adaptive-toolsmith
description: Use when a structured failure requires a versioned vendor/layout/segmentation/contour/spectral adapter. Do not alter ASE thresholds or existing validated tool versions.
---

# adaptive-toolsmith

## Purpose

Create or refine a versioned adapter/tool that unlocks a blocked quantitative measurement or inspectable artifact. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Create or refine a versioned adapter/tool that unlocks a blocked quantitative measurement or inspectable artifact.

## Required Inputs

Structured repair_required task, non-PHI failure reproducer, source file shape/metadata summaries, expected schema, and blocked measurement objective.

## Calibration And Units

Tool output must preserve or extract the calibration required by the blocked measurement and document unit assumptions. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

generated_tools/<tool>/<version>/ code, manifest, tests, synthetic fixture, validation artifact, registry update, and repair audit JSON. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If the repaired tool fails validation, version a new repair attempt or return engineering_failure with actionable logs; never overwrite a validated version.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

The blocked specialist measurement reruns successfully or the run records a precise engineering failure with reproduction steps.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
