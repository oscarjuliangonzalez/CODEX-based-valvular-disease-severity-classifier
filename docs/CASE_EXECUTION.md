# Case Execution

1. Place a de-identified study in case_data/<case_id>/.
2. Start Codex from the repository root while signed into the user's account.
3. Invoke $ar-case-orchestration.
4. Prompt Codex: Run the complete AR case workflow on case_data/<case_id>. Act as the central orchestrator. Spawn all necessary specialist agents. Permit versioned tool creation when required. Do not skip independent mask, artifact, and medical review. Do not force a severity classification. Return the validated final JSON and artifact paths.
5. Inspect runs/<case_id>/final_report.json, artifact_index.json, audit.json, and agents/.
