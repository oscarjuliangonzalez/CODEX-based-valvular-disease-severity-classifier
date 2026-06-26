from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
import sys
import time
import threading
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).resolve().parent / "relay.py"
SPEC = importlib.util.spec_from_file_location("relay", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RelayUnitTests(unittest.TestCase):
    def _make_case(
        self,
        root: pathlib.Path,
        *,
        skills: list[str] | None = None,
        validator: str = "true",
        codex_exec_args: list[str] | None = None,
    ):
        return MODULE.create_case(
            project_dir=root,
            case_name="paper-a",
            goal="Replicate paper A",
            validator=validator,
            skills=skills or ["paper-replication", "jax-fast-code", "cluster-slurm"],
            codex_exec_args=codex_exec_args or [],
            duration_hours=48,
            policy_overrides={
                "episode_hard_cap_hours": 0.01,
                "max_episodes_per_thread": 2,
                "max_thread_age_hours": 1,
                "stall_guard_seconds": 1,
                "tool_call_stall_seconds": 0.25,
                "liveness_poll_seconds": 0.05,
            },
        )

    def _seed_live_state(self, root: pathlib.Path, **extra):
        state_path = root / ".relay" / "paper-a" / "state.json"
        state = MODULE.read_json(state_path)
        state.update(
            {
                "status": "running",
                "total_episodes": 9,
                "current_thread_id": "thread-live",
                "current_thread_started_at": "2026-03-19T09:00:00Z",
                "current_thread_episode_count": 3,
                "active_episode": {
                    "thread_id": "thread-live",
                    "started_at": "2026-03-19T09:30:00Z",
                    "last_event_type": "response_item:reasoning",
                    "pending_tool_calls": 2,
                    "last_progress_at": "2026-03-19T09:31:00Z",
                },
                "interrupt_requested": True,
                "interrupt_reason": "directive:keep-me",
            }
        )
        state.update(extra)
        MODULE.write_json(state_path, state)
        return state

    def _fake_toolchain(self, root: pathlib.Path, validator_results: list[int] | None = None):
        bin_dir = root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex_log = root / "codex_calls.jsonl"
        validator_log = root / "validator_calls.jsonl"
        prompt_file = root / "prompt.txt"
        thread_counter = root / "thread_counter.txt"
        validator_counter = root / "validator_counter.txt"
        validator_results = validator_results or [1, 1, 0]
        codex_script_prefix = ""

        codex_script = bin_dir / "codex"
        codex_script.write_text(
            textwrap.dedent(
                f"""{codex_script_prefix}\
                #!/usr/bin/env python3
                from __future__ import annotations

                import json
                import os
                import pathlib
                import sys
                import time
                import json as jsonlib

                args = sys.argv[1:]
                mode = "resume" if "resume" in args else "exec"
                if mode == "resume":
                    idx = args.index("resume")
                    thread_id = args[-2]
                else:
                    counter_path = pathlib.Path(os.environ["FAKE_THREAD_COUNTER"])
                    current = int(counter_path.read_text(encoding="utf-8") or "0") if counter_path.exists() else 0
                    current += 1
                    counter_path.write_text(str(current), encoding="utf-8")
                    thread_id = f"thread-{{current}}"
                prompt = sys.stdin.read()
                pathlib.Path(os.environ["FAKE_PROMPT_FILE"]).write_text(prompt, encoding="utf-8")
                call_index = 0
                log_path = pathlib.Path(os.environ["FAKE_CODEX_LOG"])
                if log_path.exists():
                    call_index = len([line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()])
                call = {{"mode": mode, "thread_id": thread_id, "args": args}}
                call["relay_env"] = {{
                    "RELAY_ACTIVE_DIRECTIVES_PATH": os.environ.get("RELAY_ACTIVE_DIRECTIVES_PATH"),
                    "RELAY_DIRECTIVE_ACK_PATH": os.environ.get("RELAY_DIRECTIVE_ACK_PATH"),
                    "RELAY_DIRECTIVE_COMPLIANCE_PATH": os.environ.get("RELAY_DIRECTIVE_COMPLIANCE_PATH"),
                    "RELAY_NOTE_VIEW_PATH": os.environ.get("RELAY_NOTE_VIEW_PATH"),
                }}
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(call, sort_keys=True) + "\\n")
                behaviors = []
                if os.environ.get("FAKE_CODEX_BEHAVIORS"):
                    behaviors = jsonlib.loads(os.environ["FAKE_CODEX_BEHAVIORS"])
                behavior = behaviors[call_index] if call_index < len(behaviors) else "normal"
                output_last_message = None
                if "--output-last-message" in args:
                    output_last_message = pathlib.Path(args[args.index("--output-last-message") + 1])
                    output_last_message.write_text("worker complete\\n", encoding="utf-8")
                session_root = pathlib.Path(os.environ.get("RELAY_CODEX_SESSION_ROOT", pathlib.Path(os.environ["FAKE_PROMPT_FILE"]).parent / "sessions"))
                session_path = session_root / "2026" / "03" / "19" / f"rollout-test-{{thread_id}}.jsonl"
                session_path.parent.mkdir(parents=True, exist_ok=True)
                def write_session(payload: dict[str, object]) -> None:
                    with session_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(payload, sort_keys=True) + "\\n")
                if behavior != "no_stdout_thread_started":
                    print(json.dumps({{"type": "thread.started", "thread_id": thread_id}}), flush=True)
                print(json.dumps({{"type": "turn.started"}}), flush=True)
                write_session({{"timestamp": "2026-03-19T09:45:45.136Z", "type": "session_meta", "payload": {{"id": thread_id}}}})
                if behavior == "tool_dispatch_stall":
                    write_session(
                        {{
                            "timestamp": "2026-03-19T09:46:11.520Z",
                            "type": "response_item",
                            "call_id": "call-tool-1",
                            "payload": {{"type": "function_call", "name": "exec_command", "arguments": "{{}}"}},
                        }}
                    )
                    write_session(
                        {{
                            "timestamp": "2026-03-19T09:46:11.635Z",
                            "type": "event_msg",
                            "payload": {{"type": "token_count", "info": {{"total_token_usage": {{"total_tokens": 10}}}}}},
                        }}
                    )
                    time.sleep(float(os.environ.get("FAKE_CODEX_HANG_SECONDS", "60")))
                elif behavior == "quiet_hang":
                    time.sleep(float(os.environ.get("FAKE_CODEX_HANG_SECONDS", "60")))
                elif behavior == "session_progress_then_complete":
                    write_session(
                        {{
                            "timestamp": "2026-03-19T09:46:11.520Z",
                            "type": "response_item",
                            "payload": {{"type": "reasoning"}},
                        }}
                    )
                    time.sleep(0.1)
                    write_session(
                        {{
                            "timestamp": "2026-03-19T09:46:11.620Z",
                            "type": "event_msg",
                            "payload": {{"type": "token_count", "info": {{"total_token_usage": {{"total_tokens": 20}}}}}},
                        }}
                    )
                    time.sleep(0.1)
                print(json.dumps({{"type": "item.completed", "item": {{"id": "item_0", "type": "agent_message", "text": "worker complete"}}}}), flush=True)
                print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}}}}), flush=True)
                write_session(
                    {{
                        "timestamp": "2026-03-19T09:46:11.720Z",
                        "type": "response_item",
                        "call_id": "call-tool-1",
                        "payload": {{"type": "function_call_output", "output": "ok"}},
                    }}
                )
                if os.environ.get("FAKE_CODEX_HANG_AFTER_TURN_COMPLETE") == "1":
                    time.sleep(float(os.environ.get("FAKE_CODEX_HANG_SECONDS", "60")))
                """
            ),
            encoding="utf-8",
        )
        codex_script.chmod(codex_script.stat().st_mode | stat.S_IEXEC)

        validator_script = bin_dir / "validator"
        validator_script.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                from __future__ import annotations

                import os
                import pathlib
                import sys
                import json

                counter_path = pathlib.Path(os.environ["FAKE_VALIDATOR_COUNTER"])
                current = int(counter_path.read_text(encoding="utf-8") or "0") if counter_path.exists() else 0
                current += 1
                counter_path.write_text(str(current), encoding="utf-8")
                if os.environ.get("FAKE_VALIDATOR_LOG"):
                    log_path = pathlib.Path(os.environ["FAKE_VALIDATOR_LOG"])
                    record = {{
                        "RELAY_ACTIVE_DIRECTIVES_PATH": os.environ.get("RELAY_ACTIVE_DIRECTIVES_PATH"),
                        "RELAY_DIRECTIVE_COMPLIANCE_PATH": os.environ.get("RELAY_DIRECTIVE_COMPLIANCE_PATH"),
                    }}
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, sort_keys=True) + "\\n")
                if os.environ.get("FAKE_VALIDATOR_WRITES_DIRECTIVE_COMPLIANCE") == "1":
                    compliance_path = pathlib.Path(os.environ["RELAY_DIRECTIVE_COMPLIANCE_PATH"])
                    compliance_path.write_text(
                        json.dumps(
                            {{
                                "schema_version": 1,
                                "checked_at": "2026-03-19T09:46:12Z",
                                "ok": True,
                                "summary": "all active directives compliant",
                                "directives": {{}},
                            }},
                            indent=2,
                            sort_keys=True,
                        )
                        + "\\n",
                        encoding="utf-8",
                    )
                outcomes = {validator_results!r}
                index = min(current - 1, len(outcomes) - 1)
                sys.exit(outcomes[index])
                """
            ),
            encoding="utf-8",
        )
        validator_script.chmod(validator_script.stat().st_mode | stat.S_IEXEC)
        return {
            "codex_bin": codex_script,
            "validator_bin": validator_script,
            "codex_log": codex_log,
            "validator_log": validator_log,
            "prompt_file": prompt_file,
            "thread_counter": thread_counter,
            "validator_counter": validator_counter,
        }

    def test_create_writes_expected_layout_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            first = self._make_case(root)
            second = self._make_case(root)

            case_dir = root / ".relay" / "paper-a"
            self.assertTrue((case_dir / "case.json").exists())
            self.assertTrue((case_dir / "mission.md").exists())
            self.assertTrue((case_dir / "logbook.md").exists())
            self.assertTrue((case_dir / "inbox.md").exists())
            self.assertTrue((case_dir / "notes.json").exists())
            self.assertTrue((case_dir / "note_history.jsonl").exists())
            self.assertTrue((case_dir / "directives.json").exists())
            self.assertTrue((case_dir / "directive_history.jsonl").exists())
            self.assertTrue((case_dir / "directive_ack.json").exists())
            self.assertTrue((case_dir / "directive_compliance.json").exists())
            self.assertTrue((case_dir / "ledger.jsonl").exists())
            self.assertTrue((case_dir / "state.json").exists())
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["config"]["skills"], ["paper-replication", "jax-fast-code", "cluster-slurm"])
            self.assertEqual(first["config"]["codex_exec_args"], ["--dangerously-bypass-approvals-and-sandbox"])
            self.assertIn(".relay/paper-a/logbook.md", (case_dir / "mission.md").read_text(encoding="utf-8"))
            self.assertIn("Let the run end naturally.", (case_dir / "mission.md").read_text(encoding="utf-8"))

    def test_create_case_bootstraps_structured_logbook(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)

            logbook_text = (root / ".relay" / "paper-a" / "logbook.md").read_text(encoding="utf-8")

            self.assertIn("## Supervisor Status", logbook_text)
            self.assertIn("## Worker Notes", logbook_text)
            self.assertIn("Keep this section short and durable.", logbook_text)
            self.assertIn("- Active target:", logbook_text)

    def test_status_note_and_stop_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            note_result = MODULE.append_note(case, "Prioritize Figure 3.")
            stop_result = MODULE.request_stop(case)
            snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))

            self.assertIn("Prioritize Figure 3.", note_result["inbox"])
            self.assertNotIn("No notes yet.", note_result["inbox"])
            self.assertTrue(stop_result["stop_requested"])
            self.assertTrue(snapshot["stop_requested"])
            self.assertEqual(snapshot["status"], "stopping")

    def test_load_case_refreshes_mission_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            mission_path = root / ".relay" / "paper-a" / "mission.md"
            mission_path.write_text("stale\n", encoding="utf-8")

            case = MODULE.load_case(root, "paper-a")

            self.assertIn("Let the run end naturally.", mission_path.read_text(encoding="utf-8"))
            self.assertEqual(case["files"]["mission"].resolve(), mission_path.resolve())

    def test_load_case_adds_default_codex_exec_args_to_legacy_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            config_path = root / ".relay" / "paper-a" / "case.json"
            config = MODULE.read_json(config_path)
            config.pop("codex_exec_args", None)
            MODULE.write_json(config_path, config)

            case = MODULE.load_case(root, "paper-a")
            stored = MODULE.read_json(config_path)

            self.assertEqual(case["config"]["codex_exec_args"], ["--dangerously-bypass-approvals-and-sandbox"])
            self.assertEqual(stored["codex_exec_args"], ["--dangerously-bypass-approvals-and-sandbox"])

    def test_default_policy_uses_sixteen_episodes_per_thread(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            case = MODULE.create_case(
                project_dir=root,
                case_name="paper-a",
                goal="Replicate paper A",
                validator="true",
                duration_hours=24,
            )

            self.assertEqual(case["config"]["policy"]["max_episodes_per_thread"], 16)
            self.assertEqual(case["config"]["policy"]["max_thread_age_hours"], 8)
            self.assertEqual(case["config"]["policy"]["episode_hard_cap_hours"], 6)
            self.assertEqual(case["config"]["policy"]["stall_guard_seconds"], 600)
            self.assertEqual(case["config"]["policy"]["tool_call_stall_seconds"], 180)
            self.assertEqual(case["config"]["policy"]["liveness_poll_seconds"], 5)

    def test_prompt_compilation_includes_skills_and_repo_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            MODULE.append_note(case, "Use the JAX path first.")
            MODULE.add_directive(
                case,
                summary="Require topology gates before promotion.",
                payload={"directive_id": "dir-topology", "expected_outcome": "Only watertight candidates promote."},
                priority="high",
            )
            case = MODULE.load_case(root, "paper-a")
            prompt = MODULE.build_prompt(case, case["state"])

            self.assertIn("paper-replication", prompt)
            self.assertIn("jax-fast-code", prompt)
            self.assertIn("cluster-slurm", prompt)
            self.assertIn("Replicate paper A", prompt)
            self.assertIn(".relay/paper-a/directives.json", prompt)
            self.assertIn(".relay/paper-a/logbook.md", prompt)
            self.assertIn(".relay/paper-a/inbox.md", prompt)
            self.assertIn(".relay/paper-a/directive_ack.json", prompt)
            self.assertIn("Active directives are authoritative. Notes are advisory.", prompt)
            self.assertIn("Active directive details:", prompt)
            self.assertIn("Require topology gates before promotion.", prompt)
            self.assertIn("\"directive_id\": \"dir-topology\"", prompt)
            self.assertIn("Do not edit `.relay/paper-a/case.json`, `.relay/paper-a/state.json`, `.relay/paper-a/notes.json`", prompt)
            self.assertIn("Let the run end naturally. Relay will checkpoint after the worker exits or the hard cap is reached.", prompt)

    def test_prompt_compilation_includes_recent_ledger_tail(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            for index in range(7):
                MODULE.append_jsonl(
                    case["files"]["ledger"],
                    {"type": "episode", "total_episodes": index, "returncode": index},
                )

            prompt = MODULE.build_prompt(MODULE.load_case(root, "paper-a"), case["state"])

            self.assertIn("Recent ledger tail:", prompt)
            self.assertNotIn('"total_episodes": 0', prompt)
            self.assertIn('"total_episodes": 2', prompt)
            self.assertIn('"total_episodes": 6', prompt)

    def test_build_prompt_instructs_worker_to_use_worker_notes_section(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")

            prompt = MODULE.build_prompt(case, case["state"])

            self.assertIn("## Worker Notes", prompt)
            self.assertIn("update only the `## Worker Notes` section", prompt)
            self.assertIn("Record the active target, what changed, the blocker, the exact next action", prompt)

    def test_update_logbook_preserves_worker_notes_section(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            custom_worker_notes = textwrap.dedent(
                """\
                Keep this section short and durable.
                - Active target: fig_ex2compiled
                - Changes this cycle: Submitted Gautschi run 9115415.
                - Blocker: Waiting on the canonical artifact download.
                - Exact next action: Poll the tracked run and register provenance.
                - Cluster / run ids: job=9115415 run=physics-informed-20260408-085842
                """
            ).rstrip()
            write_path = root / ".relay" / "paper-a" / "logbook.md"
            write_path.write_text(
                MODULE.logbook_text(case, case["state"], "Resume the mission.", worker_notes=custom_worker_notes),
                encoding="utf-8",
            )

            MODULE.update_logbook(case, case["state"], "Continue on the current thread.")

            updated = write_path.read_text(encoding="utf-8")
            self.assertIn("## Supervisor Status", updated)
            self.assertIn("## Worker Notes", updated)
            self.assertIn("Submitted Gautschi run 9115415.", updated)
            self.assertIn("job=9115415 run=physics-informed-20260408-085842", updated)
            self.assertIn("Next action: Continue on the current thread.", updated)

    def test_update_logbook_migrates_legacy_notes_into_worker_section(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            logbook_path = root / ".relay" / "paper-a" / "logbook.md"
            legacy_logbook = textwrap.dedent(
                """\
                # Logbook

                Status: running
                Stop requested: False
                Interrupt requested: False
                Current thread: thread-1
                Current thread episodes: 1
                Total episodes: 1
                Last validator ok: False
                Last validator exit code: 1
                Active directives: none
                Active notes: 0

                Recent progress:
                - Tuned Example 3.
                - Waiting on Gautschi.

                Next action: Poll job 9115524.
                """
            )
            logbook_path.write_text(legacy_logbook, encoding="utf-8")

            MODULE.update_logbook(case, case["state"], "Continue on the current thread.")

            updated = logbook_path.read_text(encoding="utf-8")
            self.assertIn("## Supervisor Status", updated)
            self.assertIn("## Worker Notes", updated)
            self.assertIn("Recent progress:", updated)
            self.assertIn("- Tuned Example 3.", updated)
            self.assertIn("Next action: Continue on the current thread.", updated)

    def test_thread_rollover_decision_uses_policy(self):
        now = MODULE.utc_now()
        state = {
            "current_thread_id": "thread-1",
            "current_thread_started_at": (now - MODULE.timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "current_thread_episode_count": 2,
        }
        should_roll, reason = MODULE.should_start_fresh_thread(state, {"max_episodes_per_thread": 2, "max_thread_age_hours": 1}, now)
        self.assertTrue(should_roll)
        self.assertEqual(reason, "episode_limit")

    def test_supervise_loop_runs_resume_then_refreshes_thread_and_passes_validator(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[1, 1, 0])
            self._make_case(root, validator=f"{tools['validator_bin']}", skills=["paper-replication", "jax-fast-code", "cluster-slurm"])
            case = MODULE.load_case(root, "paper-a")
            case["config"]["policy"]["max_episodes_per_thread"] = 2
            case["config"]["policy"]["episode_hard_cap_hours"] = 0.01
            case["config"]["policy"]["max_thread_age_hours"] = 1
            save_path = case["files"]["config"]
            MODULE.write_json(save_path, case["config"])

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                snapshot = MODULE.supervise_case(case, max_cycles=4)

            calls = [json.loads(line) for line in tools["codex_log"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual([call["mode"] for call in calls], ["exec", "resume", "exec"])
            self.assertEqual([call["thread_id"] for call in calls], ["thread-1", "thread-1", "thread-2"])
            self.assertIn("paper-replication", tools["prompt_file"].read_text(encoding="utf-8"))
            self.assertIn("jax-fast-code", tools["prompt_file"].read_text(encoding="utf-8"))
            self.assertIn("cluster-slurm", tools["prompt_file"].read_text(encoding="utf-8"))
            self.assertTrue(snapshot["last_validator_ok"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["current_thread_episode_count"], 1)
            self.assertEqual(snapshot["total_episodes"], 3)
            self.assertIsNone(snapshot["current_rollover_reason"])
            self.assertTrue((root / ".relay" / "paper-a" / "runtime" / "current_prompt.txt").exists())

    def test_run_episode_reaps_stalled_cli_after_turn_completed(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_HANG_AFTER_TURN_COMPLETE": "1",
                    "FAKE_CODEX_HANG_SECONDS": "60",
                    "RELAY_TURN_COMPLETION_GRACE_SECONDS": "0.1",
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", None)

            self.assertFalse(episode.timed_out)
            self.assertTrue(episode.completion_guard_triggered)
            self.assertFalse(episode.stalled_guard_triggered)
            self.assertEqual(episode.returncode, 0)
            self.assertEqual(episode.thread_id, "thread-1")
            self.assertIn("worker complete", episode.last_message)
            self.assertIn("turn.completed", episode.stdout)
            self.assertIn(
                "completion_guard_triggered=True",
                (root / ".relay" / "paper-a" / "runtime" / "supervisor.log").read_text(encoding="utf-8"),
            )

    def test_run_episode_reaps_tool_dispatch_stall(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["tool_dispatch_stall"]),
                    "FAKE_CODEX_HANG_SECONDS": "60",
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", None)

            self.assertFalse(episode.timed_out)
            self.assertFalse(episode.completion_guard_triggered)
            self.assertTrue(episode.stalled_guard_triggered)
            self.assertEqual(episode.stall_reason, "tool_dispatch_stalled")
            self.assertEqual(episode.returncode, 125)
            self.assertEqual(episode.thread_id, "thread-1")
            self.assertGreater(episode.pending_tool_calls, 0)
            self.assertTrue(episode.session_log_path)
            snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))
            self.assertFalse(snapshot["active_episode"])

    def test_run_episode_uses_session_log_liveness(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["session_progress_then_complete"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", None)

            self.assertFalse(episode.timed_out)
            self.assertFalse(episode.completion_guard_triggered)
            self.assertFalse(episode.stalled_guard_triggered)
            self.assertEqual(episode.returncode, 0)
            self.assertEqual(episode.thread_id, "thread-1")
            self.assertIn("turn.completed", episode.stdout)

    def test_run_episode_recovers_thread_id_from_session_log_when_stdout_omits_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["no_stdout_thread_started"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", None)

            self.assertEqual(episode.returncode, 0)
            self.assertEqual(episode.thread_id, "thread-1")
            self.assertNotIn("thread.started", episode.stdout)
            self.assertTrue(episode.session_log_path)

    def test_run_episode_ignores_preexisting_foreign_session_logs_when_stdout_omits_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            session_root = root / "sessions"
            foreign_path = session_root / "2026" / "03" / "18" / "rollout-foreign.jsonl"
            foreign_path.parent.mkdir(parents=True, exist_ok=True)
            foreign_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-18T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thread-foreign"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["no_stdout_thread_started"]),
                    "RELAY_CODEX_SESSION_ROOT": str(session_root),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", None)

            self.assertEqual(episode.returncode, 0)
            self.assertEqual(episode.thread_id, "thread-1")
            self.assertTrue(episode.session_log_path)
            self.assertIn("thread-1", episode.session_log_path)

    def test_run_episode_keeps_resume_thread_when_stdout_omits_thread_started(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["no_stdout_thread_started"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", "thread-live")

            self.assertEqual(episode.returncode, 0)
            self.assertEqual(episode.thread_id, "thread-live")
            self.assertNotIn("thread.started", episode.stdout)

    def test_run_episode_reaps_inactive_episode(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["quiet_hang"]),
                    "FAKE_CODEX_HANG_SECONDS": "60",
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, case["state"], "Keep going.\n", None)

            self.assertFalse(episode.timed_out)
            self.assertFalse(episode.completion_guard_triggered)
            self.assertTrue(episode.stalled_guard_triggered)
            self.assertEqual(episode.stall_reason, "inactive_episode")
            self.assertEqual(episode.returncode, 125)
            self.assertEqual(episode.thread_id, "thread-1")

    def test_status_snapshot_prefers_active_episode_thread(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            state = case["state"]
            state["active_episode"] = {
                "thread_id": "thread-live",
                "last_event_type": "response_item:function_call",
                "pending_tool_calls": 2,
                "last_progress_at": "2026-03-19T09:46:11Z",
            }
            MODULE.save_case_state(case, state)
            snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))

            self.assertEqual(snapshot["current_thread_id"], "thread-live")
            self.assertEqual(snapshot["active_episode"]["pending_tool_calls"], 2)

    def test_supervise_case_recovers_from_stalled_episode_with_fresh_thread(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[1, 0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            case["config"]["policy"]["max_episodes_per_thread"] = 8
            MODULE.write_json(case["files"]["config"], case["config"])

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["tool_dispatch_stall", "normal"]),
                    "FAKE_CODEX_HANG_SECONDS": "60",
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                snapshot = MODULE.supervise_case(case, max_cycles=3)

            calls = [json.loads(line) for line in tools["codex_log"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual([call["mode"] for call in calls], ["exec", "exec"])
            self.assertEqual([call["thread_id"] for call in calls], ["thread-1", "thread-2"])
            self.assertTrue(snapshot["last_validator_ok"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertFalse(snapshot["last_episode_stalled"])
            ledger_text = (root / ".relay" / "paper-a" / "ledger.jsonl").read_text(encoding="utf-8")
            self.assertIn('"stalled_guard_triggered": true', ledger_text)
            supervisor_log = (root / ".relay" / "paper-a" / "runtime" / "supervisor.log").read_text(encoding="utf-8")
            self.assertIn("tool_dispatch_stalled", supervisor_log)

    def test_supervise_case_preserves_worker_notes_across_failed_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[1])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            logbook_path = root / ".relay" / "paper-a" / "logbook.md"
            seeded_worker_notes = textwrap.dedent(
                """\
                Keep this section short and durable.
                - Active target: fig_ex3a_trace
                - Changes this cycle: Tuned outer_alpha0 to 5e-4.
                - Blocker: GPU trace still drifts.
                - Exact next action: Reduce outer_alpha0 again and rerun Gautschi.
                - Cluster / run ids: job=9115524
                """
            ).rstrip()
            logbook_path.write_text(
                MODULE.logbook_text(case, case["state"], "Create the case and start the first cycle.", worker_notes=seeded_worker_notes),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                MODULE.supervise_case(case, max_cycles=1)

            updated = logbook_path.read_text(encoding="utf-8")
            self.assertIn("## Worker Notes", updated)
            self.assertIn("Tuned outer_alpha0 to 5e-4.", updated)
            self.assertIn("job=9115524", updated)
            self.assertIn("Next action: Continue on the current thread.", updated)

    def test_supervise_case_recovers_new_thread_id_from_session_log(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[1, 0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            case["config"]["policy"]["max_episodes_per_thread"] = 1
            MODULE.write_json(case["files"]["config"], case["config"])

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["normal", "no_stdout_thread_started"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                snapshot = MODULE.supervise_case(case, max_cycles=3)

            calls = [json.loads(line) for line in tools["codex_log"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual([call["thread_id"] for call in calls], ["thread-1", "thread-2"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertTrue(snapshot["last_validator_ok"])
            self.assertIsNone(snapshot["last_error"])

    def test_start_is_idempotent_when_supervisor_is_already_running(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")

            with patch.object(MODULE, "current_supervisor_pid", return_value=4242), patch.object(
                MODULE.subprocess,
                "Popen",
                return_value=SimpleNamespace(pid=9999),
            ) as popen_mock:
                result = MODULE.spawn_supervisor(case)

            self.assertEqual(result["supervisor_pid"], 4242)
            self.assertTrue(result["already_running"])
            self.assertEqual(result["status"], "running")
            popen_mock.assert_not_called()

    def test_clear_supervisor_identity_preserves_replacement_pid_or_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")

            case["paths"]["pid"].write_text("2222", encoding="utf-8")
            MODULE.write_supervisor_metadata(case, pid=1111)
            MODULE.clear_supervisor_runtime_identity(case, expected_pid=1111)
            self.assertEqual(case["paths"]["pid"].read_text(encoding="utf-8"), "2222")
            self.assertTrue(case["paths"]["supervisor_meta"].exists())

            case["paths"]["pid"].write_text("1111", encoding="utf-8")
            MODULE.write_supervisor_metadata(case, pid=2222)
            MODULE.clear_supervisor_runtime_identity(case, expected_pid=1111)
            self.assertEqual(case["paths"]["pid"].read_text(encoding="utf-8"), "1111")
            self.assertEqual(MODULE.read_json(case["paths"]["supervisor_meta"])["pid"], 2222)

            case["paths"]["pid"].write_text("1111", encoding="utf-8")
            MODULE.write_supervisor_metadata(case, pid=1111)
            MODULE.clear_supervisor_runtime_identity(case, expected_pid=1111)
            self.assertFalse(case["paths"]["pid"].exists())
            self.assertFalse(case["paths"]["supervisor_meta"].exists())

    def test_start_fails_closed_when_live_supervisor_is_stopping(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            MODULE.request_stop(case)
            stopping_case = MODULE.load_case(root, "paper-a")

            with patch.object(MODULE, "current_supervisor_pid", return_value=4242), patch.object(
                MODULE.subprocess,
                "Popen",
                return_value=SimpleNamespace(pid=9999),
            ) as popen_mock:
                result = MODULE.spawn_supervisor(stopping_case)

            refreshed = MODULE.load_case(root, "paper-a")
            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(result["blocked_reason"], "supervisor_stopping")
            self.assertEqual(result["supervisor_pid"], 4242)
            self.assertTrue(result["supervisor_running"])
            self.assertEqual(result["status"], "stopping")
            self.assertTrue(result["stop_requested"])
            self.assertTrue(refreshed["state"]["stop_requested"])
            self.assertEqual(refreshed["state"]["status"], "stopping")
            popen_mock.assert_not_called()

    def test_start_clears_latched_stop_request_before_spawning(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            MODULE.request_stop(case)
            stopped_case = MODULE.load_case(root, "paper-a")

            with patch.object(MODULE, "current_supervisor_pid", return_value=None), patch.object(
                MODULE.subprocess,
                "Popen",
                return_value=SimpleNamespace(pid=9999),
            ):
                result = MODULE.spawn_supervisor(stopped_case)

            refreshed = MODULE.load_case(root, "paper-a")
            self.assertEqual(result["supervisor_pid"], 9999)
            self.assertEqual(result["status"], "running")
            self.assertFalse(refreshed["state"]["stop_requested"])
            self.assertEqual(refreshed["state"]["status"], "running")

    def test_control_commands_preserve_live_execution_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            state_path = root / ".relay" / "paper-a" / "state.json"

            with self.subTest("append_note"):
                case = MODULE.load_case(root, "paper-a")
                seeded = self._seed_live_state(root)
                MODULE.append_note(case, "watch target-a")
                after = MODULE.read_json(state_path)
                self.assertEqual(after["total_episodes"], seeded["total_episodes"])
                self.assertEqual(after["active_episode"], seeded["active_episode"])
                self.assertEqual(after["interrupt_requested"], seeded["interrupt_requested"])
                self.assertEqual(after["interrupt_reason"], seeded["interrupt_reason"])
                self.assertEqual(after["last_cycle_note"], "watch target-a")

            with self.subTest("add_directive"):
                case = MODULE.load_case(root, "paper-a")
                seeded = self._seed_live_state(root)
                MODULE.add_directive(case, summary="pin target-a", payload={"active_target": "target-a"})
                after = MODULE.read_json(state_path)
                self.assertEqual(after["total_episodes"], seeded["total_episodes"])
                self.assertEqual(after["active_episode"], seeded["active_episode"])
                self.assertEqual(after["interrupt_requested"], seeded["interrupt_requested"])
                self.assertEqual(after["interrupt_reason"], seeded["interrupt_reason"])
                self.assertEqual(after["last_cycle_note"], "pin target-a")

            with self.subTest("request_stop"):
                case = MODULE.load_case(root, "paper-a")
                seeded = self._seed_live_state(root)
                MODULE.request_stop(case)
                after = MODULE.read_json(state_path)
                self.assertEqual(after["total_episodes"], seeded["total_episodes"])
                self.assertEqual(after["active_episode"], seeded["active_episode"])
                self.assertEqual(after["interrupt_requested"], seeded["interrupt_requested"])
                self.assertEqual(after["interrupt_reason"], seeded["interrupt_reason"])
                self.assertTrue(after["stop_requested"])
                self.assertEqual(after["status"], "stopping")

            with self.subTest("clear_stop_request"):
                case = MODULE.load_case(root, "paper-a")
                seeded = self._seed_live_state(root, stop_requested=True, status="stopping")
                MODULE.clear_stop_request(case)
                after = MODULE.read_json(state_path)
                self.assertEqual(after["total_episodes"], seeded["total_episodes"])
                self.assertEqual(after["active_episode"], seeded["active_episode"])
                self.assertEqual(after["interrupt_requested"], seeded["interrupt_requested"])
                self.assertEqual(after["interrupt_reason"], seeded["interrupt_reason"])
                self.assertFalse(after["stop_requested"])
                self.assertEqual(after["status"], "idle")

    def test_foreign_pid_is_not_treated_as_running_supervisor(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            sleeper = subprocess.Popen(["sleep", "5"])
            start = None
            try:
                case = MODULE.load_case(root, "paper-a")
                case["paths"]["pid"].write_text(str(sleeper.pid), encoding="utf-8")
                status = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))
                start = MODULE.spawn_supervisor(MODULE.load_case(root, "paper-a"))
                self.assertFalse(status["supervisor_running"])
                self.assertIsNone(status["supervisor_pid"])
                self.assertFalse(start.get("already_running", False))
                self.assertNotEqual(start["supervisor_pid"], sleeper.pid)
                self.assertEqual(MODULE.read_pid_file(case["paths"]["pid"]), start["supervisor_pid"])
                self.assertTrue(start["supervisor_pid"] > 0)
                deadline = time.time() + 5.0
                while time.time() < deadline and MODULE.is_process_alive(start["supervisor_pid"]):
                    time.sleep(0.05)
            finally:
                if start and MODULE.is_process_alive(start["supervisor_pid"]):
                    try:
                        os.kill(start["supervisor_pid"], MODULE.signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                sleeper.terminate()
                sleeper.wait(timeout=5)

    def test_supervisor_command_match_accepts_project_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "project with spaces"
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            tokens = [
                sys.executable,
                str(SCRIPT),
                "supervise",
                "--project-dir",
                *str(case["project_root"]).split(" "),
                "--case",
                "paper-a",
            ]

            self.assertTrue(MODULE.command_matches_supervisor(tokens, case))

            foreign_tokens = list(tokens)
            foreign_tokens[-1] = "paper-b"
            self.assertFalse(MODULE.command_matches_supervisor(foreign_tokens, case))

    def test_control_commands_do_not_signal_foreign_pid(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            sleeper = subprocess.Popen(["sleep", "5"])
            try:
                case = MODULE.load_case(root, "paper-a")
                case["paths"]["pid"].write_text(str(sleeper.pid), encoding="utf-8")
                state = case["state"]
                state["active_episode"] = {
                    "thread_id": "thread-live",
                    "started_at": "2026-03-19T09:00:00Z",
                    "last_event_type": "response_item:reasoning",
                    "pending_tool_calls": 0,
                    "last_progress_at": "2026-03-19T09:30:00Z",
                }
                MODULE.save_case_state(case, state)

                with patch.object(MODULE.os, "kill") as kill_mock:
                    MODULE.request_stop(MODULE.load_case(root, "paper-a"))
                    MODULE.add_directive(
                        MODULE.load_case(root, "paper-a"),
                        summary="interrupt now",
                        payload={"active_target": "target-a"},
                        mode="override",
                        priority="high",
                        interrupt_policy="immediate",
                    )

                kill_calls = [call.args for call in kill_mock.call_args_list]
                self.assertNotIn((sleeper.pid, MODULE.signal.SIGTERM), kill_calls)
                self.assertNotIn((sleeper.pid, MODULE.signal.SIGUSR1), kill_calls)
            finally:
                sleeper.terminate()
                sleeper.wait(timeout=5)

    def test_json_flag_is_accepted_after_subcommand(self):
        args = MODULE.parse_args(["status", "--project-dir", ".", "--case", "paper-a", "--json"])
        self.assertTrue(args.json)
        self.assertEqual(args.command, "status")

    def test_episode_commands_include_full_access_and_resume_subcommand_syntax(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root, codex_exec_args=["--sandbox-debug"])
            case = MODULE.load_case(root, "paper-a")

            fresh = MODULE.build_episode_command(case, None)
            resumed = MODULE.build_episode_command(case, "thread-123")

            self.assertEqual(fresh[:2], ["codex", "exec"])
            self.assertEqual(
                fresh[2:4],
                ["--dangerously-bypass-approvals-and-sandbox", "--sandbox-debug"],
            )
            self.assertNotIn("--full-auto", fresh)
            self.assertIn("-C", fresh)
            self.assertEqual(
                resumed[:5],
                ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--sandbox-debug", "resume"],
            )
            self.assertNotIn("--full-auto", resumed)
            self.assertNotIn("-C", resumed)
            self.assertEqual(resumed[-2:], ["thread-123", "-"])

    def test_episode_commands_keep_full_auto_when_full_access_is_not_requested(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            case["config"]["codex_exec_args"] = ["--sandbox-debug"]

            with patch.object(MODULE, "DEFAULT_CODEX_EXEC_ARGS", []):
                fresh = MODULE.build_episode_command(case, None)
                resumed = MODULE.build_episode_command(case, "thread-123")

            self.assertEqual(fresh[:3], ["codex", "exec", "--sandbox-debug"])
            self.assertIn("--full-auto", fresh)
            self.assertEqual(resumed[:4], ["codex", "exec", "--sandbox-debug", "resume"])
            self.assertIn("--full-auto", resumed)

    def test_start_updates_codex_exec_args_for_existing_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)

            with patch.object(MODULE, "spawn_supervisor", return_value={"case_name": "paper-a", "supervisor_pid": 9999, "status": "running"}):
                with patch("sys.stdout", new=io.StringIO()):
                    MODULE.main(
                        [
                            "start",
                            "--project-dir",
                            str(root),
                            "--case",
                            "paper-a",
                            "--codex-exec-arg=--sandbox-debug",
                            "--json",
                        ]
                    )

            refreshed = MODULE.load_case(root, "paper-a")
            self.assertEqual(
                refreshed["config"]["codex_exec_args"],
                ["--dangerously-bypass-approvals-and-sandbox", "--sandbox-debug"],
            )

    def test_directive_lifecycle_archives_superseded_and_resolved_items(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")

            first = MODULE.add_directive(
                case,
                summary="Prioritize the current target.",
                payload={"active_target": "target-a"},
            )["directive"]
            second = MODULE.add_directive(
                MODULE.load_case(root, "paper-a"),
                summary="Replace the old priority.",
                payload={"active_target": "target-b"},
                supersedes=[first["id"]],
            )["directive"]

            listed = MODULE.list_directives(MODULE.load_case(root, "paper-a"))
            self.assertEqual([item["id"] for item in listed["directives"]], [second["id"]])

            resolved = MODULE.resolve_directive(MODULE.load_case(root, "paper-a"), second["id"], reason="done")
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(MODULE.list_directives(MODULE.load_case(root, "paper-a"))["directives"], [])

            history = (root / ".relay" / "paper-a" / "directive_history.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event_type": "superseded"', history)
            self.assertIn('"event_type": "resolved"', history)

    def test_new_directive_does_not_emit_compliance_before_validator_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")

            MODULE.add_directive(
                case,
                summary="Prioritize the current target.",
                payload={"active_target": "target-a"},
            )

            refreshed = MODULE.load_case(root, "paper-a")
            directive = refreshed["control"]["directives"]["directives"][0]
            history_events = [
                json.loads(line)["event_type"]
                for line in refreshed["files"]["directive_history"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            snapshot = MODULE.status_snapshot(refreshed)

            self.assertEqual(history_events, ["created"])
            self.assertIsNone(directive["project_compliance"])
            self.assertIsNone(directive["project_compliance_checked_at"])
            self.assertIsNone(directive["project_compliance_detail"])
            self.assertIsNone(snapshot["directive_compliance"])

    def test_expired_notes_are_archived_and_inbox_view_is_refreshed(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            past = "2020-01-01T00:00:00Z"

            MODULE.append_note(case, "Old note", expires_at=past)
            refreshed = MODULE.load_case(root, "paper-a")

            notes_payload = MODULE.read_json(refreshed["files"]["notes"])
            self.assertEqual(notes_payload["notes"], [])
            self.assertIn("No notes yet.", refreshed["files"]["inbox"].read_text(encoding="utf-8"))
            history = refreshed["files"]["note_history"].read_text(encoding="utf-8")
            self.assertIn('"event_type": "created"', history)
            self.assertIn('"event_type": "expired"', history)

    def test_status_snapshot_reports_directive_acknowledgment_compliance_and_freshness(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            directive = MODULE.add_directive(
                case,
                summary="Make target-a active.",
                payload={"active_target": "target-a"},
            )["directive"]
            ack_payload = MODULE.default_directive_ack_payload()
            ack_payload["acks"] = {
                directive["id"]: {
                    "acknowledged_at": "2026-03-19T09:46:11Z",
                    "status": "accepted",
                    "reason": "active target updated",
                }
            }
            MODULE.write_json(case["files"]["directive_ack"], ack_payload)
            compliance_payload = MODULE.default_directive_compliance_payload()
            compliance_payload["checked_at"] = "2026-03-19T09:46:12Z"
            compliance_payload["ok"] = True
            compliance_payload["summary"] = "all active directives compliant"
            compliance_payload["directives"] = {
                directive["id"]: {
                    "compliant": True,
                    "detail": "project state matches the directive",
                }
            }
            MODULE.write_json(case["files"]["directive_compliance"], compliance_payload)
            state = case["state"]
            state["active_episode"] = {
                "thread_id": "thread-live",
                "started_at": "2026-03-19T09:00:00Z",
                "last_event_type": "response_item:reasoning",
                "pending_tool_calls": 0,
                "last_progress_at": "2026-03-19T09:30:00Z",
            }
            MODULE.save_case_state(case, state)

            snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))

            self.assertEqual(snapshot["active_directive_ids"], [directive["id"]])
            self.assertTrue(snapshot["directive_acknowledged"])
            self.assertTrue(snapshot["directive_compliance"])
            self.assertTrue(snapshot["newest_directive_started_after_episode"])

    def test_status_snapshot_normalizes_missing_ack_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            directive = MODULE.add_directive(
                case,
                summary="Make target-a active.",
                payload={"active_target": "target-a"},
            )["directive"]
            ack_payload = MODULE.default_directive_ack_payload()
            ack_payload["acks"] = {
                directive["id"]: {
                    "acknowledged_at": "2026-03-19T09:46:11Z",
                    "reason": "active target updated",
                }
            }
            MODULE.write_json(case["files"]["directive_ack"], ack_payload)

            snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))

            self.assertTrue(snapshot["directive_acknowledged"])
            refreshed = MODULE.load_case(root, "paper-a")
            directives = refreshed["control"]["directives"]["directives"]
            self.assertEqual(directives[0]["acknowledgment_status"], "acknowledged")
            ack_file = MODULE.read_json(refreshed["files"]["directive_ack"])
            self.assertEqual(ack_file["acks"][directive["id"]]["status"], "acknowledged")

    def test_status_snapshot_clamps_future_ack_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            directive = MODULE.add_directive(
                case,
                summary="Make target-a active.",
                payload={"active_target": "target-a"},
            )["directive"]
            ack_payload = MODULE.default_directive_ack_payload()
            ack_payload["acks"] = {
                directive["id"]: {
                    "acknowledged_at": "2026-03-19T11:30:00Z",
                    "status": "accepted",
                    "reason": "active target updated",
                }
            }
            MODULE.write_json(case["files"]["directive_ack"], ack_payload)

            with patch.object(MODULE, "utc_now", return_value=MODULE.parse_iso("2026-03-19T09:46:12Z")):
                snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))

            self.assertTrue(snapshot["directive_acknowledged"])
            refreshed = MODULE.load_case(root, "paper-a")
            directives = refreshed["control"]["directives"]["directives"]
            self.assertEqual(directives[0]["acknowledged_at"], "2026-03-19T09:46:12Z")
            ack_file = MODULE.read_json(refreshed["files"]["directive_ack"])
            self.assertEqual(ack_file["acks"][directive["id"]]["acknowledged_at"], "2026-03-19T09:46:12Z")

    def test_status_snapshot_clears_stale_directive_compliance_when_latest_report_omits_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            directive = MODULE.add_directive(
                case,
                summary="Make target-a active.",
                payload={"active_target": "target-a"},
            )["directive"]

            first = MODULE.default_directive_compliance_payload()
            first["checked_at"] = "2026-03-19T09:46:12Z"
            first["ok"] = True
            first["summary"] = "cycle1 all compliant"
            first["directives"] = {
                directive["id"]: {
                    "compliant": True,
                    "detail": "project state matches the directive",
                }
            }
            MODULE.write_json(case["files"]["directive_compliance"], first)
            first_snapshot = MODULE.status_snapshot(MODULE.load_case(root, "paper-a"))

            second = MODULE.default_directive_compliance_payload()
            second["checked_at"] = "2026-03-19T10:00:00Z"
            second["ok"] = None
            second["summary"] = "cycle2 omitted directive details"
            second["directives"] = {}
            MODULE.write_json(case["files"]["directive_compliance"], second)
            second_case = MODULE.load_case(root, "paper-a")
            second_snapshot = MODULE.status_snapshot(second_case)
            directive_record = second_case["control"]["directives"]["directives"][0]

            self.assertTrue(first_snapshot["directive_compliance"])
            self.assertIsNone(second_snapshot["directive_compliance"])
            self.assertIsNone(directive_record["project_compliance"])
            self.assertEqual(directive_record["project_compliance_checked_at"], second["checked_at"])
            self.assertEqual(directive_record["project_compliance_detail"], second["summary"])

    def test_immediate_override_interrupts_only_live_episode(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            state = case["state"]
            state["active_episode"] = {
                "thread_id": "thread-live",
                "started_at": "2026-03-19T09:00:00Z",
                "last_event_type": "response_item:reasoning",
                "pending_tool_calls": 0,
                "last_progress_at": "2026-03-19T09:30:00Z",
            }
            MODULE.save_case_state(case, state)
            case = MODULE.load_case(root, "paper-a")

            with patch.object(MODULE, "current_supervisor_pid", return_value=4242), patch.object(MODULE.os, "kill") as kill_mock:
                directive = MODULE.add_directive(
                    case,
                    summary="interrupt now",
                    payload={"active_target": "target-a"},
                    mode="override",
                    priority="high",
                    interrupt_policy="immediate",
                )["directive"]

            refreshed = MODULE.load_case(root, "paper-a")
            self.assertTrue(refreshed["state"]["interrupt_requested"])
            self.assertEqual(refreshed["state"]["interrupt_reason"], f"directive:{directive['id']}")
            kill_mock.assert_called_once_with(4242, MODULE.signal.SIGUSR1)

    def test_immediate_override_does_not_interrupt_without_active_episode(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")

            with patch.object(MODULE, "current_supervisor_pid", return_value=4242), patch.object(MODULE.os, "kill") as kill_mock:
                MODULE.add_directive(
                    case,
                    summary="queue this override",
                    payload={"active_target": "target-a"},
                    mode="override",
                    priority="high",
                    interrupt_policy="immediate",
                )

            refreshed = MODULE.load_case(root, "paper-a")
            self.assertFalse(refreshed["state"]["interrupt_requested"])
            self.assertIsNone(refreshed["state"]["interrupt_reason"])
            kill_mock.assert_not_called()

    def test_supervise_case_handles_immediate_override_before_first_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            directive = MODULE.add_directive(
                case,
                summary="queue this override",
                payload={"active_target": "target-a"},
                mode="override",
                priority="high",
                interrupt_policy="immediate",
            )["directive"]

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                snapshot = MODULE.supervise_case(MODULE.load_case(root, "paper-a"), max_cycles=1)

            prompt_text = tools["prompt_file"].read_text(encoding="utf-8")
            refreshed = MODULE.load_case(root, "paper-a")
            self.assertEqual(snapshot["status"], "completed")
            self.assertIsNone(snapshot["last_error"])
            self.assertEqual(snapshot["total_episodes"], 1)
            self.assertFalse(refreshed["state"]["interrupt_requested"])
            self.assertIsNone(refreshed["state"]["interrupt_reason"])
            self.assertIn(directive["summary"], prompt_text)

    def test_active_episode_state_updates_preserve_concurrent_control_mutations(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            case = MODULE.load_case(root, "paper-a")
            stale_state = dict(case["state"])
            current_state = MODULE.read_json(case["files"]["state"])
            current_state["stop_requested"] = True
            current_state["status"] = "stopping"
            current_state["last_cycle_note"] = "Stop requested."
            current_state["total_episodes"] = 12
            MODULE.write_json(case["files"]["state"], current_state)
            payload = {
                "thread_id": "thread-live",
                "started_at": "2026-03-19T09:00:00Z",
                "last_event_type": "response_item:reasoning",
                "pending_tool_calls": 0,
                "last_progress_at": "2026-03-19T09:30:00Z",
            }

            MODULE.update_active_episode_state(case, stale_state, payload)

            after = MODULE.read_json(case["files"]["state"])
            self.assertTrue(after["stop_requested"])
            self.assertEqual(after["status"], "stopping")
            self.assertEqual(after["last_cycle_note"], "Stop requested.")
            self.assertEqual(after["total_episodes"], 12)
            self.assertEqual(after["active_episode"], payload)
            self.assertTrue(stale_state["stop_requested"])
            self.assertEqual(stale_state["active_episode"], payload)

    def test_run_episode_honors_interrupt_requests(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            episode_state = case["state"]

            def request_interrupt() -> None:
                time.sleep(0.2)
                episode_state["interrupt_requested"] = True
                episode_state["interrupt_reason"] = "directive:interrupt-now"
                MODULE.save_case_state(case, episode_state)

            trigger = threading.Thread(target=request_interrupt, daemon=True)
            trigger.start()
            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["quiet_hang"]),
                    "FAKE_CODEX_HANG_SECONDS": "60",
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                episode = MODULE.run_episode(case, episode_state, "Keep going.\n", None)
            trigger.join(timeout=1.0)

            self.assertTrue(episode.interrupted)
            self.assertEqual(episode.interrupt_reason, "directive:interrupt-now")
            self.assertEqual(episode.returncode, 130)

    def test_supervise_case_clears_stale_interrupt_flag_before_starting_episode(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            state = case["state"]
            state["interrupt_requested"] = True
            state["interrupt_reason"] = "directive:stale"
            MODULE.save_case_state(case, state)

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                snapshot = MODULE.supervise_case(MODULE.load_case(root, "paper-a"), max_cycles=1)

            calls = [json.loads(line) for line in tools["codex_log"].read_text(encoding="utf-8").splitlines()]
            refreshed = MODULE.load_case(root, "paper-a")
            self.assertEqual([call["mode"] for call in calls], ["exec"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertIsNone(snapshot["last_error"])
            self.assertFalse(refreshed["state"]["interrupt_requested"])
            self.assertIsNone(refreshed["state"]["interrupt_reason"])

    def test_supervise_case_reports_ambiguous_session_log_recovery_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[0])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            session_root = root / "sessions"

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_CODEX_BEHAVIORS": json.dumps(["no_stdout_thread_started"]),
                    "RELAY_CODEX_SESSION_ROOT": str(session_root),
                },
                clear=False,
            ):
                with patch.object(MODULE, "changed_rollout_logs") as changed_logs_mock, patch.object(
                    MODULE,
                    "extract_thread_id_from_session_log",
                ) as extract_thread_id_mock:
                    path_a = session_root / "2026" / "03" / "19" / "rollout-a.jsonl"
                    path_b = session_root / "2026" / "03" / "19" / "rollout-b.jsonl"
                    path_a.parent.mkdir(parents=True, exist_ok=True)
                    path_a.write_text("", encoding="utf-8")
                    path_b.write_text("", encoding="utf-8")
                    changed_logs_mock.return_value = [path_a, path_b]
                    extract_thread_id_mock.side_effect = ["thread-a", "thread-b"]
                    snapshot = MODULE.supervise_case(case, max_cycles=1)

            self.assertEqual(snapshot["status"], "error")
            self.assertEqual(snapshot["last_error"], "ambiguous_thread_id_from_changed_session_logs")

    def test_supervisor_exposes_directive_paths_to_worker_and_validator(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            tools = self._fake_toolchain(root, validator_results=[1])
            self._make_case(root, validator=f"{tools['validator_bin']}")
            case = MODULE.load_case(root, "paper-a")
            MODULE.add_directive(case, summary="Keep target-a active.", payload={"active_target": "target-a"})

            with patch.dict(
                os.environ,
                {
                    "RELAY_CODEX_BIN": str(tools["codex_bin"]),
                    "FAKE_CODEX_LOG": str(tools["codex_log"]),
                    "FAKE_PROMPT_FILE": str(tools["prompt_file"]),
                    "FAKE_THREAD_COUNTER": str(tools["thread_counter"]),
                    "FAKE_VALIDATOR_COUNTER": str(tools["validator_counter"]),
                    "FAKE_VALIDATOR_LOG": str(tools["validator_log"]),
                    "FAKE_VALIDATOR_WRITES_DIRECTIVE_COMPLIANCE": "1",
                    "RELAY_CODEX_SESSION_ROOT": str(root / "sessions"),
                },
                clear=False,
            ):
                MODULE.supervise_case(MODULE.load_case(root, "paper-a"), max_cycles=1)

            worker_calls = [json.loads(line) for line in tools["codex_log"].read_text(encoding="utf-8").splitlines()]
            validator_calls = [json.loads(line) for line in tools["validator_log"].read_text(encoding="utf-8").splitlines()]
            self.assertTrue(worker_calls[0]["relay_env"]["RELAY_ACTIVE_DIRECTIVES_PATH"])
            self.assertTrue(worker_calls[0]["relay_env"]["RELAY_DIRECTIVE_ACK_PATH"])
            self.assertTrue(worker_calls[0]["relay_env"]["RELAY_NOTE_VIEW_PATH"])
            self.assertTrue(validator_calls[0]["RELAY_ACTIVE_DIRECTIVES_PATH"])
            compliance = MODULE.read_json(root / ".relay" / "paper-a" / "directive_compliance.json")
            self.assertEqual(compliance["summary"], "all active directives compliant")

    def test_parse_args_accepts_directive_subcommands_and_override(self):
        directive_args = MODULE.parse_args(
            [
                "directive",
                "--project-dir",
                ".",
                "--case",
                "paper-a",
                "add",
                "--summary",
                "prioritize",
                "--payload-json",
                "{\"active_target\": \"a\"}",
            ]
        )
        override_args = MODULE.parse_args(
            [
                "override",
                "--project-dir",
                ".",
                "--case",
                "paper-a",
                "--summary",
                "interrupt now",
            ]
        )

        self.assertEqual(directive_args.command, "directive")
        self.assertEqual(directive_args.directive_command, "add")
        self.assertEqual(override_args.command, "override")
        self.assertEqual(override_args.interrupt_policy, "immediate")

    def test_note_cli_lists_and_resolves_active_notes(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "note",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "--message",
                        "check the active hypothesis",
                        "--json",
                    ]
                )
                created = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            note_id = created["note"]["id"]

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "notes",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                    ]
                )
                rendered = stdout.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn(note_id, rendered)
            self.assertIn("check the active hypothesis", rendered)

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "note-resolve",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "--id",
                        note_id,
                        "--reason",
                        "handled",
                        "--json",
                    ]
                )
                resolved = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(resolved["status"], "resolved")
            refreshed = MODULE.load_case(root, "paper-a")
            self.assertEqual(MODULE.active_notes(refreshed), [])
            self.assertIn("No notes yet.", refreshed["files"]["inbox"].read_text(encoding="utf-8"))
            history = refreshed["files"]["note_history"].read_text(encoding="utf-8")
            self.assertIn('"event_type": "resolved"', history)

    def test_load_case_recreates_legacy_runtime_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)
            runtime = root / ".relay" / "paper-a" / "runtime"
            shutil.rmtree(runtime)

            case = MODULE.load_case(root, "paper-a")

            self.assertTrue(case["paths"]["runtime"].exists())
            self.assertTrue(case["paths"]["pid"].exists())
            self.assertTrue(case["paths"]["log"].exists())
            self.assertTrue(case["paths"]["events"].exists())
            self.assertTrue(case["paths"]["current_prompt"].exists())
            self.assertTrue(case["paths"]["last_message"].exists())

    def test_directive_cli_accepts_json_after_leaf_subcommand_and_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)

            args = MODULE.parse_args(
                [
                    "directive",
                    "--project-dir",
                    str(root),
                    "--case",
                    "paper-a",
                    "add",
                    "--summary",
                    "prioritize target-a",
                    "--payload-json",
                    "{\"active_target\": \"target-a\"}",
                    "--json",
                ]
            )
            self.assertTrue(args.json)

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "directive",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "add",
                        "--summary",
                        "prioritize target-a",
                        "--payload-json",
                        "{\"active_target\": \"target-a\"}",
                        "--json",
                    ]
                )
                created = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            directive_id = created["directive"]["id"]

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "directive",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "list",
                        "--json",
                    ]
                )
                listed = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual([item["id"] for item in listed["directives"]], [directive_id])

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "directive",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "resolve",
                        "--id",
                        directive_id,
                        "--reason",
                        "completed",
                        "--json",
                    ]
                )
                resolved = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(MODULE.list_directives(MODULE.load_case(root, "paper-a"))["directives"], [])

    def test_directive_cli_accepts_json_before_directive_subcommand(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)

            args = MODULE.parse_args(
                [
                    "directive",
                    "--json",
                    "--project-dir",
                    str(root),
                    "--case",
                    "paper-a",
                    "add",
                    "--summary",
                    "prioritize target-a",
                    "--payload-json",
                    "{\"active_target\": \"target-a\"}",
                ]
            )
            self.assertTrue(args.json)

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "directive",
                        "--json",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "add",
                        "--summary",
                        "prioritize target-a",
                        "--payload-json",
                        "{\"active_target\": \"target-a\"}",
                    ]
                )
                created = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(created["directive"]["summary"], "prioritize target-a")

    def test_directive_cli_accepts_top_level_json_before_command(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            self._make_case(root)

            args = MODULE.parse_args(
                [
                    "--json",
                    "directive",
                    "--project-dir",
                    str(root),
                    "--case",
                    "paper-a",
                    "add",
                    "--summary",
                    "prioritize target-a",
                    "--payload-json",
                    "{\"active_target\": \"target-a\"}",
                ]
            )
            self.assertTrue(args.json)

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "--json",
                        "directive",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "add",
                        "--summary",
                        "prioritize target-a",
                        "--payload-json",
                        "{\"active_target\": \"target-a\"}",
                    ]
                )
                created = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(created["directive"]["summary"], "prioritize target-a")

    def test_create_cli_accepts_top_level_json_before_command(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)

            with patch("sys.stdout", new=io.StringIO()) as stdout:
                exit_code = MODULE.main(
                    [
                        "--json",
                        "create",
                        "--project-dir",
                        str(root),
                        "--case",
                        "paper-a",
                        "--goal",
                        "replicate the paper",
                        "--validator",
                        "python3 validate.py",
                        "--duration-hours",
                        "1",
                    ]
                )
                created = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(created["case_name"], "paper-a")


if __name__ == "__main__":
    unittest.main()
