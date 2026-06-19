# Agent Team

The project defines specialist agents in .codex/agents/: guideline_curator, case_ingestion, image_harmonization, view_classifier, cardiac_phase, mask_generation, jet_characterization, jet_width_lvot, vena_contracta, pisa_analysis, cwd_analysis, pwd_analysis, doppler_volumetrics, lv_remodeling, toolsmith, evidence_integrator, medical_safety_reviewer, artifact_reviewer, and report_generator.

Each agent receives an AgentTask JSON, writes an independent result JSON, saves artifacts under its run folder, and abstains when data or calibration are insufficient.
