# Architecture

The system separates a stable core from evolvable case adapters. The stable core contains schemas, unit definitions, physical equations, numerical integration, ASE threshold definitions, evidence contracts, quality flags, provenance requirements, audit structure, safety rules, and deterministic tests. Evolvable adapters are generated under generated_tools/ only after structured failures.

Codex remains the central orchestrator. Repository skills encode repeatable workflows. Project custom agents under .codex/agents/ define specialist responsibilities for case ingestion, harmonization, view classification, masks, measurements, evidence integration, safety review, and report generation.
