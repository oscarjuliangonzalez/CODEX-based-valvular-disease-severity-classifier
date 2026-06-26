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

View-classification outputs must be produced before timing detection and are required inputs for source selection, selected view, selected modality, series/SOP provenance, and derived media paths. Use ECG traces when available, embedded ECG overlays, frame timestamps, LV masks/area curves, CWD/PWD spectra, and case manifest timing metadata.

## Calibration And Units

Use seconds or milliseconds for time and cite the timestamp/ECG/calibrated frame-rate source. Extract DICOM/video frame-time mapping from `FrameTime`, `FrameTimeVector`, cine/display rate, actual frame duration, calibrated spectral time axes, or an explicitly documented single-frame static capture. If calibration is not immediately available, create a repair_required task for calibration extraction and rerun; do not infer physical units.

## Required Artifacts

Phase timeline JSON, selected-frame list, ECG strip crops, extracted ECG waveform JSON/CSV, ECG trace overlays, frame-index/time mapping artifacts, smoothing parameters, and QC overlays. QC overlays must show detected PR intervals, QRS complexes, QT intervals, R-peaks or equivalent cycle anchors, cycle boundaries, and selected phase windows. Every artifact needed for review must be saved under the assigned run directory and referenced by path in JSON.

## Embedded ECG Detection

Detect the ECG trace location before phase classification. The trace is typically green and in the lower overlay band, but it may appear in an upper overlay or central/spectral overlay region. Search lower, upper, and other overlay regions for green-channel dominant trace pixels, extract the waveform, preserve the ECG crop and overlay artifacts, and record the trace location in JSON.

## Required Timing Outputs

For each usable view-classified image, cine, video, or spectral series, store PR intervals, QRS complexes, QT intervals, R-peaks or equivalent cycle anchors, cardiac cycle boundaries, frame-to-time mappings, and per-frame phase labels in both frame units and calibrated time units. Phase labels must include systole, diastole, early_diastole, late_systole, ED_candidate, and ES_candidate where appropriate.

## Downstream Instructions

Write machine-readable frame-selection instructions so downstream AR tools can select early_diastole, late_systole, ED_candidate, and ES_candidate windows without reinterpreting ECG or timing. Include source file, view, modality, series/SOP identifiers, frame ranges, time ranges, confidence, evidence, limitations, and artifact references.

## First Failed Attempt

If ECG extraction, DICOM/video timing metadata extraction, frame mapping, interval detection, or phase classification confidence is low, request a timing/metadata/layout adapter repair and rerun phase detection.

## Repair-Loop Behavior

Do not leave `unknown`, `undetermined`, unable-to-classify, or non-diagnostic timing as a terminal result when source data are usable. Low confidence, missing frame-time calibration, sparse ECG extraction, unsupported ECG layout, failed video decode, parser failure, or classifier failure is a tooling defect: record a structured repair_required event, improve or tune the parser/layout/ECG/timing/classifier adapter, rerun the affected source objects, and preserve both the original failure and repaired result in the audit. If repair attempts are exhausted, record engineering_failure with concrete next repair tasks rather than emitting a clinical fallback.

## Adapter Tool Improvement Loop

1. Preserve the failing source path, frame/series identifier, error, and tool version in JSON without PHI.
2. Identify the exact blocked measurement or artifact.
3. Create or request a versioned adapter under `generated_tools/<tool_name>/<version>/` with tests and a manifest.
4. Validate the repaired artifact visually or structurally.
5. Rerun the blocked measurement and update the audit with the original failure and repaired result.

## Success Criteria

Measurement agents receive auditable per-cycle frame/time windows for diastolic AR jets, late-systolic findings, CWD/PWD envelopes, and ED/ES LV measurements. The outputs include embedded ECG provenance, calibrated DICOM/video timing evidence, PR/QRS/QT interval contracts, R-peak/cycle anchors, per-frame phase labels, and downstream frame-selection instructions.


## Medical Source Rules

Use `2017VavularRegurgitationGuideline.pdf` and `medical_references/ase_ar_source_map.yaml` for AR thresholds and limitations. Do not invent thresholds, change stable equations, or tune tools toward a desired severity label.

## JSON Schema

Return valid JSON matching `schemas/agent_result.schema.json` unless the AgentTask names a stricter schema. Measurement objects must satisfy `schemas/measurement_result.schema.json`. Final reports must satisfy `schemas/final_report.schema.json`.

## Status Contract

Use `success` when the measurable job is complete, `partial` only for accepted warning-level limitations with quantitative output preserved, `repair_required` when a tool or adapter must be improved and rerun, and `engineering_failure` when the implementation cannot complete after documented repair attempts.

## Privacy And Audit

Do not expose PHI, commit patient data, or write outside allowed run/tool paths. Save what was tried, tool versions, repair attempts, measurement provenance, and reviewer status in the case audit.
