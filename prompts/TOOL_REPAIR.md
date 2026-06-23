# Tool Repair

Use TOOL-REPAIR MODE after a structured measurement extraction failure. Reproduce the failure without PHI, create a new version under `generated_tools/<tool_name>/<version>/`, add a manifest, tests, synthetic fixture, limitations, and registry entry, and request independent artifact review. Do not overwrite prior versions or alter stable medical thresholds or equations.

A repaired tool must state the measurement or artifact it unlocks, the input modality/view/vendor/layout it supports, required calibration, generated artifacts, and validation evidence. Rerun the blocked specialist measurement after repair and record both the original failure and repaired result in the case audit.
