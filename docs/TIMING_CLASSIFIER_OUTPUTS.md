# Timing Classifier Outputs

This document defines the output contract for `scripts/run_timing_classifier_validation.py`.
The workflow is local-only, uses view-classification outputs as required input, and writes
all validation artifacts under `runs/timing_classifier_validation/`.

## Workflow Order

1. Inventory each requested case folder from the read-only source root.
2. Verify or regenerate `runs/view_classifier_validation/<case_id>/` before timing.
3. Read each usable view-classified ultrasound image, cine, video, or spectral series.
4. Extract DICOM/video timing metadata and embedded ECG provenance.
5. Detect R-peaks or equivalent cycle anchors, PR intervals, QRS complexes, QT intervals,
   cycle boundaries, and frame-to-time mappings.
6. Label every frame with a downstream phase label and write frame-selection instructions.

## Output Tree

Per case:

- `case_manifest.json`
- `timing_metadata.json`
- `ecg_extraction.json`
- `timing_classification.json`
- `frame_selection_instructions.json`
- `artifact_index.json`
- `audit.json`

Global:

- `summary.json`
- `timing_table.json`
- `repair_log.json`

Artifact paths are absolute local paths or paths under the timing run directory. Source
DICOM paths may be absolute local paths for provenance. Do not commit `runs/` artifacts.

## Required Source Record Fields

Each timed source object in `timing_classification.json.records` contains:

- `case_id`: validation case ID such as `A1`.
- `source_file`: original local source path.
- `source_type`: view-classifier source type, usually `ultrasound_image` or
  `ultrasound_multiframe_image`.
- `selected_view`: view selected by the view-classification workflow.
- `selected_modality`: modality selected by the view-classification workflow.
- `series_uid`, `sop_instance_uid`: DICOM identifiers when present.
- `frame_count`: number of frames in the source object.
- `frame_time_ms`: calibrated frame interval in milliseconds, or `0.0` for a single
  static frame capture.
- `calibrated_time_mapping`: list of `{frame_index, time_ms, time_seconds}`.
- `derived_media_paths`: local representative frame or cine artifacts used by timing.
- `ecg_trace_location`: detected ECG overlay bounding box and region name.
- `ecg_trace_artifact_paths`: ECG crop and overlay QC artifacts.
- `phase_qc_artifact_paths`: timeline overlays showing cycle boundaries, PR/QRS/QT
  intervals, and selected analysis windows.
- `ecg_signal_path_json`, `ecg_signal_path_csv`: extracted ECG waveform samples.
- `pr_intervals`, `qrs_complexes`, `qt_intervals`: interval lists in frame and ms units.
- `r_peaks`: cycle anchors in frame and ms units.
- `visible_ecg_r_peaks`: R-peak candidates found in the visual ECG strip.
- `cardiac_cycles`: per-cycle frame boundaries.
- `frame_phase_labels`: one record per frame.
- `selected_analysis_windows`: preferred frame windows for downstream tools.
- `confidence`: combined view, ECG, and timing confidence from `0.0` to `1.0`.
- `evidence`: ECG and view evidence strings.
- `metadata_evidence`: DICOM/video timing evidence strings.
- `visual_evidence_artifact_paths`: inspectable artifacts supporting the classification.
- `limitations`: accepted limitations; not terminal unknowns.
- `repair_history`: adapter or heuristic repairs applied before final classification.
- `quality_flags`: non-terminal extraction flags that downstream tools should preserve.
- `downstream_instructions`: source-local consumer instructions.

## Phase Labels

Allowed `frame_phase_labels[].phase_label` values:

- `systole`
- `diastole`
- `early_diastole`
- `late_systole`
- `ED_candidate`
- `ES_candidate`

`parent_phase` is either `systole` or `diastole` when an analysis-window label is more
specific. Downstream tools should prefer `selected_analysis_windows` when selecting frames,
then fall back to `frame_phase_labels` only if they need every-frame labels.

## Confidence Semantics

`confidence` is a workflow confidence score, not clinical validation.

