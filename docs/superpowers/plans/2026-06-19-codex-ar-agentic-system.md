# Codex AR Agentic System Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build the repository-scoped Codex AR multi-agent research scaffold.

**Architecture:** Add stable deterministic AR core modules, JSON schemas, custom Codex agent TOML, repository skills, prompts, docs, synthetic fixtures, and smoke tests. Preserve patient-data privacy and avoid external orchestration frameworks.

**Tech Stack:** Python 3.11, Conda, pytest, JSON Schema, Codex skills and project custom agents.

---

### Task 1: Git And Source Audit

Files: docs/HANDOFF_AUDIT.md, handoff_missing_info.md, medical_references/*

- [x] Run Git preflight commands.
- [x] Create a feature branch from main.
- [x] Inspect repository files and handoff folder.
- [x] Record missing handoff information without inventing endpoints.

### Task 2: Failing Tests

Files: tests/unit/test_physics.py, tests/integration/test_contracts_and_smoke.py

- [x] Add tests for deterministic formulas, thresholds, schemas, and smoke workflow.
- [x] Run tests and confirm failure due missing modules/scripts.

### Task 3: Stable Core And Schemas

Files: ar_core/, schemas/, scripts/, examples/

- [x] Implement deterministic formulas and threshold interpretation.
- [x] Add JSON schemas and validation script.
- [x] Add synthetic measurable final report and smoke workflow.

### Task 4: Codex Agentic Scaffold

Files: AGENTS.md, .codex/agents/, .agents/skills/, prompts/

- [x] Add project agent definitions with required instructions and repair-trigger conditions.
- [x] Add repository skills with output contracts, formulas, QC, measurable repair loops, and tool-evolution workflow.
- [x] Add central orchestration, case, validation, and tool-repair prompts.

### Task 5: Documentation, Environment, Verification, GitHub

Files: docs/, environment.yml, requirements.txt, .env.example, .gitignore

- [x] Add researcher, architecture, environment, Git, medical limitation, and JSON contract docs.
- [ ] Run pytest and python scripts/smoke_test.py.
- [ ] Fix verification failures.
- [ ] Commit milestone changes.
- [ ] Push branch and create PR if authentication permits.
