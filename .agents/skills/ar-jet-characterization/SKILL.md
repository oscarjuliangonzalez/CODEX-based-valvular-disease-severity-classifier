---
name: ar-jet-characterization
description: Use when characterizing AR jet presence, central/eccentric behavior, multiplicity, and reliability. Do not grade severity from jet area alone.
---

# ar-jet-characterization

## Purpose

Produce quantitative and categorical jet morphology features: presence, origin, central/eccentric direction, wall impingement, multiplicity, and downstream metric reliability. This skill supports research and decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

Produce quantitative and categorical jet morphology features: presence, origin, central/eccentric direction, wall impingement, multiplicity, and downstream metric reliability.

## Required Inputs

Color Doppler frames, jet masks/contours, LVOT/aortic valve masks, view classification, phase selections, and color scale provenance.

## Calibration And Units

Use calibrated lengths/areas where reported, plus frame/source provenance and color Doppler scale provenance. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Jet overlays, origin/axis annotations, multiplicity labels, reliability table, and morphology JSON. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## First Failed Attempt

If jet detection or color scale parsing fails, request a jet/color adapter repair and rerun characterization.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Downstream VC, jet-width/LVOT, and PISA agents know which metrics are technically applicable and how to weight limitations.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
