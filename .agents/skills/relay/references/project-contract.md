# Project Contract

Relay stays generic. Companion skills define project semantics.

Each project that runs under Relay should expose a small project-local contract with:

- a durable project state file or small state file set
- a validator command that can check the project state
- a clear definition of active work, blocked work, next action, and completion
- a mapping from active directives into project state

Relay exposes the active directive file to the worker and validator through stable environment variables:

- `RELAY_CASE_DIR`
- `RELAY_ACTIVE_DIRECTIVES_PATH`
- `RELAY_DIRECTIVE_ACK_PATH`
- `RELAY_DIRECTIVE_COMPLIANCE_PATH`
- `RELAY_NOTE_VIEW_PATH`

The project validator should read the active directives and report whether the project state complies with them. Relay does not interpret project-specific payloads. The validator owns that logic.

The validator can write `directive_compliance.json` with:

- `checked_at`
- `ok`
- `summary`
- `directives`

`directives` should be a mapping keyed by directive id. Each entry should include:

- `compliant`
- `detail`

The worker should acknowledge active directives in `directive_ack.json`. Acknowledgments should be keyed by directive id and should include:

- `acknowledged_at`
- `status`
- `reason`

Use the current UTC time for `acknowledged_at`. Relay may normalize malformed or future acknowledgment timestamps and may fill in a default acknowledgment status when the worker omits it.

This keeps the control plane consistent across project types:

- Relay handles runtime, lifecycle, interruptions, and history.
- The companion skill defines what project state means.
- The validator decides whether the project state complies with the active directives.
