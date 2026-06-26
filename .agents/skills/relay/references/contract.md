# Contract

`relay` keeps one mission per case directory under `.relay/<case>/`.

## Files

- `case.json`: stable mission config
- `mission.md`: short mission statement and stop rules
- `logbook.md`: current status, next step, and short operational notes; Relay owns `## Supervisor Status` and the worker owns `## Worker Notes`
- `notes.json`: active advisory notes
- `note_history.jsonl`: append-only note history
- `inbox.md`: rendered view of the active advisory notes
- `directives.json`: active structured directives
- `directive_history.jsonl`: append-only directive history
- `directive_ack.json`: worker acknowledgment file for active directives
- `directive_compliance.json`: validator-written compliance report for active directives
- `ledger.jsonl`: append-only episode and validation history
- `state.json`: live state for the supervisor
- `state.lock`: state mutation lock for supervisor and control commands
- `runtime/pid`: supervisor process id
- `runtime/supervisor.json`: supervisor identity metadata
- `runtime/supervisor.log`: supervisor log
- `runtime/codex-events.jsonl`: raw JSON events from each episode
- `runtime/current_prompt.txt`: last compiled prompt
- `runtime/last_message.txt`: last message from the episode

## State

The live state tracks:

- `status`
- `stop_requested`
- `current_thread_id`
- `current_thread_started_at`
- `current_thread_episode_count`
- `total_episodes`
- `active_episode`
- `interrupt_requested`
- `interrupt_reason`
- `last_episode_exit_code`
- `last_episode_timed_out`
- `last_episode_stalled`
- `last_episode_stall_reason`
- `last_episode_interrupted`
- `last_episode_interrupt_reason`
- `last_validator_exit_code`
- `last_validator_ok`
- `completed_at`

## Policies

- One episode runs until the worker exits or the hard cap is reached.
- If Codex emits `turn.completed` but the CLI wrapper does not exit, Relay treats the turn as logically complete, waits a short grace period, and then reaps the stuck wrapper.
- If a background episode stops making observable progress, Relay classifies it as stalled when session events stop advancing, there are no live child workers, and there is no repo activity for the configured watchdog window.
- If the last observed session event is tool dispatch without matching outputs, Relay uses a shorter watchdog and treats that as `tool_dispatch_stalled`.
- If an urgent override arrives, Relay can interrupt the current episode, roll to a fresh thread, and start the next cycle with the override in force.
- After a stalled episode, Relay records the stall reason in the ledger, clears the active episode state, rolls to a fresh thread, and starts the next cycle from disk state.
- Default hard cap: `6h`
- Default max episodes per thread: `16`
- Default max thread age: `8h`
- Default stall guard: `600s`
- Default tool-dispatch stall guard: `180s`
- Default liveness poll: `5s`
- Relay does not tell the worker when to stop. It lets the Codex run end normally and checkpoints after exit or the hard cap.
- Start a fresh thread only between episodes.
- Run the validator after every episode.
- Stop only when the validator passes, the deadline arrives, or stop is requested.

## Prompt rules

The compiled prompt should be short and current:

- mission summary
- active directives
- validator command
- deadline
- requested skills
- current logbook
- advisory notes
- recent ledger tail

Keep the mission files small and use the repo files as the system of record.

`status` should expose both checkpointed state and live episode state:

- current thread id or active episode thread id
- active episode last event
- active episode pending tool calls
- active episode last progress time
- active directive ids
- directive acknowledgment state
- directive compliance state
- whether the newest directive arrived after the active episode started
- last stalled episode reason, if any

Supervisor-owned files are read-only to the worker:

- `case.json`
- `state.json`
- `notes.json`
- `note_history.jsonl`
- `directives.json`
- `directive_history.jsonl`
- `directive_compliance.json`
- `ledger.jsonl`
- `inbox.md`
- everything under `runtime/`

The worker may update only the `## Worker Notes` section of `logbook.md` and `directive_ack.json` inside the Relay case.
