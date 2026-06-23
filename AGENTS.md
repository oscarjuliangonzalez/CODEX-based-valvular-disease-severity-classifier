# AGENTS.md

## Project Scope

This repository implements a research-oriented Codex multi-agent scaffold for aortic regurgitation assessment from echocardiography studies. It is decision-support development infrastructure, not an autonomous diagnostic device.

## Required Operating Mode

- Codex is the central orchestrator.
- Use native Codex subagents or project-scoped custom agents under .codex/agents/ when case or validation workflows need delegation.
- Use repository skills under .agents/skills/ for repeatable medical, image-processing, artifact-review, and tool-evolution workflows.
- Do not use LangGraph, LangChain, OpenAI Agents SDK, application-level OpenAI API clients, or OPENAI_API_KEY for orchestration.
- Do not send patient data to external services unless the researcher has explicitly approved the service and the audit records it.

## Stable Core vs Evolvable Adapters

Stable core files include JSON schemas, unit definitions, physical equations, numerical integration, ASE thresholds, evidence contracts, quality flags, provenance requirements, audit structures, safety rules, and deterministic tests. Agents must not dynamically change these to obtain a desired result.

Evolvable adapters include DICOM/vendor parsers, image-layout parsers, color-map and Doppler-scale extraction, view classification strategies, segmentation tools, contour extraction, spectral envelope extraction, and registration adapters. Generated adapters must be versioned under generated_tools/<tool_name>/<version>/, tested, and registered without overwriting validated versions.

## Medical Safety Rules

- Do not invent measurements or infer physical units without calibration.
- Every specialist result must be saved as JSON under runs/<case_id>/agents/<agent_name>/result.json.
- Masks, contours, measurement lines, spectral envelopes, overlays, plots, and transforms must be inspectable artifacts with paths in JSON.
- For the provided complete high-quality exam set, never use a global not-enough-information fallback as the terminal result.
- Treat missing calibration, failed extraction, rejected artifacts, unresolved views, or absent quantitative metrics as upstream engineering/tooling defects to repair, then rerun the measurement.
- If the software cannot obtain required quantitative measurements, fail the run as an engineering failure with actionable repair logs rather than classifying the case as non-diagnostic.
- Preserve discordant evidence; do not average it away.
- Identify trusted, down-weighted, excluded, repaired, and repair-requested metrics in final reports or audit logs.
- Include guideline_provenance in final reports.
- Do not claim clinical validation from synthetic fixtures.

## Privacy And Git

- Never commit PHI, real DICOM/NIfTI studies, real patient videos, .env, credentials, API tokens, SSH keys, model weights, generated case masks, generated case reports, or cache directories.
- Patient and case data belong under ignored paths such as case_data/, patient_data/, runs/, outputs/, reports/, overlays/, plots/, or artifacts/.
- Preserve existing user work. Do not run destructive Git commands unless explicitly authorized.

## Review Guidelines

Prioritize medical safety, unit correctness, schema validity, provenance, privacy, measurable complete-exam behavior, and test coverage. Findings should cite file paths and line numbers.

## Verification

Before reporting build work complete, run:

    pytest
    python scripts/smoke_test.py

If the Conda environment is unavailable, report the exact command attempted and the reason verification could not be completed.