- `>= 0.85`: strong ECG trace and calibrated DICOM/video timing evidence.
- `0.70-0.84`: usable ECG/timing evidence with minor extraction or layout flags.
- `0.50-0.69`: repaired or sparse ECG evidence; still classified and auditable.
- `< 0.50`: should not be emitted as a terminal result for usable source data; create a
  repair event and rerun.

The workflow must not emit terminal `unknown`, `undetermined`, or `non-diagnostic`
timing for usable validation sources. Low confidence becomes `repair_history`,
`quality_flags`, and `repair_log.json` entries.

## ECG Provenance Fields

`ecg_trace_location` contains:

- `region_name`: `lower_overlay`, `upper_overlay`, `central_overlay`, or `full_frame`.
- `x_min`, `y_min`, `x_max`, `y_max`: ECG crop bounds in source artifact pixels.
- `image_width`, `image_height`: dimensions of the inspected frame.
- `green_pixel_count`: count of green-channel dominant trace pixels in the selected band.
- `component_center_x`, `component_center_y`: selected ECG component center.

`ecg_signal_path_json` stores:

- `source_file`
- `artifact_stem`
- `created_at`
- `ecg_trace_location`
- `samples`: `sample_index`, `x_px`, `y_px`, `signal_normalized`
- `sample_count`
- `quality_flags`
- `signal_axis`

`ecg_signal_path_csv` contains the same sample table for quick plotting.

## PR, QRS, QT, R-Peak, And Cycle Representation

Each interval record contains:

- `cycle_index`
- `kind`: `PR_interval`, `QRS_complex`, or `QT_interval`
- `start_ms`, `end_ms`, `duration_ms`
- `frame_start`, `frame_end`
- `unit`: always `ms`

Each `r_peaks` record contains:

- `cycle_index`
- `frame_index`
- `time_ms`
- `unit`
- `source`: DICOM heart-rate, visible ECG spacing, or a named repair source.

Each `cardiac_cycles` record contains:

- `cycle_index`
- `start_frame`, `end_frame`
- `start_ms`, `end_ms`, `duration_ms`
- `anchor`: `R_peak_or_equivalent_cycle_start`

Intervals are stored both in physical time and frame units so downstream tools can avoid
recomputing ECG timing.

## Per-Case Files

`case_manifest.json` records source case path, view run path, view summary, timed source
count, privacy status, and the embedded input view manifest.

`timing_metadata.json` stores safe timing metadata records, including frame timing,
frame-to-time mapping, heart rate, ECG/cardiac tags, ultrasound regions, and private
vendor hints without private values.

`ecg_extraction.json` stores ECG provenance summaries for every timed source, including
artifact paths, intervals, R-peaks, confidence, and quality flags.

`timing_classification.json` is the primary per-frame timing output. It contains all
timing records, allowed labels, and summary counts.

`frame_selection_instructions.json` is the downstream contract. Consumers must use its
`records[].preferred_windows` and `do_not_reinterpret_ecg: true` fields rather than
rerunning ECG extraction.

`artifact_index.json` lists ECG crops, overlays, signal JSON/CSV files, representative
frames, and other visual evidence.

`audit.json` records local-only execution, skills used, view dependency handling, repair
events, privacy notes, and source/output roots.

## Global Files

`summary.json` stores run-level counts, per-case counts, output roots, view dependency
status, interval totals, cycle totals, and early/late analysis-window totals.

`timing_table.json` is a compact table for downstream inspection. It includes source,
view, modality, frame count, frame timing, cycle and interval counts, analysis windows,
confidence, and phase-label status.

`repair_log.json` aggregates non-terminal repair events across all cases. Repair events
must identify the case, source file, and concrete parser, layout, ECG, timing, or
classification issue that was repaired or still needs work.

## Downstream Consumption

Downstream AR tools should:

1. Load `frame_selection_instructions.json`.
2. Match records by `source_file`, `series_uid`, or `sop_instance_uid`.
3. Select frames from `preferred_windows` for `early_diastole`, `late_systole`,
   `ED_candidate`, or `ES_candidate`.
4. Use `timing_classification.json.frame_phase_labels` only when every-frame labels are
   needed.
5. Preserve `confidence`, `limitations`, and `quality_flags` in later measurement JSON.
6. Never reinterpret ECG or frame timing when `do_not_reinterpret_ecg` is `true`.
