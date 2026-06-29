# View Classifier Versioning

## Previous Implementation

- Module: `ar_core/view_validation.py`
- CLI: `scripts/run_view_classifier_validation.py`
- Generated tool record: `generated_tools/view_classifier_validation_adapter/1.0.0/manifest.json`
- Behavior: local DICOM inventory, media rendering, deterministic modality classification from DICOM ultrasound regions, hard-coded view aliases, acquisition-order context, fixed view-feature scoring, and PWD/CWD spectral trace extraction in one module.
- Status: replaced. The file now exists only as a compatibility shim that redirects active work to the agentic workflow and neutral utility modules.

## Replacement Implementation

- Active orchestration module: `ar_core/agentic_view_classifier.py`
- Neutral DICOM/media utilities: `ar_core/dicom_media.py`
- Preserved PWD/CWD spectral utility: `ar_core/spectral.py`
- Guideline summary generation: `ar_core/guideline_summary.py`
- CLI: `scripts/run_agentic_view_classifier_validation.py`
- Generated tool record: `generated_tools/agentic_view_classifier_validation_adapter/1.0.0/manifest.json`
- Output mode: `agentic_view_classifier_validation`
- Default output root: `runs/agentic_view_classifier_validation/`

## Architectural Change

The active Python path no longer selects echo view, modality, or zoom status. It does not use acquisition order, a fixed deterministic view scoring table, programmed cue weights, hard-coded feature-to-view mappings, or a terminal fallback label.

The Python path builds evidence packets from safe DICOM metadata, locally rendered frames/contact sheets/cine previews, local guideline summaries, and guideline page artifacts. It writes task prompts for a Codex `view_classifier` specialist and validates agent-authored JSON records. The Codex orchestrator or specialist agent is the classification authority.

## Spectral Preservation

PWD/CWD velocity-time extraction was moved out of the old view classifier into `ar_core/spectral.py`. The preserved behavior still writes calibrated JSON, CSV, and overlay artifacts with DICOM ultrasound-region calibration provenance. Spectral utilities do not classify echo view.

## Safety And Privacy

Run outputs, rendered media, spectral overlays, extracted metadata, PHI, and generated case artifacts remain under ignored run/artifact paths and must not be committed. Guideline summaries under `docs/guideline_summaries/` contain no patient data and are intended for agent use.
