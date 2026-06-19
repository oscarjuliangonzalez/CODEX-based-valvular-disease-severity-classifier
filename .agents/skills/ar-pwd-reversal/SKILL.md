---
name: ar-pwd-reversal
description: Use when analyzing PWD aortic flow reversal. Do not interpret severity when sample site is unknown.
---

# ar-pwd-reversal

## Purpose

Classify reversal timing and measure forward/reverse VTIs with sample-site provenance. This skill supports research and decision-support development only; it must not be used to claim autonomous clinical diagnosis.

## Trigger Conditions

Use this skill when the active Codex task matches the description above or when an AgentTask lists ar-pwd-reversal in required_skills. Do not use it outside AR-focused echocardiography research workflows.

## Inputs

- AgentTask JSON with task_id, case_id, objective, input artifact paths, required schema, write paths, medical constraints, and iteration limits.
- Relevant manifests, masks, contours, overlays, spectral images, calibration metadata, or prior agent JSON results.
- Medical source maps in medical_references/ when threshold or guideline logic is used.

## Required Metadata

Record case ID, source file path, frame index when applicable, original image shape, working image shape, transforms to original coordinates, tool ID, tool version, creation time, and reviewer status.

## Required Calibration

Spatial measurements require pixel spacing or an accepted calibration source. Doppler measurements require time and velocity scales. PISA requires aliasing velocity. Volumetrics require valid diameter, VTI, and reference-flow assumptions. If calibration is absent, return invalid_calibration or insufficient_data.

## Step-By-Step Workflow

1. Read the AgentTask JSON and confirm the objective is in scope.
2. Load only required inputs and source maps.
3. Validate required calibration and metadata before measurement.
4. Select a stable deterministic tool or registered versioned adapter.
5. Generate inspectable artifacts when the task involves images, masks, contours, measurement lines, or spectra.
6. Preserve original coordinates and transformations in JSON.
7. Apply deterministic formulas and ASE-grounded thresholds only from stable core files.
8. Populate schemas/agent_result.schema.json for result.json and validate individual measurements against schemas/measurement_result.schema.json.
9. Add quality flags, assumptions, limitations, abstention reasons, and medical provenance.
10. Save result.json under the assigned agent run folder.
11. Request independent artifact or safety review when clinically relevant artifacts or threshold interpretations are present.

## Deterministic Formulas

Use ar_core/measurements/physics.py for PISA surface area, surface of revolution, VTI, pressure half-time, stroke volume, regurgitant volume, and regurgitant fraction. Use ar_core/evidence/ase_ar_thresholds.yaml and ar_core/evidence/interpretation.py for threshold categories.

## Permitted Inference

Permitted inference is limited to explicit, auditable reasoning from case metadata, calibrated measurements, generated artifacts, validated masks, and cited medical source maps. Heuristic or model-based outputs must include confidence, limitations, and validation scope.

## Prohibited Inference

Do not invent measurements, assume physical units, infer view labels at inadequate confidence, treat reconstructed geometry as measured 3D anatomy, treat synthetic validation as clinical validation, or tune tools toward a desired severity result.

## Output JSON Schema

Return valid JSON matching schemas/agent_result.schema.json for result.json; measurement objects must also match schemas/measurement_result.schema.json. Prose-only output is invalid.

## Artifact Requirements

Every mask, contour, spectral envelope, measurement line, overlay, plot, frame selection, and transform needed for review must be saved as a file and referenced by path in JSON. Preserve observed and reconstructed artifacts separately.

## Quality-Control Checks

Check calibration, coordinate transforms, unit consistency, frame timing, mask completeness, connected components, envelope completeness, reviewer status, threshold applicability, and discordance with other metrics.

## Abstention Conditions

Abstain or return insufficient data for unknown view, missing pixel spacing, missing Doppler scale, missing Nyquist velocity, incomplete CWD envelope, unknown PWD sample site, unresolved multiple jets, rejected masks, invalid volumetric assumptions, major unresolved discordance, tool-generation failure, or no reliable independent evidence.

## Medical References

Primary AR thresholds and integrative logic are mapped in medical_references/ase_ar_source_map.yaml to 2017VavularRegurgitationGuideline.pdf, especially Table 11 and Figure 25. Use EasyPISA and EchoPedia maps only when repository sources are present and indexed.

## Example Input Manifest

```json
{
  "task_id": "mock_ar-pwd-reversal",
  "case_id": "mock_case_indeterminate",
  "agent_name": "ar-pwd-reversal",
  "objective": "Run build-phase synthetic workflow",
  "input_artifacts": ["examples/mock_case/case_manifest.json"],
  "required_skills": ["ar-pwd-reversal"],
  "required_output_schema": "schemas/agent_result.schema.json",
  "allowed_write_paths": ["runs/mock_case_indeterminate/agents/ar-pwd-reversal/"],
  "medical_constraints": ["research_use_only", "do_not_force_severity"],
  "timeout_or_iteration_limit": 1
}
```

## Example Output JSON

```json
{
  "task_id": "mock_ar-pwd-reversal",
  "case_id": "mock_case_indeterminate",
  "agent_name": "ar-pwd-reversal",
  "status": "insufficient_data",
  "tool_ids": ["deterministic_mock_tools:1.0.0"],
  "skills_used": ["ar-pwd-reversal"],
  "input_artifacts": ["examples/mock_case/case_manifest.json"],
  "output_artifacts": [],
  "measurements": [],
  "evidence": {},
  "confidence": 0.0,
  "quality_flags": ["synthetic_build_phase"],
  "assumptions": [],
  "limitations": ["No real de-identified study supplied."],
  "errors": [],
  "medical_sources": ["ase_2017_native_valvular_regurgitation"],
  "provenance": {"source_map": "medical_references/source_index.json"},
  "review_required": true
}
```

## Deterministic Mock Tool

Use scripts/run_deterministic_tools.py and scripts/smoke_test.py for CPU-compatible mock execution. These tools generate JSON and deterministic numerical outputs without patient data, GPU access, external model services, LangGraph, LangChain, or an OpenAI API key.

## Synthetic Validation Test

Run pytest tests/unit/test_physics.py tests/integration/test_contracts_and_smoke.py -q and python scripts/smoke_test.py. The synthetic run must produce an indeterminate report when calibration or validated evidence is missing.

## Dynamic Tool-Evolution Instructions

If a registered tool fails for vendor, format, geometry, color map, scale extraction, segmentation, contour, or spectral-envelope reasons, return a structured failure and request adaptive-toolsmith. New tools must live under generated_tools/<tool_name>/<version>/, include a manifest, tests, limitations, and registry entry, and must never overwrite a validated version.

## Failure-Repair Workflow

1. Preserve the failing input path and error in JSON without PHI.
2. Identify missing calibration, unsupported format, rejected artifact, or invalid assumption.
3. Request artifact review or toolsmith repair when appropriate.
4. Limit repair loops.
5. After the iteration limit, return insufficient_data or indeterminate rather than force a result.
