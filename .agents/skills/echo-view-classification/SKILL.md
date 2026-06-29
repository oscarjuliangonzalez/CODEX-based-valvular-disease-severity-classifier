---
name: echo-view-classification
description: Use when a Codex orchestrator or specialist agent must classify echo view, modality, and zoom status from rendered media, DICOM metadata, and local guideline summaries. The skill is for agent reasoning; deterministic code must not select labels.
---

# echo-view-classification

## Purpose

Produce agent-authored view, modality, and zoom classification records from local evidence. This skill supports research decision-support development only; it must not claim autonomous diagnosis or clinical validation.

## Measurable Job

For each usable image or series, inspect the evidence packet and rendered media, write structured visual observations, rank view/modality/zoom candidates with evidence, and select one terminal view, one terminal modality/type, and one terminal zoom status.

## Required Inputs

Use all available local evidence:

- `case_manifest.json`
- `dicom_metadata.json`
- `evidence_packets.json`
- rendered representative frames, contact sheets, and cine previews
- safe DICOM metadata and ultrasound region calibration tags
- `docs/guideline_summaries/view_classification_guidelines.md`
- `docs/guideline_summaries/view_modality_zoom_definitions.md`
- `docs/guideline_summaries/guideline_figure_index.md`
- extracted guideline page/figure artifacts referenced by the summaries
- masks or harmonized geometry only when already available

## Calibration And Units

Do not report physical measurements. Preserve frame/source provenance and calibration references used by downstream measurement agents. If calibration evidence is missing for a measurement-oriented downstream task, request repair of metadata or calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Write machine-readable JSON containing evidence packets, agent observations, ranked candidates, selected conclusions, limitations, repair history, and measurement suitability. Reference every inspected media artifact and guideline summary by path.

## Agent Reasoning Rules

- Inspect the rendered frame/contact sheet/cine before selecting labels.
- Read the local guideline summaries and rendered guideline figures/pages before deciding.
- Decide which evidence matters for the specific source object; do not apply a fixed rule or a fixed weight.
- Preserve uncertainty by ranking plausible candidates, but still choose a terminal label when the image is usable.
- Use DICOM metadata as evidence, not as an automatic answer.
- Use spectral, color, and M-mode layout evidence for modality/type, not for view unless it also helps identify anatomy or acquisition window.
- Do not use acquisition order.
- Do not use fixed scoring tables, programmed weights, deterministic feature-to-view mappings, or a fallback view.
- Do not invent anatomy, units, or measurement suitability that is not supported by the rendered media, metadata, or guideline summaries.

## View Cues To Search For

These are cues to inspect and reason about; they are not a scoring table.

### PLAX

Search for parasternal long-axis anatomy: long-axis LV cavity, interventricular septum and posterior wall, mitral valve, left atrium, aortic valve/root, LVOT, and a sector oriented from the parasternal window. PLAX may support aortic root/LVOT context, AR color jet origin, and vena contracta review when calibrated.

### PSAX

Search for short-axis circular or near-circular cross sections. Identify level when possible: aortic valve level, mitral valve level, papillary muscle level, or LV apex. PSAX often shows a valve or ventricular cross-section rather than a chamber long axis.

### A4C

Search for apical four-chamber anatomy: LV, RV, LA, RA, mitral valve, tricuspid valve, septum, and apex-to-base chamber orientation. A4C can support chamber context, color Doppler review, and some Doppler alignment evidence depending on acquisition.

### A2C

Search for apical two-chamber anatomy: LV and LA with mitral valve, usually without right-sided chambers. Use this when the image is apical but right atrium/RV are not visible and LV-LA long-axis anatomy dominates.

### A3C / Apical Long-Axis

Search for apical long-axis anatomy: LV, LA, mitral valve, LVOT, aortic valve/root, and apical alignment through the outflow tract. This view can support AR CWD/color context when the aortic valve/LVOT are visible.

### Suprasternal

Search for suprasternal notch anatomy: aortic arch, great vessel branches, and descending thoracic aorta continuity. PWD/CWD from this window may support descending aortic flow reversal evidence when sample site is known.

### Subcostal

Search for subcostal window cues: liver-proximal acoustic window, horizontal or inferior chamber orientation, IVC, abdominal aorta, or alternative four-chamber context. PWD from this window may support abdominal aortic flow reversal evidence when sample site is known.

## Modality/Layout Cues To Search For

- `2D`: grayscale anatomy without persistent red/blue flow overlay and without spectral or M-mode time layout.
- `color Doppler`: red/blue or variance flow overlay within a 2D sector, with underlying anatomy visible.
- `CWD`: spectral Doppler velocity-time display from continuous-wave acquisition; use DICOM spectral calibration and visible spectral panel evidence.
- `PWD`: spectral Doppler velocity-time display from pulsed-wave acquisition; sample site evidence is required before downstream severity interpretation.
- `M-mode`: motion over time with depth axis, often a linear time-depth stripe layout; DICOM regions may encode seconds by distance.
- `spectral Doppler`: use when the layout is spectral but CWD/PWD cannot be resolved from evidence; request repair if downstream CWD/PWD separation is needed.

## Zoom Status Cues To Search For

Terminal zoom status must be either `zoomed_in` or `not_zoomed`.

Use `zoomed_in` when the rendered evidence shows a cropped field of view, enlarged valve/root/jet region, absent surrounding chambers, focused Doppler/valve target, or safe metadata/overlay evidence suggesting zoom.

Use `not_zoomed` when surrounding anatomy and broader sector context remain visible and the acquisition is not focused on a small valve/root/jet region.

If zoom status cannot be defended, request repair of rendering, metadata parsing, or guideline evidence and rerun. Do not leave zoom uncertainty as the terminal result.

## Required Output Fields

Every classified source object must include:

- `case_id`
- `source_file`
- `source_type`
- `series_uid`
- `sop_instance_uid`
- `frame_count`
- `derived_media_paths`
- `selected_view`
- `selected_modality`
- `zoom_status`
- `zoom_confidence`
- `ranked_view_candidates`
- `ranked_modality_candidates`
- `ranked_zoom_candidates`
- `confidence`
- `guideline_evidence`
- `metadata_evidence`
- `visual_observations`
- `visual_evidence_artifact_paths`
- `agent_reasoning_summary`
- `measurement_suitability`
- `limitations`
- `repair_history`

## First Failed Attempt

If rendered media, metadata, guideline summaries, or figure artifacts do not support a reasoned terminal record, request repair of the evidence path and rerun classification. Do not create a code rule to bypass missing agent reasoning.

## Repair-Loop Behavior

Treat unreadable frames, unsupported vendor layout, missing guideline figure extraction, missing DICOM calibration, failed spectral-region parsing, or unresolved zoom status as an engineering/tooling issue. Record a structured repair event with source path, frame/series identifier, failed evidence type, tool version when available, and the concrete repair needed. After repair, rerun the affected source object and preserve the original failure plus repaired result in the audit.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked evidence artifact or downstream measurement.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked classification or measurement and update the audit.

## Success Criteria

Required AR measurement agents receive selected view, selected modality, zoom status, ranked candidates, visual observations, guideline provenance, media artifact paths, and documented uncertainty sufficient to decide whether calibrated downstream measurements can proceed.

## Medical Source Rules

Use local guideline summaries, rendered guideline page artifacts, `guidelines/2017VavularRegurgitationGuideline.pdf`, and `medical_references/ase_ar_source_map.yaml` for source provenance and AR limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
