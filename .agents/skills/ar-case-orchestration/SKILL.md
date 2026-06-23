---
name: ar-case-orchestration
description: Use when running build, case, validation, or tool-repair workflows for AR assessment with Codex as the orchestrator. Do not use for non-AR clinical tasks.
---

# ar-case-orchestration

## Purpose

Coordinate specialist agents until complete-exam quantitative AR measurements, review artifacts, evidence integration, final report, audit, and artifact index are produced. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Coordinate specialist agents until complete-exam quantitative AR measurements, review artifacts, evidence integration, final report, audit, and artifact index are produced.

## Required Inputs

Case directory, AGENTS.md, prompts, custom agents, repository skills, schemas, generated tool registry, source maps, and specialist results.

## Calibration And Units

Enforce unit/calibration provenance for every measurement before evidence integration and final reporting. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Per-agent result JSON, final_report.json, audit.json, artifact_index.json, measurement artifacts, repair logs, and tool manifests. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If any specialist cannot measure, route the defect to toolsmith or the responsible extraction skill, validate the repair, and rerun before final reporting.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

The case completes with schema-valid quantitative outputs or exits as engineering_failure with actionable repair logs and no clinical fallback.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
