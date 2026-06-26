# Quickstart

Create a case:

```bash
python3 skills/relay/scripts/relay.py create \
  --project-dir . \
  --case paper-a \
  --goal "Replicate paper A" \
  --validator "python3 -m pytest -q" \
  --skill paper-replication \
  --skill jax-fast-code \
  --skill cluster-slurm \
  --duration-hours 48
```

Start the supervisor:

```bash
python3 skills/relay/scripts/relay.py start --project-dir . --case paper-a
```

Inspect status:

```bash
python3 skills/relay/scripts/relay.py status --project-dir . --case paper-a
```

If the first episode is still running, `thread: none` is normal until the first checkpoint finishes. Use the live fields to see what the active episode last did:

- `active_episode_last_event`
- `active_episode_pending_tool_calls`
- `active_episode_last_progress`
- `last_episode_stalled`
- `last_episode_stall_reason`

Add a steering note:

```bash
python3 skills/relay/scripts/relay.py note --project-dir . --case paper-a --message "Prioritize Figure 3."
```

List active notes:

```bash
python3 skills/relay/scripts/relay.py notes --project-dir . --case paper-a
```

Add a structured directive:

```bash
python3 skills/relay/scripts/relay.py directive \
  --project-dir . \
  --case paper-a \
  add \
  --summary "Make Figure 3 the active target" \
  --payload-json '{"active_target":"figure3"}'
```

Add an urgent override and interrupt the active episode:

```bash
python3 skills/relay/scripts/relay.py override \
  --project-dir . \
  --case paper-a \
  --summary "Stop the current path and reopen Figure 3 now" \
  --payload-json '{"active_target":"figure3","blocked_targets":["figure4"]}'
```

Resolve a note or directive after it is handled:

```bash
python3 skills/relay/scripts/relay.py note-resolve --project-dir . --case paper-a --id <note-id> --reason "handled"
python3 skills/relay/scripts/relay.py directive --project-dir . --case paper-a resolve --id <directive-id> --reason "completed"
```

Stop after the current cycle:

```bash
python3 skills/relay/scripts/relay.py stop --project-dir . --case paper-a
```

Show the latest log tail:

```bash
python3 skills/relay/scripts/relay.py tail --project-dir . --case paper-a --lines 80
```

The same case can be reopened later with `status` or `start`. New missions should use a new case name.
