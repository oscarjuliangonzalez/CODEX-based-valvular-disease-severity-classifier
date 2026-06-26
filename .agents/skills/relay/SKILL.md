---
name: relay
description: Run durable long-lived missions with repo-local state, validators, and thread rollover. Use when a task needs to keep going across many sessions, across stop/start boundaries, or with periodic refreshes while preserving progress on disk.
---

# Relay

Use this skill to create or reopen a durable mission in the current project.

## First move

1. Pick or reopen a case name.
2. Create the case if it does not exist.
3. Write the mission contract and validator.
4. Start the supervisor.

Create a new case with:

```bash
python3 ~/.codex/skills/relay/scripts/relay.py create \
  --project-dir . \
  --case <case-name> \
  --goal "<goal>" \
  --validator "<validator command>" \
  --duration-hours <hours> \
  --skill <skill-1> \
  --skill <skill-2>
```

Relay launches worker episodes with `--dangerously-bypass-approvals-and-sandbox` by default. To persist any additional `codex exec` flags in the case config, add repeated `--codex-exec-arg=...` values on `create` or `start`. Relay drops `--full-auto` automatically when full-access execution is enabled so the generated `codex exec` command stays valid.

Start the supervisor with:

```bash
python3 ~/.codex/skills/relay/scripts/relay.py start --project-dir . --case <case-name>
```

For cluster-backed missions, the persisted worker launch flags can be updated on an existing case without editing `case.json` directly:

```bash
python3 ~/.codex/skills/relay/scripts/relay.py start \
  --project-dir . \
  --case <case-name> \
  --codex-exec-arg=--some-other-codex-flag
```

For an existing case, check status first:

```bash
python3 ~/.codex/skills/relay/scripts/relay.py status --project-dir . --case <case-name>
```

Add a soft steering note with:

```bash
python3 ~/.codex/skills/relay/scripts/relay.py note \
  --project-dir . \
  --case <case-name> \
  --message "Watch target A carefully."
```

Add an authoritative directive with:

```bash
python3 ~/.codex/skills/relay/scripts/relay.py directive \
  --project-dir . \
  --case <case-name> \
  add \
  --summary "Make target A the active priority." \
  --payload-json '{"active_target":"target-a"}'
```

Do not read `scripts/relay.py` unless the CLI behavior is ambiguous or broken. Use the CLI directly.

## Operating rules

- Keep mission state in `.relay/<case>/`.
- Treat `case.json`, `mission.md`, `logbook.md`, `notes.json`, `inbox.md`, `directives.json`, `ledger.jsonl`, and `state.json` as the system of record.
- Keep `logbook.md` structured: Relay owns the `## Supervisor Status` section and the worker owns the `## Worker Notes` section.
- Use `status` instead of reconstructing state from memory.
- Reuse the current thread until the episode or age policy says to refresh it, then continue from the files.
- After each episode, run the validator.
- Stop only when the validator passes, the deadline arrives, or a stop request is present.
- Do not tell the worker when to stop. Let the Codex run behave normally and let Relay checkpoint after the run exits or the hard cap is reached.
- Use `note` for soft steering. Use `notes`, `note-resolve`, and `note-expire` to inspect or archive notes. Use `directive` for structured durable instructions. Use `override` when the active episode should be interrupted for an urgent directive.
- Relay watches live episode health. If the background worker emits `turn.completed` and the CLI wrapper does not exit, Relay reaps the stuck wrapper after a short grace period.
- Relay also watches for stalled background episodes with no new session events, no worker children, and no repo activity. If that state persists, Relay terminates the stalled episode, records the stall reason, and starts the next cycle from disk state.
- Keep `mission.md` short and move detail into the repo files that already exist.
- Only the `## Worker Notes` section of `logbook.md` and `directive_ack.json` are worker-writable inside `.relay/<case>/`; `case.json`, `state.json`, `notes.json`, `note_history.jsonl`, `directives.json`, `directive_history.jsonl`, `directive_compliance.json`, `inbox.md`, `ledger.jsonl`, and `runtime/*` are supervisor-owned.
- When acknowledging directives in `directive_ack.json`, include `acknowledged_at`, `status`, and `reason`, and use the current UTC time for `acknowledged_at`.
- Compose with other skills by listing them in the case config and prompt.
- Use `start`, `status`, `note`, `notes`, `note-resolve`, `note-expire`, `directive`, `override`, `stop`, and `tail` for day-to-day control.
- When the user names companion skills, pass each one as `--skill <name>` during `create`.
- Relay keeps the active control plane small. Expired notes and directives leave the live files and move to history automatically.

## Status checks

`status` reports both mission state and active episode state.

- `thread: none` right after startup is normal if the first episode has not finished yet.
- `active_episode_last_event`, `active_episode_pending_tool_calls`, and `active_episode_last_progress` show what the live worker last did before the next checkpoint.
- `last_episode_stalled` and `last_episode_stall_reason` show whether Relay had to recover from a stalled background run on the previous cycle.
- `active_directives`, `directive_acknowledged`, `directive_compliance`, and `newest_directive_after_active_episode_start` show whether the live project state has caught up with the current directive set.

See [Quickstart](references/quickstart.md), [Contract](references/contract.md), and [Project Contract](references/project-contract.md).
