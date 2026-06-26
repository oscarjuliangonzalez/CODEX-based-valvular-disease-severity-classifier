from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import pathlib
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import textwrap
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - relay runs on POSIX, but keep import-safe behavior.
    fcntl = None


SCHEMA_VERSION = 1
DEFAULT_POLICY = {
    "episode_hard_cap_hours": 6,
    "max_episodes_per_thread": 16,
    "max_thread_age_hours": 8,
    "stall_guard_seconds": 600,
    "tool_call_stall_seconds": 180,
    "liveness_poll_seconds": 5,
}
DEFAULT_CODEX_EXEC_ARGS = ["--dangerously-bypass-approvals-and-sandbox"]
FULL_AUTO_FLAG = "--full-auto"
FULL_ACCESS_FLAG = "--dangerously-bypass-approvals-and-sandbox"

CASE_FILE = "case.json"
MISSION_FILE = "mission.md"
LOGBOOK_FILE = "logbook.md"
INBOX_FILE = "inbox.md"
NOTES_FILE = "notes.json"
NOTE_HISTORY_FILE = "note_history.jsonl"
DIRECTIVES_FILE = "directives.json"
DIRECTIVE_HISTORY_FILE = "directive_history.jsonl"
DIRECTIVE_ACK_FILE = "directive_ack.json"
DIRECTIVE_COMPLIANCE_FILE = "directive_compliance.json"
LEDGER_FILE = "ledger.jsonl"
STATE_FILE = "state.json"
RUNTIME_DIR = "runtime"
STATE_LOCK_FILE = "state.lock"
PID_FILE = "pid"
SUPERVISOR_METADATA_FILE = "supervisor.json"
SUPERVISOR_LOG_FILE = "supervisor.log"
EVENTS_FILE = "codex-events.jsonl"
CURRENT_PROMPT_FILE = "current_prompt.txt"
LAST_MESSAGE_FILE = "last_message.txt"

CASE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ISO_Z_RE = re.compile(r"Z$")
LOGBOOK_TITLE = "# Logbook"
LOGBOOK_SUPERVISOR_HEADER = "## Supervisor Status"
LOGBOOK_WORKER_HEADER = "## Worker Notes"
LOGBOOK_LEGACY_SUPERVISOR_PREFIXES = (
    "Status:",
    "Stop requested:",
    "Interrupt requested:",
    "Current thread:",
    "Current thread episodes:",
    "Total episodes:",
    "Last validator ok:",
    "Last validator exit code:",
    "Active directives:",
    "Active notes:",
    "Last stalled episode:",
    "Last interrupted episode:",
    "Active episode thread:",
    "Active episode last event:",
    "Active episode pending tool calls:",
    "Last error:",
    "Next action:",
)


@dataclasses.dataclass
class EpisodeResult:
    returncode: int
    timed_out: bool
    interrupted: bool
    interrupt_reason: str | None
    completion_guard_triggered: bool
    stalled_guard_triggered: bool
    stall_reason: str | None
    stdout: str
    stderr: str
    thread_id: str | None
    started_at: str
    finished_at: str
    command: list[str]
    prompt: str
    prompt_path: str
    last_message: str
    session_log_path: str | None
    last_event_type: str | None
    pending_tool_calls: int
    last_progress_at: str
    thread_resolution_error: str | None


@dataclasses.dataclass
class SessionTracker:
    thread_id: str | None = None
    path: pathlib.Path | None = None
    offset: int = 0
    last_event_type: str | None = None
    pending_tool_calls: dict[str, str] = dataclasses.field(default_factory=dict)
    episode_session_snapshot: dict[pathlib.Path, tuple[int, int]] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ValidationResult:
    returncode: int
    stdout: str
    stderr: str
    passed: bool
    started_at: str
    finished_at: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    cleaned = ISO_Z_RE.sub("+00:00", text)
    value = datetime.fromisoformat(cleaned)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def read_text(path: pathlib.Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: pathlib.Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: Any) -> None:
    write_text(path, to_json_text(payload))


def append_jsonl(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


@contextlib.contextmanager
def file_lock(path: pathlib.Path) -> Iterable[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_case_name(case_name: str) -> str:
    if not CASE_NAME_RE.match(case_name):
        raise ValueError(f"invalid case name: {case_name!r}")
    return case_name


def unique_keep_order(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_codex_exec_args(args: Iterable[str] | str | None = None) -> list[str]:
    raw_args: list[str]
    if isinstance(args, str):
        raw_args = [args]
    elif args:
        raw_args = [str(item).strip() for item in args if str(item).strip()]
    else:
        raw_args = []
    normalized = unique_keep_order([*DEFAULT_CODEX_EXEC_ARGS, *raw_args])
    if FULL_ACCESS_FLAG in normalized:
        normalized = [item for item in normalized if item != FULL_AUTO_FLAG]
    return normalized


def ensure_case_config_defaults(config: dict[str, Any]) -> bool:
    changed = False
    codex_exec_args = normalize_codex_exec_args(config.get("codex_exec_args"))
    if config.get("codex_exec_args") != codex_exec_args:
        config["codex_exec_args"] = codex_exec_args
        changed = True
    return changed


def project_root_path(project_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(project_dir).resolve()


def relay_root(project_root: pathlib.Path) -> pathlib.Path:
    return project_root / ".relay"


def case_dir(project_root: pathlib.Path, case_name: str) -> pathlib.Path:
    return relay_root(project_root) / validate_case_name(case_name)


def case_state_lock_path(case: dict[str, Any]) -> pathlib.Path:
    state_lock = (case.get("files") or {}).get("state_lock")
    if state_lock is not None:
        return state_lock
    return pathlib.Path(case["case_dir"]) / STATE_LOCK_FILE


def runtime_paths(case_path: pathlib.Path) -> dict[str, pathlib.Path]:
    runtime = case_path / RUNTIME_DIR
    return {
        "runtime": runtime,
        "pid": runtime / PID_FILE,
        "supervisor_meta": runtime / SUPERVISOR_METADATA_FILE,
        "log": runtime / SUPERVISOR_LOG_FILE,
        "events": runtime / EVENTS_FILE,
        "current_prompt": runtime / CURRENT_PROMPT_FILE,
        "last_message": runtime / LAST_MESSAGE_FILE,
    }


def ensure_runtime_paths(paths: dict[str, pathlib.Path]) -> None:
    paths["runtime"].mkdir(parents=True, exist_ok=True)
    for key in ("pid", "log", "events", "current_prompt", "last_message"):
        paths[key].touch(exist_ok=True)


def compute_deadline(deadline: str | None, duration_hours: float | None, duration_days: float | None) -> str | None:
    if deadline:
        parse_iso(deadline)
        return deadline
    if duration_days is not None:
        return (utc_now() + timedelta(days=float(duration_days))).isoformat().replace("+00:00", "Z")
    if duration_hours is not None:
        return (utc_now() + timedelta(hours=float(duration_hours))).isoformat().replace("+00:00", "Z")
    return None


def compute_expiration(expires_at: str | None = None, expires_hours: float | None = None) -> str | None:
    if expires_at:
        parse_iso(expires_at)
        return expires_at
    if expires_hours is not None:
        return (utc_now() + timedelta(hours=float(expires_hours))).isoformat().replace("+00:00", "Z")
    return None


def load_payload_json(*, payload_json: str | None = None, payload_file: str | None = None) -> dict[str, Any]:
    if payload_file:
        payload = json.loads(pathlib.Path(payload_file).read_text(encoding="utf-8"))
    elif payload_json:
        payload = json.loads(payload_json)
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("directive payload must decode to a JSON object")
    return payload


def default_case_payload(
    *,
    project_root: pathlib.Path,
    case_name: str,
    goal: str,
    validator: str,
    skills: list[str],
    deadline: str | None,
    policy_overrides: dict[str, Any] | None = None,
    codex_exec_args: Iterable[str] = (),
) -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY)
    if policy_overrides:
        policy.update(policy_overrides)
    return {
        "schema_version": SCHEMA_VERSION,
        "case_name": case_name,
        "project_root": str(project_root),
        "created_at": iso_now(),
        "goal": goal,
        "validator": validator,
        "deadline": deadline,
        "skills": skills,
        "codex_exec_args": normalize_codex_exec_args(codex_exec_args),
        "policy": policy,
        "resume_policy": {
            "max_episodes_per_thread": policy["max_episodes_per_thread"],
            "max_thread_age_hours": policy["max_thread_age_hours"],
        },
    }


def initial_state(deadline: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "idle",
        "stop_requested": False,
        "interrupt_requested": False,
        "interrupt_reason": None,
        "deadline": deadline,
        "current_thread_id": None,
        "current_thread_started_at": None,
        "current_thread_episode_count": 0,
        "total_episodes": 0,
        "last_episode_started_at": None,
        "last_episode_finished_at": None,
        "last_episode_exit_code": None,
        "last_episode_timed_out": False,
        "last_validator_exit_code": None,
        "last_validator_ok": None,
        "last_validator_started_at": None,
        "last_validator_finished_at": None,
        "last_error": None,
        "completed_at": None,
        "thread_history": [],
        "current_rollover_reason": None,
        "last_cycle_note": None,
        "active_episode": None,
        "last_episode_stalled": False,
        "last_episode_stall_reason": None,
        "last_episode_interrupted": False,
        "last_episode_interrupt_reason": None,
    }


def default_state_payload(case: dict[str, Any]) -> dict[str, Any]:
    return initial_state((case.get("config") or {}).get("deadline"))


def mission_text(payload: dict[str, Any]) -> str:
    skills = payload.get("skills") or []
    deadline = payload.get("deadline") or "none"
    skill_text = ", ".join(skills) if skills else "none"
    case_name = payload.get("case_name", "<case>")
    return textwrap.dedent(
        f"""\
        # Mission

        Goal: {payload.get("goal", "")}
        Validator: `{payload.get("validator", "")}`
        Deadline: {deadline}
        Skills: {skill_text}

        Stop only when the validator passes, the deadline arrives, or a stop request is present.
        Keep progress in repo files and the `## Worker Notes` section of `.relay/{case_name}/logbook.md`.
        Active directives are authoritative. Notes are advisory.
        Do not edit `case.json`, `state.json`, `notes.json`, `note_history.jsonl`, `directives.json`, `directive_history.jsonl`, `directive_compliance.json`, `inbox.md`, `ledger.jsonl`, or anything under `runtime/`.
        The worker may update `logbook.md` and `directive_ack.json` inside the relay case.
        Each directive acknowledgment should include `acknowledged_at`, `status`, and `reason`; use the current UTC time for `acknowledged_at`.
        Let the run end naturally. Relay will checkpoint after the worker exits or the hard cap is reached.
        """
    ).strip() + "\n"


def default_worker_notes_text() -> str:
    return textwrap.dedent(
        """\
        Keep this section short and durable.
        - Active target:
        - Changes this cycle:
        - Blocker:
        - Exact next action:
        - Cluster / run ids:
        """
    ).rstrip()


def extract_worker_notes(text: str) -> str | None:
    marker = f"{LOGBOOK_WORKER_HEADER}\n"
    if marker in text:
        _, _, worker_body = text.partition(marker)
        return worker_body.strip("\n")
    if text.rstrip().endswith(LOGBOOK_WORKER_HEADER):
        return ""
    return None


def extract_legacy_worker_notes(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != LOGBOOK_TITLE:
        return None
    worker_lines: list[str] = []
    for raw_line in lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            if worker_lines:
                worker_lines.append("")
            continue
        if raw_line.startswith("## "):
            continue
        if stripped == LOGBOOK_TITLE:
            continue
        if any(stripped.startswith(prefix) for prefix in LOGBOOK_LEGACY_SUPERVISOR_PREFIXES):
            continue
        worker_lines.append(raw_line)
    while worker_lines and not worker_lines[0].strip():
        worker_lines.pop(0)
    while worker_lines and not worker_lines[-1].strip():
        worker_lines.pop()
    if not worker_lines:
        return None
    return "\n".join(worker_lines)


def persisted_worker_notes_text(existing_logbook: str) -> str:
    worker_notes = extract_worker_notes(existing_logbook)
    if worker_notes is None:
        worker_notes = extract_legacy_worker_notes(existing_logbook)
    if worker_notes is None:
        return default_worker_notes_text()
    normalized = worker_notes.strip("\n")
    return normalized if normalized else default_worker_notes_text()


def logbook_text(
    case: dict[str, Any],
    state: dict[str, Any],
    note: str | None = None,
    worker_notes: str | None = None,
) -> str:
    active_episode = state.get("active_episode") or {}
    control = case.get("control") or {}
    directives = (control.get("directives") or {}).get("directives") or []
    notes = (control.get("notes") or {}).get("notes") or []
    lines = [
        LOGBOOK_TITLE,
        "",
        LOGBOOK_SUPERVISOR_HEADER,
        "",
        f"Status: {state.get('status', 'idle')}",
        f"Stop requested: {state.get('stop_requested', False)}",
        f"Interrupt requested: {state.get('interrupt_requested', False)}",
        f"Current thread: {state.get('current_thread_id') or 'none'}",
        f"Current thread episodes: {state.get('current_thread_episode_count', 0)}",
        f"Total episodes: {state.get('total_episodes', 0)}",
        f"Last validator ok: {state.get('last_validator_ok')}",
        f"Last validator exit code: {state.get('last_validator_exit_code')}",
    ]
    if directives:
        directive_ids = ", ".join(directive["id"] for directive in directives)
        lines.append(f"Active directives: {directive_ids}")
    else:
        lines.append("Active directives: none")
    lines.append(f"Active notes: {len(notes)}")
    if state.get("last_episode_stalled"):
        lines.append(f"Last stalled episode: {state.get('last_episode_stall_reason') or 'unknown'}")
    if state.get("last_episode_interrupted"):
        lines.append(f"Last interrupted episode: {state.get('last_episode_interrupt_reason') or 'unknown'}")
    if active_episode:
        lines.append(f"Active episode thread: {active_episode.get('thread_id') or 'pending'}")
        lines.append(f"Active episode last event: {active_episode.get('last_event_type') or 'none'}")
        lines.append(f"Active episode pending tool calls: {active_episode.get('pending_tool_calls', 0)}")
    if state.get("last_error"):
        lines.append(f"Last error: {state['last_error']}")
    if note:
        lines.extend(["", f"Next action: {note}"])
    effective_worker_notes = worker_notes if worker_notes is not None else default_worker_notes_text()
    lines.extend(
        [
            "",
            LOGBOOK_WORKER_HEADER,
            "",
            effective_worker_notes.rstrip(),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def default_notes_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": iso_now(),
        "notes": [],
    }


def default_directives_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": iso_now(),
        "directives": [],
    }


def default_directive_ack_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "acks": {},
    }


def normalize_directive_ack(
    ack: Any,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(ack, dict):
        return None, False
    current = now or utc_now()
    normalized = dict(ack)
    changed = False

    acknowledgment_status = normalized.get("status")
    if isinstance(acknowledgment_status, str):
        cleaned = acknowledgment_status.strip()
        if cleaned != acknowledgment_status:
            changed = True
        acknowledgment_status = cleaned or None
    elif acknowledgment_status is not None:
        acknowledgment_status = str(acknowledgment_status).strip() or None
        changed = True

    acknowledgment_reason = normalized.get("reason")
    if isinstance(acknowledgment_reason, str):
        cleaned = acknowledgment_reason.strip()
        if cleaned != acknowledgment_reason:
            changed = True
        acknowledgment_reason = cleaned or None
    elif acknowledgment_reason is not None:
        acknowledgment_reason = str(acknowledgment_reason).strip() or None
        changed = True

    raw_acknowledged_at = normalized.get("acknowledged_at")
    parsed_acknowledged_at: datetime | None = None
    if isinstance(raw_acknowledged_at, str):
        cleaned = raw_acknowledged_at.strip()
        if cleaned != raw_acknowledged_at:
            changed = True
        raw_acknowledged_at = cleaned or None
        if raw_acknowledged_at:
            with contextlib.suppress(ValueError):
                parsed_acknowledged_at = parse_iso(raw_acknowledged_at)
    elif raw_acknowledged_at:
        changed = True

    attempted_ack = bool(raw_acknowledged_at or acknowledgment_status or acknowledgment_reason)
    if not attempted_ack:
        return normalized, changed

    if not acknowledgment_status:
        acknowledgment_status = "acknowledged"
        changed = True

    if parsed_acknowledged_at is None or parsed_acknowledged_at > current:
        parsed_acknowledged_at = current
        changed = True

    normalized["acknowledged_at"] = iso_utc(parsed_acknowledged_at)
    normalized["status"] = acknowledgment_status
    if acknowledgment_reason is None:
        normalized.pop("reason", None)
    else:
        normalized["reason"] = acknowledgment_reason
    return normalized, changed


def default_directive_compliance_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at": None,
        "ok": None,
        "summary": "",
        "directives": {},
    }


def next_control_id(prefix: str) -> str:
    return f"{prefix}-{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}"


def render_inbox_from_notes(notes: list[dict[str, Any]]) -> str:
    active = [note for note in notes if note.get("status") == "active"]
    if not active:
        return "# Inbox\n\nNo notes yet.\n"
    lines = ["# Inbox", ""]
    for note in active:
        message = str(note.get("message") or "").strip()
        lines.append(f"- [{note['id']}] {note['created_at']}: {message}")
        if note.get("expires_at"):
            lines.append(f"  expires_at: {note['expires_at']}")
    return "\n".join(lines).rstrip() + "\n"


def parse_legacy_inbox_notes(text: str) -> list[dict[str, Any]]:
    body = text.strip()
    if not body or body == "# Inbox\n\nNo notes yet.":
        return []
    lines = body.splitlines()
    if lines and lines[0].strip() == "# Inbox":
        lines = lines[1:]
    entries: list[list[str]] = []
    current: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            if current:
                current.append("")
            continue
        if line.startswith("- "):
            if current:
                entries.append(current)
            current = [line[2:]]
            continue
        if current:
            current.append(line)
    if current:
        entries.append(current)

    notes: list[dict[str, Any]] = []
    for entry in entries:
        first = entry[0]
        timestamp = iso_now()
        message = first
        match = re.match(r"^(?P<created_at>\d{4}-\d{2}-\d{2}T[^:]+:[^:]+:[^:]+Z):\s*(?P<message>.*)$", first)
        if match:
            timestamp = match.group("created_at")
            message = match.group("message")
        remainder = "\n".join(part for part in entry[1:] if part is not None).strip()
        if remainder:
            message = f"{message}\n{remainder}".strip()
        notes.append(
            {
                "id": next_control_id("note"),
                "created_at": timestamp,
                "message": message.strip(),
                "expires_at": None,
                "status": "active",
            }
        )
    return notes


def control_history_event(*, item_type: str, event_type: str, item_id: str, payload: dict[str, Any] | None = None, reason: str | None = None) -> dict[str, Any]:
    event = {
        "at": iso_now(),
        "item_type": item_type,
        "event_type": event_type,
        "item_id": item_id,
    }
    if reason:
        event["reason"] = reason
    if payload is not None:
        event["payload"] = payload
    return event


def item_expired(item: dict[str, Any], *, now: datetime | None = None) -> bool:
    expires_at = parse_iso(item.get("expires_at"))
    if not expires_at:
        return False
    current = now or utc_now()
    return current >= expires_at


def apply_directive_acknowledgments(
    directives_payload: dict[str, Any],
    ack_payload: dict[str, Any],
    history_path: pathlib.Path,
) -> bool:
    changed = False
    ack_map = dict(ack_payload.get("acks") or {})
    if not ack_map:
        return changed
    current = utc_now()
    for directive in directives_payload.get("directives") or []:
        ack = ack_map.get(directive["id"])
        normalized_ack, ack_changed = normalize_directive_ack(ack, now=current)
        if ack_changed:
            if normalized_ack is None:
                ack_map.pop(directive["id"], None)
            else:
                ack_map[directive["id"]] = normalized_ack
            ack_payload["acks"] = ack_map
            ack_payload["updated_at"] = iso_utc(current)
            changed = True
        if not isinstance(normalized_ack, dict):
            continue
        acknowledged_at = normalized_ack.get("acknowledged_at")
        acknowledgment_status = normalized_ack.get("status")
        acknowledgment_reason = normalized_ack.get("reason")
        if directive.get("acknowledged_at") == acknowledged_at and directive.get("acknowledgment_status") == acknowledgment_status and directive.get("acknowledgment_reason") == acknowledgment_reason:
            continue
        directive["acknowledged_at"] = acknowledged_at
        directive["acknowledgment_status"] = acknowledgment_status
        directive["acknowledgment_reason"] = acknowledgment_reason
        append_jsonl(
            history_path,
            control_history_event(
                item_type="directive",
                event_type="acknowledged",
                item_id=directive["id"],
                payload={
                    "acknowledged_at": acknowledged_at,
                    "status": acknowledgment_status,
                    "reason": acknowledgment_reason,
                },
            ),
        )
        changed = True
    return changed


def apply_directive_compliance(
    directives_payload: dict[str, Any],
    compliance_payload: dict[str, Any],
    history_path: pathlib.Path,
) -> bool:
    changed = False
    compliance_map = dict(compliance_payload.get("directives") or {})
    checked_at = compliance_payload.get("checked_at")
    summary = compliance_payload.get("summary")
    has_report = (
        checked_at is not None
        or bool(summary)
        or bool(compliance_map)
        or compliance_payload.get("ok") is not None
    )
    if not has_report:
        return changed
    for directive in directives_payload.get("directives") or []:
        report = compliance_map.get(directive["id"])
        if isinstance(report, dict):
            compliant = report.get("compliant")
            detail = report.get("detail")
        else:
            compliant = None
            detail = None
        if (
            directive.get("project_compliance") == compliant
            and directive.get("project_compliance_checked_at") == checked_at
            and directive.get("project_compliance_detail") == (detail or summary)
        ):
            continue
        directive["project_compliance"] = compliant
        directive["project_compliance_checked_at"] = checked_at
        directive["project_compliance_detail"] = detail or summary
        append_jsonl(
            history_path,
            control_history_event(
                item_type="directive",
                event_type="compliance",
                item_id=directive["id"],
                payload={
                    "checked_at": checked_at,
                    "compliant": compliant,
                    "detail": detail or summary,
                },
            ),
        )
        changed = True
    return changed


def expire_notes(notes_payload: dict[str, Any], history_path: pathlib.Path, *, now: datetime | None = None) -> bool:
    changed = False
    active_notes = []
    for note in notes_payload.get("notes") or []:
        if item_expired(note, now=now):
            append_jsonl(
                history_path,
                control_history_event(item_type="note", event_type="expired", item_id=note["id"], payload=note),
            )
            changed = True
            continue
        active_notes.append(note)
    if changed:
        notes_payload["notes"] = active_notes
        notes_payload["updated_at"] = iso_now()
    return changed


def expire_directives(directives_payload: dict[str, Any], history_path: pathlib.Path, *, now: datetime | None = None) -> bool:
    changed = False
    active_directives = []
    for directive in directives_payload.get("directives") or []:
        if item_expired(directive, now=now):
            append_jsonl(
                history_path,
                control_history_event(item_type="directive", event_type="expired", item_id=directive["id"], payload=directive),
            )
            changed = True
            continue
        active_directives.append(directive)
    if changed:
        directives_payload["directives"] = active_directives
        directives_payload["updated_at"] = iso_now()
    return changed


def ensure_control_plane(case: dict[str, Any]) -> dict[str, Any]:
    changed = False
    notes_path = case["files"]["notes"]
    note_history_path = case["files"]["note_history"]
    directives_path = case["files"]["directives"]
    directive_history_path = case["files"]["directive_history"]
    directive_ack_path = case["files"]["directive_ack"]
    directive_compliance_path = case["files"]["directive_compliance"]

    notes_payload = read_json(notes_path)
    if not isinstance(notes_payload, dict):
        legacy_notes = parse_legacy_inbox_notes(read_text(case["files"]["inbox"]))
        notes_payload = default_notes_payload()
        notes_payload["notes"] = legacy_notes
        for note in legacy_notes:
            append_jsonl(
                note_history_path,
                control_history_event(item_type="note", event_type="migrated", item_id=note["id"], payload=note),
            )
        changed = True

    directives_payload = read_json(directives_path)
    if not isinstance(directives_payload, dict):
        directives_payload = default_directives_payload()
        changed = True

    ack_payload = read_json(directive_ack_path)
    if not isinstance(ack_payload, dict):
        ack_payload = default_directive_ack_payload()
        changed = True

    compliance_payload = read_json(directive_compliance_path)
    if not isinstance(compliance_payload, dict):
        compliance_payload = default_directive_compliance_payload()
        changed = True

    if expire_notes(notes_payload, note_history_path):
        changed = True
    if expire_directives(directives_payload, directive_history_path):
        changed = True
    if apply_directive_acknowledgments(directives_payload, ack_payload, directive_history_path):
        directives_payload["updated_at"] = iso_now()
        changed = True
    if apply_directive_compliance(directives_payload, compliance_payload, directive_history_path):
        directives_payload["updated_at"] = iso_now()
        changed = True

    rendered_inbox = render_inbox_from_notes(notes_payload.get("notes") or [])
    if read_text(case["files"]["inbox"]) != rendered_inbox:
        write_text(case["files"]["inbox"], rendered_inbox)

    if changed or not notes_path.exists():
        write_json(notes_path, notes_payload)
    if changed or not directives_path.exists():
        write_json(directives_path, directives_payload)
    if changed or not directive_ack_path.exists():
        write_json(directive_ack_path, ack_payload)
    if changed or not directive_compliance_path.exists():
        write_json(directive_compliance_path, compliance_payload)

    note_history_path.touch(exist_ok=True)
    directive_history_path.touch(exist_ok=True)

    case["control"] = {
        "notes": notes_payload,
        "directives": directives_payload,
        "directive_ack": ack_payload,
        "directive_compliance": compliance_payload,
    }
    return case


def read_ledger_tail(case_path: pathlib.Path, limit: int = 5) -> str:
    ledger_path = case_path / LEDGER_FILE
    if not ledger_path.exists():
        return ""
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return ""
    return "\n".join(lines[-limit:])


def create_case(
    *,
    project_dir: str | pathlib.Path,
    case_name: str,
    goal: str,
    validator: str,
    skills: Iterable[str] = (),
    deadline: str | None = None,
    duration_hours: float | None = None,
    duration_days: float | None = None,
    policy_overrides: dict[str, Any] | None = None,
    codex_exec_args: Iterable[str] = (),
) -> dict[str, Any]:
    project_root = project_root_path(project_dir)
    case_name = validate_case_name(case_name)
    effective_deadline = compute_deadline(deadline, duration_hours, duration_days)
    case_path = case_dir(project_root, case_name)
    paths = runtime_paths(case_path)
    skill_list = unique_keep_order(list(skills))

    project_root.mkdir(parents=True, exist_ok=True)
    case_path.mkdir(parents=True, exist_ok=True)
    ensure_runtime_paths(paths)

    config_path = case_path / CASE_FILE
    state_path = case_path / STATE_FILE
    mission_path = case_path / MISSION_FILE
    logbook_path = case_path / LOGBOOK_FILE
    inbox_path = case_path / INBOX_FILE
    notes_path = case_path / NOTES_FILE
    note_history_path = case_path / NOTE_HISTORY_FILE
    directives_path = case_path / DIRECTIVES_FILE
    directive_history_path = case_path / DIRECTIVE_HISTORY_FILE
    directive_ack_path = case_path / DIRECTIVE_ACK_FILE
    directive_compliance_path = case_path / DIRECTIVE_COMPLIANCE_FILE
    ledger_path = case_path / LEDGER_FILE

    created = not config_path.exists()
    if created:
        config = default_case_payload(
            project_root=project_root,
            case_name=case_name,
            goal=goal,
            validator=validator,
            skills=skill_list,
            deadline=effective_deadline,
            policy_overrides=policy_overrides,
            codex_exec_args=codex_exec_args,
        )
        state = initial_state(effective_deadline)
        write_json(config_path, config)
        write_json(state_path, state)
        write_text(mission_path, mission_text(config))
        bootstrap_case = {
            "config": config,
            "control": {
                "notes": default_notes_payload(),
                "directives": default_directives_payload(),
            },
        }
        write_text(logbook_path, logbook_text(bootstrap_case, state, "Create the case and start the first cycle."))
        write_json(notes_path, default_notes_payload())
        note_history_path.touch(exist_ok=True)
        write_text(inbox_path, render_inbox_from_notes([]))
        write_json(directives_path, default_directives_payload())
        directive_history_path.touch(exist_ok=True)
        write_json(directive_ack_path, default_directive_ack_payload())
        write_json(directive_compliance_path, default_directive_compliance_payload())
        ledger_path.touch(exist_ok=True)
    else:
        config = read_json(config_path)
        if ensure_case_config_defaults(config):
            write_json(config_path, config)
        state = read_json(state_path, initial_state(config.get("deadline")))

    return {
        "created": created,
        "project_root": str(project_root),
        "case_name": case_name,
        "case_dir": str(case_path),
        "config": config,
        "state": state,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def load_case(project_dir: str | pathlib.Path, case_name: str) -> dict[str, Any]:
    project_root = project_root_path(project_dir)
    case_path = case_dir(project_root, case_name)
    config_path = case_path / CASE_FILE
    state_path = case_path / STATE_FILE
    if not config_path.exists() or not state_path.exists():
        raise FileNotFoundError(f"missing relay case: {case_name}")
    config = read_json(config_path)
    if ensure_case_config_defaults(config):
        write_json(config_path, config)
    state = read_json(state_path)
    mission_path = case_path / MISSION_FILE
    desired_mission = mission_text(config)
    if read_text(mission_path) != desired_mission:
        write_text(mission_path, desired_mission)
    paths = runtime_paths(case_path)
    ensure_runtime_paths(paths)
    case = {
        "project_root": project_root,
        "case_name": validate_case_name(case_name),
        "case_dir": case_path,
        "config": config,
        "state": state,
        "paths": paths,
        "files": {
            "config": config_path,
            "state": state_path,
            "state_lock": case_path / STATE_LOCK_FILE,
            "mission": mission_path,
            "logbook": case_path / LOGBOOK_FILE,
            "inbox": case_path / INBOX_FILE,
            "notes": case_path / NOTES_FILE,
            "note_history": case_path / NOTE_HISTORY_FILE,
            "directives": case_path / DIRECTIVES_FILE,
            "directive_history": case_path / DIRECTIVE_HISTORY_FILE,
            "directive_ack": case_path / DIRECTIVE_ACK_FILE,
            "directive_compliance": case_path / DIRECTIVE_COMPLIANCE_FILE,
            "ledger": case_path / LEDGER_FILE,
        },
    }
    return ensure_control_plane(case)


def refresh_case_config(case: dict[str, Any]) -> dict[str, Any]:
    config = read_json(case["files"]["config"], case["config"])
    case["config"] = config
    desired_mission = mission_text(config)
    if read_text(case["files"]["mission"]) != desired_mission:
        write_text(case["files"]["mission"], desired_mission)
    return ensure_control_plane(case)


def _write_case_state(case: dict[str, Any], state: dict[str, Any]) -> None:
    write_json(case["files"]["state"], state)
    case["state"] = state


def save_case_state(case: dict[str, Any], state: dict[str, Any]) -> None:
    with file_lock(case_state_lock_path(case)):
        _write_case_state(case, state)


def mutate_case_state(case: dict[str, Any], mutator: Any) -> dict[str, Any]:
    with file_lock(case_state_lock_path(case)):
        state = read_json(case["files"]["state"], default_state_payload(case))
        mutator(state)
        _write_case_state(case, state)
    return state


def update_active_episode_state(case: dict[str, Any], state: dict[str, Any], payload: dict[str, Any] | None) -> None:
    with file_lock(case_state_lock_path(case)):
        current = read_json(case["files"]["state"], default_state_payload(case))
        if not isinstance(current, dict):
            current = default_state_payload(case)
        current["active_episode"] = payload
        _write_case_state(case, current)
    state.clear()
    state.update(current)


def update_logbook(case: dict[str, Any], state: dict[str, Any], note: str | None = None) -> None:
    existing_logbook = read_text(case["files"]["logbook"])
    worker_notes = persisted_worker_notes_text(existing_logbook)
    write_text(case["files"]["logbook"], logbook_text(case, state, note, worker_notes=worker_notes))


def save_notes_payload(case: dict[str, Any], notes_payload: dict[str, Any]) -> None:
    notes_payload["updated_at"] = iso_now()
    write_json(case["files"]["notes"], notes_payload)
    write_text(case["files"]["inbox"], render_inbox_from_notes(notes_payload.get("notes") or []))
    if "control" not in case:
        case["control"] = {}
    case["control"]["notes"] = notes_payload


def save_directives_payload(case: dict[str, Any], directives_payload: dict[str, Any]) -> None:
    directives_payload["updated_at"] = iso_now()
    write_json(case["files"]["directives"], directives_payload)
    if "control" not in case:
        case["control"] = {}
    case["control"]["directives"] = directives_payload


def append_note(case: dict[str, Any], message: str, *, expires_at: str | None = None) -> dict[str, Any]:
    if expires_at:
        parse_iso(expires_at)
    case = ensure_control_plane(case)
    notes_payload = case["control"]["notes"]
    note_message = message.strip()
    note = {
        "id": next_control_id("note"),
        "created_at": iso_now(),
        "message": note_message,
        "expires_at": expires_at,
        "status": "active",
    }
    notes_payload.setdefault("notes", []).append(note)
    save_notes_payload(case, notes_payload)
    append_jsonl(
        case["files"]["note_history"],
        control_history_event(item_type="note", event_type="created", item_id=note["id"], payload=note),
    )
    case = ensure_control_plane(case)
    state = mutate_case_state(case, lambda current: current.__setitem__("last_cycle_note", note_message))
    update_logbook(case, state, "Apply the inbox note on the next cycle.")
    return {"case_name": case["case_name"], "note": note, "inbox": read_text(case["files"]["inbox"])}


def active_notes(case: dict[str, Any]) -> list[dict[str, Any]]:
    case = ensure_control_plane(case)
    return list((case["control"]["notes"].get("notes") or []))


def archive_note(
    case: dict[str, Any],
    note_id: str,
    *,
    event_type: str,
    reason: str | None = None,
) -> dict[str, Any]:
    case = ensure_control_plane(case)
    notes_payload = case["control"]["notes"]
    active = notes_payload.get("notes") or []
    kept: list[dict[str, Any]] = []
    archived: dict[str, Any] | None = None
    for note in active:
        if note["id"] != note_id:
            kept.append(note)
            continue
        archived = dict(note)
        append_jsonl(
            case["files"]["note_history"],
            control_history_event(
                item_type="note",
                event_type=event_type,
                item_id=note_id,
                payload=archived,
                reason=reason,
            ),
        )
    if archived is None:
        raise ValueError(f"unknown note id: {note_id}")
    notes_payload["notes"] = kept
    save_notes_payload(case, notes_payload)
    update_logbook(case, case["state"], case["state"].get("last_cycle_note"))
    return archived


def active_directives(case: dict[str, Any]) -> list[dict[str, Any]]:
    case = ensure_control_plane(case)
    return list((case["control"]["directives"].get("directives") or []))


def archive_directive(
    case: dict[str, Any],
    directive_id: str,
    *,
    event_type: str,
    reason: str | None = None,
    replacement_id: str | None = None,
) -> dict[str, Any]:
    case = ensure_control_plane(case)
    directives_payload = case["control"]["directives"]
    active = directives_payload.get("directives") or []
    kept: list[dict[str, Any]] = []
    archived: dict[str, Any] | None = None
    for directive in active:
        if directive["id"] != directive_id:
            kept.append(directive)
            continue
        archived = dict(directive)
        if replacement_id:
            archived["replacement_id"] = replacement_id
        append_jsonl(
            case["files"]["directive_history"],
            control_history_event(
                item_type="directive",
                event_type=event_type,
                item_id=directive_id,
                payload=archived,
                reason=reason,
            ),
        )
    if archived is None:
        raise ValueError(f"unknown directive id: {directive_id}")
    directives_payload["directives"] = kept
    save_directives_payload(case, directives_payload)
    update_logbook(case, case["state"], case["state"].get("last_cycle_note"))
    return archived


def add_directive(
    case: dict[str, Any],
    *,
    summary: str,
    payload: dict[str, Any],
    mode: str = "directive",
    priority: str = "normal",
    interrupt_policy: str = "none",
    supersedes: Iterable[str] = (),
    expires_at: str | None = None,
) -> dict[str, Any]:
    case = ensure_control_plane(case)
    directives_payload = case["control"]["directives"]
    directive = {
        "id": next_control_id("directive"),
        "created_at": iso_now(),
        "mode": mode,
        "priority": priority,
        "interrupt_policy": interrupt_policy,
        "supersedes": list(unique_keep_order(supersedes)),
        "expires_at": expires_at,
        "summary": summary.strip(),
        "payload": payload,
        "status": "active",
        "acknowledged_at": None,
        "acknowledgment_status": None,
        "acknowledgment_reason": None,
        "project_compliance": None,
        "project_compliance_checked_at": None,
        "project_compliance_detail": None,
    }
    for superseded_id in directive["supersedes"]:
        archive_directive(
            case,
            superseded_id,
            event_type="superseded",
            reason=f"Superseded by {directive['id']}",
            replacement_id=directive["id"],
        )
        case = ensure_control_plane(case)
        directives_payload = case["control"]["directives"]
    directives_payload.setdefault("directives", []).append(directive)
    save_directives_payload(case, directives_payload)
    append_jsonl(
        case["files"]["directive_history"],
        control_history_event(item_type="directive", event_type="created", item_id=directive["id"], payload=directive),
    )
    case = ensure_control_plane(case)
    should_interrupt = False

    def update_state(current: dict[str, Any]) -> None:
        nonlocal should_interrupt
        current["last_cycle_note"] = summary.strip()
        if interrupt_policy == "immediate" and current.get("active_episode"):
            current["interrupt_requested"] = True
            current["interrupt_reason"] = f"directive:{directive['id']}"
            should_interrupt = True

    state = mutate_case_state(case, update_state)
    update_logbook(case, state, "Apply the active directive on the next cycle.")
    if should_interrupt and hasattr(signal, "SIGUSR1"):
        pid = current_supervisor_pid(case)
        if pid:
            try:
                os.kill(pid, signal.SIGUSR1)
            except ProcessLookupError:
                pass
    return {"case_name": case["case_name"], "directive": directive}


def render_notes(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "notes: none\n"
    lines = ["notes:"]
    for note in notes:
        line = f"- {note['id']}: {note.get('message', '').strip()}"
        if note.get("expires_at"):
            line += f" (expires_at={note['expires_at']})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def render_directives(directives: list[dict[str, Any]]) -> str:
    if not directives:
        return "directives: none\n"
    lines = ["directives:"]
    for directive in directives:
        line = (
            f"- {directive['id']} [{directive.get('mode', 'directive')}/{directive.get('priority', 'normal')}] "
            f"{directive.get('summary', '').strip()}"
        )
        if directive.get("interrupt_policy") and directive.get("interrupt_policy") != "none":
            line += f" (interrupt={directive['interrupt_policy']})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def render_prompt_directives(directives: list[dict[str, Any]]) -> str:
    if not directives:
        return "Active directive details: none."
    lines = ["Active directive details:"]
    for directive in directives:
        lines.append(
            f"- {directive['id']} [{directive.get('mode', 'directive')}/{directive.get('priority', 'normal')}]: "
            f"{directive.get('summary', '').strip()}"
        )
        payload = directive.get("payload")
        if isinstance(payload, dict) and payload:
            payload_text = json.dumps(payload, indent=2, sort_keys=True)
            lines.append("  payload:")
            lines.extend(f"    {line}" for line in payload_text.splitlines())
    return "\n".join(lines)


def list_notes(case: dict[str, Any]) -> dict[str, Any]:
    return {"case_name": case["case_name"], "notes": active_notes(case)}


def resolve_note(case: dict[str, Any], note_id: str, *, reason: str | None = None) -> dict[str, Any]:
    archived = archive_note(case, note_id, event_type="resolved", reason=reason)
    return {"case_name": case["case_name"], "note": archived, "status": "resolved"}


def expire_note(case: dict[str, Any], note_id: str, *, reason: str | None = None) -> dict[str, Any]:
    archived = archive_note(case, note_id, event_type="expired", reason=reason)
    return {"case_name": case["case_name"], "note": archived, "status": "expired"}


def list_directives(case: dict[str, Any]) -> dict[str, Any]:
    return {"case_name": case["case_name"], "directives": active_directives(case)}


def resolve_directive(case: dict[str, Any], directive_id: str, *, reason: str | None = None) -> dict[str, Any]:
    archived = archive_directive(case, directive_id, event_type="resolved", reason=reason)
    return {"case_name": case["case_name"], "directive": archived, "status": "resolved"}


def expire_directive(case: dict[str, Any], directive_id: str, *, reason: str | None = None) -> dict[str, Any]:
    archived = archive_directive(case, directive_id, event_type="expired", reason=reason)
    return {"case_name": case["case_name"], "directive": archived, "status": "expired"}


def supersede_directive(
    case: dict[str, Any],
    directive_id: str,
    *,
    replacement_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    archived = archive_directive(
        case,
        directive_id,
        event_type="superseded",
        reason=reason or f"Superseded by {replacement_id}",
        replacement_id=replacement_id,
    )
    return {"case_name": case["case_name"], "directive": archived, "status": "superseded"}


def request_stop(case: dict[str, Any]) -> dict[str, Any]:
    def update_state(current: dict[str, Any]) -> None:
        current["stop_requested"] = True
        current["status"] = "stopping"
        current["last_cycle_note"] = "Stop requested."

    state = mutate_case_state(case, update_state)
    update_logbook(case, state, "Stop after the current cycle.")
    pid = current_supervisor_pid(case)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return {"case_name": case["case_name"], "stop_requested": True}


def clear_stop_request(case: dict[str, Any]) -> dict[str, Any]:
    def update_state(current: dict[str, Any]) -> None:
        current["stop_requested"] = False
        if current.get("status") in {"stopped", "stopping"}:
            current["status"] = "idle"
        current["last_cycle_note"] = "Stop request cleared."

    state = mutate_case_state(case, update_state)
    update_logbook(case, state, "Resume the mission.")
    return {"case_name": case["case_name"], "stop_requested": False}


def read_pid_file(path: pathlib.Path) -> int | None:
    if not path.exists():
        return None
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def is_process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_command_tokens(pid: int | None) -> list[str]:
    if not pid:
        return []
    proc = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    command = proc.stdout.strip()
    if not command:
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def build_supervisor_command(case: dict[str, Any]) -> list[str]:
    script = pathlib.Path(__file__).resolve()
    return [
        sys.executable,
        str(script),
        "supervise",
        "--project-dir",
        str(case["project_root"]),
        "--case",
        case["case_name"],
    ]


def write_supervisor_metadata(
    case: dict[str, Any],
    *,
    pid: int,
    command: list[str] | None = None,
    started_at: str | None = None,
) -> None:
    write_json(
        case["paths"]["supervisor_meta"],
        {
            "schema_version": SCHEMA_VERSION,
            "pid": pid,
            "case_name": case["case_name"],
            "project_root": str(case["project_root"]),
            "started_at": started_at or iso_now(),
            "command": list(command or build_supervisor_command(case)),
        },
    )


def clear_supervisor_runtime_identity(case: dict[str, Any], *, expected_pid: int | None = None) -> None:
    current_pid = read_pid_file(case["paths"]["pid"])
    metadata = read_json(case["paths"]["supervisor_meta"])
    metadata_pid = metadata.get("pid") if isinstance(metadata, dict) else None
    if expected_pid is not None:
        if current_pid not in {None, expected_pid}:
            return
        if metadata_pid not in {None, expected_pid}:
            return
    if case["paths"]["pid"].exists():
        case["paths"]["pid"].unlink()
    if case["paths"]["supervisor_meta"].exists():
        case["paths"]["supervisor_meta"].unlink()


def command_matches_supervisor(tokens: list[str], case: dict[str, Any]) -> bool:
    if not tokens:
        return False
    script_name = pathlib.Path(__file__).name

    def matches_args(args: list[str]) -> bool:
        if len(args) < 5 or args[0] != "supervise" or args[1] != "--project-dir":
            return False
        try:
            case_flag_index = args.index("--case", 2)
        except ValueError:
            return False
        project_root = " ".join(args[2:case_flag_index])
        case_value_index = case_flag_index + 1
        if case_value_index >= len(args):
            return False
        return (
            project_root == str(case["project_root"])
            and args[case_value_index] == case["case_name"]
        )

    for index, token in enumerate(tokens):
        if pathlib.Path(token).name != script_name:
            continue
        if matches_args(tokens[index + 1 :]):
            return True
    return False


def deadline_reached(deadline: str | None, now: datetime | None = None) -> bool:
    if not deadline:
        return False
    now = now or utc_now()
    return now >= parse_iso(deadline)


def should_start_fresh_thread(state: dict[str, Any], policy: dict[str, Any], now: datetime | None = None) -> tuple[bool, str]:
    now = now or utc_now()
    thread_id = state.get("current_thread_id")
    if not thread_id:
        return True, "no_current_thread"
    episodes = int(state.get("current_thread_episode_count") or 0)
    if episodes >= int(policy["max_episodes_per_thread"]):
        return True, "episode_limit"
    started_at = parse_iso(state.get("current_thread_started_at"))
    if started_at:
        age_hours = (now - started_at).total_seconds() / 3600.0
        if age_hours >= float(policy["max_thread_age_hours"]):
            return True, "thread_age_limit"
    return False, ""


def build_prompt(case: dict[str, Any], state: dict[str, Any]) -> str:
    skills = case["config"].get("skills", [])
    skill_line = ", ".join(skills) if skills else "none"
    deadline = case["config"].get("deadline") or "none"
    mission_path = case["files"]["mission"]
    directives_path = case["files"]["directives"]
    logbook_path = case["files"]["logbook"]
    inbox_path = case["files"]["inbox"]
    ledger_path = case["files"]["ledger"]
    directive_ack_path = case["files"]["directive_ack"]
    directives = active_directives(case)
    ledger_tail = read_ledger_tail(case["case_dir"])
    ledger_section = f"Recent ledger tail:\n{ledger_tail}" if ledger_tail else "Recent ledger tail: none."
    return textwrap.dedent(
        f"""\
        Continue the durable mission in this repo.

        Goal: {case["config"].get("goal", "")}
        Requested skills: {skill_line}
        Validator: {case["config"].get("validator", "")}
        Deadline: {deadline}

        Read these files first:
        - {mission_path}
        - {directives_path}
        - {logbook_path}
        - {inbox_path}

        Read {ledger_path} only if you need recent episode history.

        {ledger_section}

        {render_prompt_directives(directives)}

        Rules:
        - Work directly in the repo files.
        - Active directives are authoritative. Notes are advisory.
        - If active directives exist, acknowledge them in `{directive_ack_path}` before unrelated work and bring the project state into compliance with them.
        - Every directive acknowledgment in `{directive_ack_path}` should include `acknowledged_at`, `status`, and `reason`; use the current UTC time for `acknowledged_at`.
        - Let the run end naturally. Relay will checkpoint after the worker exits or the hard cap is reached.
        - You may update only the `## Worker Notes` section of `.relay/{case["case_name"]}/logbook.md` and `.relay/{case["case_name"]}/directive_ack.json` inside the relay case.
        - Keep `## Worker Notes` short and durable. Record the active target, what changed, the blocker, the exact next action, and any cluster job or run ids needed for the next cycle.
        - Do not edit `.relay/{case["case_name"]}/case.json`, `.relay/{case["case_name"]}/state.json`, `.relay/{case["case_name"]}/notes.json`, `.relay/{case["case_name"]}/note_history.jsonl`, `.relay/{case["case_name"]}/directives.json`, `.relay/{case["case_name"]}/directive_history.jsonl`, `.relay/{case["case_name"]}/directive_compliance.json`, `.relay/{case["case_name"]}/inbox.md`, `.relay/{case["case_name"]}/ledger.jsonl`, or anything under `.relay/{case["case_name"]}/runtime/`.
        - Keep going until the validator passes, the deadline arrives, or a stop request is present.
        - If you are blocked or waiting on long external work, record the next action in the `## Worker Notes` section of `.relay/{case["case_name"]}/logbook.md` before stopping.
        - After this cycle, the validator will run automatically.
        """
    ).strip() + "\n"


def codex_bin() -> str:
    return os.environ.get("RELAY_CODEX_BIN", "codex")


def codex_exec_args(case: dict[str, Any]) -> list[str]:
    return normalize_codex_exec_args(case["config"].get("codex_exec_args"))


def codex_exec_mode_flags(extra_args: list[str]) -> list[str]:
    if FULL_ACCESS_FLAG in extra_args:
        return []
    return [FULL_AUTO_FLAG]


def build_episode_command(case: dict[str, Any], thread_id: str | None) -> list[str]:
    extra_args = codex_exec_args(case)
    mode_flags = codex_exec_mode_flags(extra_args)
    if thread_id:
        command = [
            codex_bin(),
            "exec",
            *extra_args,
            "resume",
            "--json",
            *mode_flags,
            "--skip-git-repo-check",
            "--output-last-message",
            str(case["paths"]["last_message"]),
            thread_id,
            "-",
        ]
    else:
        command = [
            codex_bin(),
            "exec",
            *extra_args,
            "--json",
            *mode_flags,
            "--skip-git-repo-check",
            "-C",
            str(case["project_root"]),
            "--output-last-message",
            str(case["paths"]["last_message"]),
            "-",
        ]
    return command


def codex_session_root() -> pathlib.Path:
    raw = os.environ.get("RELAY_CODEX_SESSION_ROOT", "~/.codex/sessions")
    return pathlib.Path(raw).expanduser()


def rollout_log_paths(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    base = root or codex_session_root()
    if not base.exists():
        return []
    return [path for path in base.glob("**/rollout-*.jsonl") if path.is_file()]


def rollout_log_signature(path: pathlib.Path) -> tuple[int, int] | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (int(stat_result.st_mtime_ns), int(stat_result.st_size))


def snapshot_rollout_logs(root: pathlib.Path | None = None) -> dict[pathlib.Path, tuple[int, int]]:
    snapshot: dict[pathlib.Path, tuple[int, int]] = {}
    for path in rollout_log_paths(root):
        signature = rollout_log_signature(path)
        if signature is not None:
            snapshot[path] = signature
    return snapshot


def changed_rollout_logs(snapshot: dict[pathlib.Path, tuple[int, int]], root: pathlib.Path | None = None) -> list[pathlib.Path]:
    changed: list[pathlib.Path] = []
    for path in rollout_log_paths(root):
        signature = rollout_log_signature(path)
        if signature is None:
            continue
        if snapshot.get(path) != signature:
            changed.append(path)
    changed.sort(key=lambda candidate: candidate.stat().st_mtime_ns, reverse=True)
    return changed


def describe_session_event(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "unknown")
    inner = payload.get("payload")
    if isinstance(inner, dict) and inner.get("type"):
        return f"{event_type}:{inner['type']}"
    return event_type


def find_session_log_path(thread_id: str | None, root: pathlib.Path | None = None) -> pathlib.Path | None:
    session_root = root or codex_session_root()
    if not session_root.exists():
        return None
    if not thread_id:
        return None
    matches = list(session_root.glob(f"**/rollout-*{thread_id}*.jsonl"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def extract_thread_id_from_session_log(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload_type = payload.get("type")
            inner = payload.get("payload")
            if payload_type == "session_meta" and isinstance(inner, dict) and inner.get("id"):
                return str(inner["id"])
            if payload_type == "thread.started" and payload.get("thread_id"):
                return str(payload["thread_id"])
    return None


def resolve_episode_session_log(
    tracker: SessionTracker,
    *,
    thread_id: str | None = None,
    root: pathlib.Path | None = None,
) -> pathlib.Path | None:
    session_root = root or codex_session_root()
    if thread_id:
        exact = find_session_log_path(thread_id, session_root)
        if exact is not None:
            return exact
    candidates = changed_rollout_logs(tracker.episode_session_snapshot, session_root)
    if not candidates:
        return None
    if thread_id:
        matching = [path for path in candidates if extract_thread_id_from_session_log(path) == thread_id]
        if len(matching) == 1:
            return matching[0]
        return None
    if len(candidates) == 1:
        return candidates[0]
    return None


def recover_episode_thread_id(
    tracker: SessionTracker,
    *,
    root: pathlib.Path | None = None,
) -> tuple[str | None, pathlib.Path | None, str | None]:
    session_root = root or codex_session_root()
    candidates = changed_rollout_logs(tracker.episode_session_snapshot, session_root)
    thread_to_paths: dict[str, list[pathlib.Path]] = {}
    for path in candidates:
        recovered = extract_thread_id_from_session_log(path)
        if recovered:
            thread_to_paths.setdefault(recovered, []).append(path)
    if not candidates:
        return None, None, None
    if not thread_to_paths:
        return None, None, "unable_to_resolve_thread_id_from_changed_session_logs"
    if len(thread_to_paths) != 1:
        return None, None, "ambiguous_thread_id_from_changed_session_logs"
    thread_id = next(iter(thread_to_paths))
    matching_paths = thread_to_paths[thread_id]
    path = max(matching_paths, key=lambda candidate: candidate.stat().st_mtime_ns)
    return thread_id, path, None


def sync_session_tracker(tracker: SessionTracker) -> bool:
    if tracker.path is None:
        tracker.path = resolve_episode_session_log(tracker, thread_id=tracker.thread_id)
        if tracker.path is None:
            return False
    elif tracker.thread_id:
        exact_path = find_session_log_path(tracker.thread_id)
        if exact_path is not None and exact_path != tracker.path:
            tracker.path = exact_path
            tracker.offset = 0
    if not tracker.path.exists():
        tracker.path = None
        tracker.offset = 0
        return False

    size = tracker.path.stat().st_size
    if size < tracker.offset:
        tracker.offset = 0
    if size == tracker.offset:
        return False

    updated = False
    with tracker.path.open("r", encoding="utf-8", errors="ignore") as handle:
        handle.seek(tracker.offset)
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            tracker.last_event_type = describe_session_event(payload)
            payload_type = payload.get("type")
            inner = payload.get("payload")
            if payload_type == "session_meta" and isinstance(inner, dict) and inner.get("id"):
                tracker.thread_id = str(inner["id"])
            elif payload_type == "thread.started" and payload.get("thread_id"):
                tracker.thread_id = str(payload["thread_id"])
            if payload_type == "response_item" and isinstance(inner, dict):
                inner_type = inner.get("type")
                if inner_type == "function_call":
                    call_id = str(payload.get("call_id") or inner.get("call_id") or "")
                    if call_id:
                        tracker.pending_tool_calls[call_id] = str(inner.get("name") or "")
                elif inner_type == "function_call_output":
                    call_id = str(payload.get("call_id") or inner.get("call_id") or "")
                    if call_id:
                        tracker.pending_tool_calls.pop(call_id, None)
            updated = True
        tracker.offset = handle.tell()
    return updated


def liveness_poll_seconds(policy: dict[str, Any]) -> float:
    try:
        value = float(policy.get("liveness_poll_seconds", 5))
    except (TypeError, ValueError):
        value = 5.0
    return max(0.1, value)


def bounded_policy_seconds(policy: dict[str, Any], key: str, default: float, minimum: float) -> float:
    try:
        value = float(policy.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def latest_project_activity_epoch(project_root: pathlib.Path) -> float:
    latest = 0.0
    relay_dir = relay_root(project_root)
    for dirpath, dirnames, filenames in os.walk(project_root):
        current = pathlib.Path(dirpath)
        if current == relay_dir or current.name == ".git":
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in {".git", ".relay"}]
        for filename in filenames:
            path = current / filename
            try:
                latest = max(latest, path.stat().st_mtime)
            except FileNotFoundError:
                continue
    return latest


def process_descendants(pid: int) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["ps", "-ax", "-o", "pid=,ppid=,pcpu=,pmem=,command="],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    children: dict[int, list[dict[str, Any]]] = {}
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            child_pid = int(parts[0])
            parent_pid = int(parts[1])
            pcpu = float(parts[2])
            pmem = float(parts[3])
        except ValueError:
            continue
        entry = {
            "pid": child_pid,
            "ppid": parent_pid,
            "pcpu": pcpu,
            "pmem": pmem,
            "command": parts[4],
        }
        children.setdefault(parent_pid, []).append(entry)

    out: list[dict[str, Any]] = []
    stack = [pid]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            child_pid = int(child["pid"])
            if child_pid in seen:
                continue
            seen.add(child_pid)
            out.append(child)
            stack.append(child_pid)
    return out


def extract_thread_id(output: str) -> str | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "thread.started" and payload.get("thread_id"):
            return str(payload["thread_id"])
    return None


def extract_episode_signal(line: str) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return {}
    signal_data: dict[str, Any] = {}
    if payload.get("type") == "thread.started" and payload.get("thread_id"):
        signal_data["thread_id"] = str(payload["thread_id"])
    if payload.get("type") == "turn.completed":
        signal_data["turn_completed"] = True
    item = payload.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            signal_data["last_message"] = text
    return signal_data


def turn_completion_grace_seconds() -> float:
    raw = os.environ.get("RELAY_TURN_COMPLETION_GRACE_SECONDS", "30")
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    return max(0.0, value)


def _terminate_episode_process(proc: subprocess.Popen[str], *, grace_seconds: float = 5.0) -> int | None:
    if proc.poll() is not None:
        return proc.returncode
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return proc.poll()
    except OSError:
        proc.terminate()
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return proc.returncode
        time.sleep(0.05)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return proc.poll()
    except OSError:
        proc.kill()
    try:
        return proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        return proc.poll()


def write_episode_logs(case: dict[str, Any], stdout: str, stderr: str) -> None:
    if stdout:
        with case["paths"]["events"].open("a", encoding="utf-8") as handle:
            handle.write(stdout)
            if not stdout.endswith("\n"):
                handle.write("\n")
    if stderr:
        with case["paths"]["log"].open("a", encoding="utf-8") as handle:
            handle.write(stderr)
            if not stderr.endswith("\n"):
                handle.write("\n")


def append_supervisor_log(case: dict[str, Any], message: str) -> None:
    with case["paths"]["log"].open("a", encoding="utf-8") as handle:
        handle.write(f"[{iso_now()}] {message}\n")


def reap_detached_process(proc: subprocess.Popen[Any]) -> None:
    def wait_for_exit() -> None:
        with contextlib.suppress(Exception):
            proc.wait()

    threading.Thread(
        target=wait_for_exit,
        name=f"relay-detached-reaper-{proc.pid}",
        daemon=True,
    ).start()


def active_episode_payload(
    *,
    started_at: str,
    thread_id: str | None,
    command: list[str],
    prompt_path: str,
    last_progress_at: str,
    last_event_type: str | None,
    session_log_path: str | None,
    pending_tool_calls: int,
    active_child_count: int,
    stall_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "started_at": started_at,
        "thread_id": thread_id,
        "command": command,
        "prompt_path": prompt_path,
        "last_progress_at": last_progress_at,
        "last_event_type": last_event_type,
        "session_log_path": session_log_path,
        "pending_tool_calls": pending_tool_calls,
        "active_child_count": active_child_count,
        "stall_reason": stall_reason,
    }


def relay_environment(case: dict[str, Any]) -> dict[str, str]:
    return {
        "RELAY_CASE_DIR": str(case["case_dir"]),
        "RELAY_ACTIVE_DIRECTIVES_PATH": str(case["files"]["directives"]),
        "RELAY_DIRECTIVE_ACK_PATH": str(case["files"]["directive_ack"]),
        "RELAY_DIRECTIVE_COMPLIANCE_PATH": str(case["files"]["directive_compliance"]),
        "RELAY_NOTE_VIEW_PATH": str(case["files"]["inbox"]),
    }


def run_episode(case: dict[str, Any], state: dict[str, Any], prompt: str, thread_id: str | None) -> EpisodeResult:
    started_at = iso_now()
    command = build_episode_command(case, thread_id)
    timeout_seconds = int(float(case["config"]["policy"]["episode_hard_cap_hours"]) * 3600)
    completion_grace = turn_completion_grace_seconds()
    poll_seconds = liveness_poll_seconds(case["config"]["policy"])
    stall_guard_seconds = bounded_policy_seconds(
        case["config"]["policy"],
        "stall_guard_seconds",
        DEFAULT_POLICY["stall_guard_seconds"],
        max(1.0, poll_seconds * 2.0),
    )
    tool_call_stall_seconds = bounded_policy_seconds(
        case["config"]["policy"],
        "tool_call_stall_seconds",
        DEFAULT_POLICY["tool_call_stall_seconds"],
        max(0.25, poll_seconds * 2.0),
    )
    write_text(case["paths"]["current_prompt"], prompt)
    append_supervisor_log(case, f"episode start thread={thread_id or 'new'} command={shlex.join(command)}")
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(case["project_root"]),
        env={**os.environ, **relay_environment(case)},
        start_new_session=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    proc.stdin.write(prompt)
    proc.stdin.close()

    event_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def pump(stream: Any, source: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                event_queue.put((source, line))
        finally:
            try:
                stream.close()
            finally:
                event_queue.put((source, None))

    stdout_thread = threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_done = False
    stderr_done = False
    thread = thread_id
    observed_last_message = ""
    turn_completed_at: float | None = None
    stalled_guard_triggered = False
    stall_reason: str | None = None
    timed_out = False
    interrupted = False
    interrupt_reason: str | None = None
    completion_guard_triggered = False
    returncode: int | None = None
    hard_deadline = time.monotonic() + timeout_seconds
    started_monotonic = time.monotonic()
    last_progress_monotonic = started_monotonic
    next_poll_at = started_monotonic
    tracker = SessionTracker(thread_id=thread, episode_session_snapshot=snapshot_rollout_logs())
    latest_project_mtime = latest_project_activity_epoch(case["project_root"])
    active_child_count = 0
    last_event_type = "episode:start"
    last_progress_at_iso = started_at
    last_state_flush = 0.0

    def flush_active_episode(*, force: bool = False) -> None:
        nonlocal last_state_flush
        now = time.monotonic()
        if not force and (now - last_state_flush) < 1.0:
            return
        payload = active_episode_payload(
            started_at=started_at,
            thread_id=thread,
            command=command,
            prompt_path=str(case["paths"]["current_prompt"]),
            last_progress_at=last_progress_at_iso,
            last_event_type=last_event_type,
            session_log_path=str(tracker.path) if tracker.path else None,
            pending_tool_calls=len(tracker.pending_tool_calls),
            active_child_count=active_child_count,
            stall_reason=stall_reason,
        )
        update_active_episode_state(case, state, payload)
        last_state_flush = now

    flush_active_episode(force=True)

    while True:
        now = time.monotonic()
        if now >= hard_deadline:
            timed_out = True
            append_supervisor_log(case, f"episode hit hard cap after {timeout_seconds}s; terminating process")
            _terminate_episode_process(proc)
            returncode = 124
            break

        if state.get("interrupt_requested"):
            interrupted = True
            interrupt_reason = str(state.get("interrupt_reason") or "interrupt_requested")
            append_supervisor_log(case, f"episode interrupted reason={interrupt_reason}; terminating process")
            _terminate_episode_process(proc)
            returncode = 130
            break

        if turn_completed_at is not None and proc.poll() is None and (now - turn_completed_at) >= completion_grace:
            completion_guard_triggered = True
            append_supervisor_log(
                case,
                f"episode reached turn.completed and stayed alive for {completion_grace:.1f}s; terminating stalled process",
            )
            _terminate_episode_process(proc)
            returncode = 0
            break

        if now >= next_poll_at:
            next_poll_at = now + poll_seconds
            if thread and tracker.thread_id != thread:
                tracker.thread_id = thread
            if sync_session_tracker(tracker):
                last_progress_monotonic = now
                last_progress_at_iso = iso_now()
                if tracker.last_event_type:
                    last_event_type = tracker.last_event_type
                if tracker.thread_id and not thread:
                    thread = tracker.thread_id
            active_children = process_descendants(proc.pid)
            active_child_count = len(active_children)
            if active_child_count:
                last_progress_monotonic = now
                last_progress_at_iso = iso_now()
            current_project_mtime = latest_project_activity_epoch(case["project_root"])
            if current_project_mtime > latest_project_mtime:
                latest_project_mtime = current_project_mtime
                last_progress_monotonic = now
                last_progress_at_iso = iso_now()

            idle_for = now - last_progress_monotonic
            if tracker.pending_tool_calls and active_child_count == 0 and idle_for >= tool_call_stall_seconds:
                stalled_guard_triggered = True
                stall_reason = "tool_dispatch_stalled"
                append_supervisor_log(
                    case,
                    "episode stalled after tool dispatch with no matching outputs; terminating process",
                )
                _terminate_episode_process(proc)
                returncode = 125
                flush_active_episode(force=True)
                break
            if active_child_count == 0 and idle_for >= stall_guard_seconds:
                stalled_guard_triggered = True
                stall_reason = "inactive_episode"
                append_supervisor_log(
                    case,
                    f"episode made no observable progress for {stall_guard_seconds:.1f}s; terminating process",
                )
                _terminate_episode_process(proc)
                returncode = 125
                flush_active_episode(force=True)
                break
            flush_active_episode()

        queue_timeout = 0.25
        if turn_completed_at is not None:
            queue_timeout = min(queue_timeout, max(0.05, completion_grace - (now - turn_completed_at)))
        try:
            source, line = event_queue.get(timeout=queue_timeout)
        except queue.Empty:
            source = ""
            line = None

        if source:
            if line is None:
                if source == "stdout":
                    stdout_done = True
                else:
                    stderr_done = True
            else:
                if source == "stdout":
                    stdout_parts.append(line)
                    last_progress_monotonic = now
                    last_progress_at_iso = iso_now()
                    signal_data = extract_episode_signal(line)
                    if signal_data.get("thread_id"):
                        thread = str(signal_data["thread_id"])
                        last_event_type = "thread.started"
                        flush_active_episode(force=True)
                    if signal_data.get("turn_completed") and turn_completed_at is None:
                        turn_completed_at = time.monotonic()
                        last_event_type = "turn.completed"
                        flush_active_episode(force=True)
                    if signal_data.get("last_message"):
                        observed_last_message = str(signal_data["last_message"])
                else:
                    stderr_parts.append(line)
                    last_progress_monotonic = now
                    last_progress_at_iso = iso_now()
                    last_event_type = "stderr"

        proc_returncode = proc.poll()
        if proc_returncode is not None and stdout_done and stderr_done:
            returncode = int(proc_returncode)
            break

    stdout_thread.join(timeout=1.0)
    stderr_thread.join(timeout=1.0)
    while True:
        try:
            source, line = event_queue.get_nowait()
        except queue.Empty:
            break
        if source == "stdout":
            if line is None:
                stdout_done = True
            else:
                stdout_parts.append(line)
                signal_data = extract_episode_signal(line)
                if signal_data.get("thread_id"):
                    thread = str(signal_data["thread_id"])
                if signal_data.get("last_message"):
                    observed_last_message = str(signal_data["last_message"])
        elif source == "stderr":
            if line is None:
                stderr_done = True
            else:
                stderr_parts.append(line)

    if returncode is None:
        proc_returncode = proc.poll()
        returncode = int(proc_returncode) if proc_returncode is not None else 0

    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
    thread_resolution_error: str | None = None
    if tracker.path is None:
        tracker.path = resolve_episode_session_log(tracker, thread_id=thread)
    if not thread:
        thread = tracker.thread_id or extract_thread_id(stdout)
    if not thread:
        recovered_thread_id, recovered_path, thread_resolution_error = recover_episode_thread_id(tracker)
        if recovered_thread_id:
            thread = recovered_thread_id
            tracker.thread_id = recovered_thread_id
        if recovered_path is not None:
            tracker.path = recovered_path
    if tracker.path is None and thread:
        tracker.path = resolve_episode_session_log(tracker, thread_id=thread)
    write_episode_logs(case, stdout, stderr)
    last_message = read_text(case["paths"]["last_message"])
    if not last_message.strip() and observed_last_message:
        last_message = observed_last_message.rstrip() + "\n"
        write_text(case["paths"]["last_message"], last_message)
    update_active_episode_state(case, state, None)
    append_supervisor_log(
        case,
        f"episode finished returncode={returncode} timed_out={timed_out} completion_guard_triggered={completion_guard_triggered} stalled_guard_triggered={stalled_guard_triggered} stall_reason={stall_reason or 'none'} thread={thread or 'missing'}",
    )
    return EpisodeResult(
        returncode=returncode,
        timed_out=timed_out,
        interrupted=interrupted,
        interrupt_reason=interrupt_reason,
        completion_guard_triggered=completion_guard_triggered,
        stalled_guard_triggered=stalled_guard_triggered,
        stall_reason=stall_reason,
        stdout=stdout,
        stderr=stderr,
        thread_id=thread,
        started_at=started_at,
        finished_at=iso_now(),
        command=command,
        prompt=prompt,
        prompt_path=str(case["paths"]["current_prompt"]),
        last_message=last_message,
        session_log_path=str(tracker.path) if tracker.path else None,
        last_event_type=tracker.last_event_type or last_event_type,
        pending_tool_calls=len(tracker.pending_tool_calls),
        last_progress_at=last_progress_at_iso,
        thread_resolution_error=thread_resolution_error,
    )


def run_validator(case: dict[str, Any]) -> ValidationResult:
    validator = str(case["config"].get("validator", "")).strip()
    if not validator:
        now = iso_now()
        return ValidationResult(returncode=0, stdout="", stderr="", passed=True, started_at=now, finished_at=now)
    started_at = iso_now()
    append_supervisor_log(case, f"validator start command={validator}")
    proc = subprocess.run(
        validator,
        shell=True,
        text=True,
        capture_output=True,
        cwd=str(case["project_root"]),
        env={**os.environ, **relay_environment(case)},
    )
    result = ValidationResult(
        returncode=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        passed=int(proc.returncode) == 0,
        started_at=started_at,
        finished_at=iso_now(),
    )
    append_supervisor_log(
        case,
        f"validator finished returncode={result.returncode} passed={result.passed} started={result.started_at} finished={result.finished_at}",
    )
    if result.stdout:
        append_jsonl(case["case_dir"] / LEDGER_FILE, {"type": "validator_stdout", "at": iso_now(), "text": result.stdout})
    if result.stderr:
        append_jsonl(case["case_dir"] / LEDGER_FILE, {"type": "validator_stderr", "at": iso_now(), "text": result.stderr})
    return result


def finalize_thread_history(state: dict[str, Any], finished_at: str | None = None) -> None:
    thread_id = state.get("current_thread_id")
    if not thread_id:
        return
    history = list(state.get("thread_history") or [])
    if history and history[-1].get("thread_id") == thread_id and not history[-1].get("ended_at"):
        history[-1]["ended_at"] = finished_at or iso_now()
        history[-1]["episode_count"] = int(state.get("current_thread_episode_count") or 0)
        state["thread_history"] = history
        return
    history.append(
        {
            "thread_id": thread_id,
            "started_at": state.get("current_thread_started_at"),
            "ended_at": finished_at or iso_now(),
            "episode_count": int(state.get("current_thread_episode_count") or 0),
        }
    )
    state["thread_history"] = history


def rollover_thread(case: dict[str, Any], state: dict[str, Any], reason: str) -> None:
    finalize_thread_history(state)
    state["current_thread_id"] = None
    state["current_thread_started_at"] = None
    state["current_thread_episode_count"] = 0
    state["current_rollover_reason"] = reason
    save_case_state(case, state)
    update_logbook(case, state, f"Start a fresh thread next cycle: {reason}.")


def current_supervisor_pid(case: dict[str, Any]) -> int | None:
    pid = read_pid_file(case["paths"]["pid"])
    if not is_process_alive(pid):
        return None
    metadata = read_json(case["paths"]["supervisor_meta"])
    if isinstance(metadata, dict):
        if metadata.get("pid") not in {None, pid}:
            return None
        if metadata.get("case_name") != case["case_name"]:
            return None
        if metadata.get("project_root") != str(case["project_root"]):
            return None
    return pid if command_matches_supervisor(process_command_tokens(pid), case) else None


def status_snapshot(case: dict[str, Any]) -> dict[str, Any]:
    case = ensure_control_plane(case)
    state = case["state"]
    active_episode = state.get("active_episode") or {}
    directives = list((case.get("control") or {}).get("directives", {}).get("directives") or [])
    notes = list((case.get("control") or {}).get("notes", {}).get("notes") or [])
    newest_directive = max(directives, key=lambda item: item["created_at"], default=None)
    episode_started_at = parse_iso(active_episode.get("started_at"))
    newest_directive_started_after_episode = False
    if newest_directive and episode_started_at:
        directive_started_at = parse_iso(newest_directive.get("created_at"))
        newest_directive_started_after_episode = bool(directive_started_at and directive_started_at > episode_started_at)
    directive_acknowledged: bool | None
    if not directives:
        directive_acknowledged = None
    else:
        directive_acknowledged = all(bool(item.get("acknowledged_at")) and bool(item.get("acknowledgment_status")) for item in directives)
    directive_compliance: bool | None
    if not directives:
        directive_compliance = None
    else:
        statuses = [item.get("project_compliance") for item in directives]
        if any(status is False for status in statuses):
            directive_compliance = False
        elif all(status is True for status in statuses):
            directive_compliance = True
        else:
            directive_compliance = None
    pid = current_supervisor_pid(case)
    alive = pid is not None
    deadline = case["config"].get("deadline")
    return {
        "case_name": case["case_name"],
        "project_root": str(case["project_root"]),
        "case_dir": str(case["case_dir"]),
        "status": state.get("status"),
        "stop_requested": state.get("stop_requested", False),
        "deadline": deadline,
        "deadline_reached": deadline_reached(deadline),
        "supervisor_pid": pid,
        "supervisor_running": alive,
        "current_thread_id": active_episode.get("thread_id") or state.get("current_thread_id"),
        "current_thread_started_at": state.get("current_thread_started_at"),
        "current_thread_episode_count": state.get("current_thread_episode_count", 0),
        "total_episodes": state.get("total_episodes", 0),
        "last_episode_exit_code": state.get("last_episode_exit_code"),
        "last_episode_timed_out": state.get("last_episode_timed_out"),
        "last_episode_stalled": state.get("last_episode_stalled", False),
        "last_episode_stall_reason": state.get("last_episode_stall_reason"),
        "last_episode_interrupted": state.get("last_episode_interrupted", False),
        "last_episode_interrupt_reason": state.get("last_episode_interrupt_reason"),
        "last_validator_exit_code": state.get("last_validator_exit_code"),
        "last_validator_ok": state.get("last_validator_ok"),
        "completed_at": state.get("completed_at"),
        "last_error": state.get("last_error"),
        "skills": case["config"].get("skills", []),
        "validator": case["config"].get("validator"),
        "goal": case["config"].get("goal"),
        "current_rollover_reason": state.get("current_rollover_reason"),
        "active_episode": active_episode or None,
        "active_notes_count": len(notes),
        "active_directives": directives,
        "active_directive_ids": [item["id"] for item in directives],
        "directive_acknowledged": directive_acknowledged,
        "directive_compliance": directive_compliance,
        "newest_directive_id": newest_directive.get("id") if newest_directive else None,
        "newest_directive_created_at": newest_directive.get("created_at") if newest_directive else None,
        "newest_directive_started_after_episode": newest_directive_started_after_episode,
    }


def render_status(snapshot: dict[str, Any]) -> str:
    lines = [
        f"case: {snapshot['case_name']}",
        f"status: {snapshot['status']}",
        f"supervisor: {snapshot['supervisor_pid'] if snapshot['supervisor_pid'] else 'none'}",
        f"running: {snapshot['supervisor_running']}",
        f"deadline: {snapshot['deadline'] or 'none'}",
        f"deadline_reached: {snapshot['deadline_reached']}",
        f"thread: {snapshot['current_thread_id'] or 'none'}",
        f"thread_episodes: {snapshot['current_thread_episode_count']}",
        f"total_episodes: {snapshot['total_episodes']}",
        f"validator_ok: {snapshot['last_validator_ok']}",
        f"validator_exit: {snapshot['last_validator_exit_code']}",
        f"stop_requested: {snapshot['stop_requested']}",
        f"skills: {', '.join(snapshot['skills']) if snapshot['skills'] else 'none'}",
        f"active_notes: {snapshot['active_notes_count']}",
        f"active_directives: {', '.join(snapshot['active_directive_ids']) if snapshot['active_directive_ids'] else 'none'}",
    ]
    if snapshot["newest_directive_id"]:
        lines.append(f"newest_directive: {snapshot['newest_directive_id']}")
        lines.append(f"newest_directive_created_at: {snapshot['newest_directive_created_at']}")
        lines.append(f"newest_directive_after_active_episode_start: {snapshot['newest_directive_started_after_episode']}")
        lines.append(f"directive_acknowledged: {snapshot['directive_acknowledged']}")
        lines.append(f"directive_compliance: {snapshot['directive_compliance']}")
    if snapshot.get("last_episode_stalled"):
        lines.append(f"last_episode_stalled: {snapshot['last_episode_stalled']}")
        lines.append(f"last_episode_stall_reason: {snapshot.get('last_episode_stall_reason') or 'unknown'}")
    if snapshot.get("last_episode_interrupted"):
        lines.append(f"last_episode_interrupted: {snapshot['last_episode_interrupted']}")
        lines.append(f"last_episode_interrupt_reason: {snapshot.get('last_episode_interrupt_reason') or 'unknown'}")
    active_episode = snapshot.get("active_episode") or {}
    if active_episode:
        lines.append(f"active_episode_last_event: {active_episode.get('last_event_type') or 'none'}")
        lines.append(f"active_episode_pending_tool_calls: {active_episode.get('pending_tool_calls', 0)}")
        lines.append(f"active_episode_last_progress: {active_episode.get('last_progress_at') or 'none'}")
        if active_episode.get("stall_reason"):
            lines.append(f"active_episode_stall_reason: {active_episode['stall_reason']}")
    if snapshot.get("last_error"):
        lines.append(f"last_error: {snapshot['last_error']}")
    if snapshot.get("current_rollover_reason"):
        lines.append(f"rollover_reason: {snapshot['current_rollover_reason']}")
    return "\n".join(lines) + "\n"


def format_tail(case: dict[str, Any], lines: int = 80) -> str:
    items: list[str] = []
    for filename in (SUPERVISOR_LOG_FILE, EVENTS_FILE):
        path = case["paths"]["runtime"] / filename
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").splitlines()
        tail = content[-lines:]
        items.append(f"## {filename}")
        items.extend(tail or ["(empty)"])
    ledger_tail = read_ledger_tail(case["case_dir"], limit=lines)
    if ledger_tail:
        items.append(f"## {LEDGER_FILE}")
        items.extend(ledger_tail.splitlines())
    return "\n".join(items).rstrip() + "\n"


def supervise_case(case: dict[str, Any], *, max_cycles: int | None = None) -> dict[str, Any]:
    state = case["state"]
    state["status"] = "running"
    state["stop_requested"] = bool(state.get("stop_requested", False))
    save_case_state(case, state)
    write_text(case["paths"]["pid"], str(os.getpid()))
    write_supervisor_metadata(case, pid=os.getpid(), command=[sys.executable, *sys.argv])
    append_supervisor_log(case, "supervisor start")

    def _request_stop(signum: int, _frame: Any) -> None:
        state["stop_requested"] = True
        state["status"] = "stopping"
        state["last_cycle_note"] = f"Signal {signum}"
        save_case_state(case, state)
        append_supervisor_log(case, f"signal received signum={signum}")

    def _request_interrupt(signum: int, _frame: Any) -> None:
        state["interrupt_requested"] = True
        state["interrupt_reason"] = f"signal:{signum}"
        save_case_state(case, state)
        append_supervisor_log(case, f"interrupt received signum={signum}")

    previous_int = signal.signal(signal.SIGINT, _request_stop)
    previous_term = signal.signal(signal.SIGTERM, _request_stop)
    previous_usr1 = signal.signal(signal.SIGUSR1, _request_interrupt) if hasattr(signal, "SIGUSR1") else None
    completed_cycles = 0
    try:
        while True:
            case = refresh_case_config(case)
            state = read_json(case["files"]["state"], state)
            case["state"] = state
            if state.get("interrupt_requested") and not state.get("active_episode"):
                state["interrupt_requested"] = False
                state["interrupt_reason"] = None
                save_case_state(case, state)
            if state.get("stop_requested"):
                state["status"] = "stopped"
                save_case_state(case, state)
                update_logbook(case, state, "Stop requested.")
                append_supervisor_log(case, "supervisor stopped by request")
                break
            if deadline_reached(case["config"].get("deadline")):
                state["status"] = "deadline_reached"
                state["last_cycle_note"] = "Deadline reached."
                save_case_state(case, state)
                update_logbook(case, state, "Deadline reached.")
                append_supervisor_log(case, "supervisor stopped because the deadline was reached")
                break

            fresh_thread, reason = should_start_fresh_thread(state, case["config"]["policy"])
            if fresh_thread:
                rollover_thread(case, state, reason)
                state = read_json(case["files"]["state"], state)
                case["state"] = state

            prompt = build_prompt(case, state)
            episode = run_episode(case, state, prompt, state.get("current_thread_id"))
            if not episode.thread_id and not episode.timed_out and not episode.stalled_guard_triggered:
                state["status"] = "error"
                state["last_error"] = episode.thread_resolution_error or "missing thread_id in episode output"
                save_case_state(case, state)
                update_logbook(case, state, "Fix the episode output before continuing.")
                append_supervisor_log(case, f"supervisor stopped because thread_id was missing error={state['last_error']}")
                break

            if episode.thread_id:
                if state.get("current_thread_id") != episode.thread_id:
                    if state.get("current_thread_id"):
                        finalize_thread_history(state, episode.finished_at)
                    state["current_thread_id"] = episode.thread_id
                    state["current_thread_started_at"] = episode.started_at
                    state["current_thread_episode_count"] = 0
                state["current_rollover_reason"] = None

            state["status"] = "running"
            state["last_episode_started_at"] = episode.started_at
            state["last_episode_finished_at"] = episode.finished_at
            state["last_episode_exit_code"] = episode.returncode
            state["last_episode_timed_out"] = episode.timed_out
            state["last_episode_stalled"] = episode.stalled_guard_triggered
            state["last_episode_stall_reason"] = episode.stall_reason
            state["last_episode_interrupted"] = episode.interrupted
            state["last_episode_interrupt_reason"] = episode.interrupt_reason
            state["interrupt_requested"] = False
            state["interrupt_reason"] = None
            state["total_episodes"] = int(state.get("total_episodes") or 0) + 1
            if episode.thread_id:
                state["current_thread_episode_count"] = int(state.get("current_thread_episode_count") or 0) + 1
            if episode.interrupted:
                state["last_cycle_note"] = f"Episode interrupted: {episode.interrupt_reason or 'unknown'}."
            elif episode.stalled_guard_triggered:
                state["last_cycle_note"] = f"Episode stalled: {episode.stall_reason}."
            else:
                state["last_cycle_note"] = "Episode complete."
            save_case_state(case, state)
            append_jsonl(
                case["case_dir"] / LEDGER_FILE,
                {
                    "type": "episode",
                    "at": episode.finished_at,
                    "returncode": episode.returncode,
                    "timed_out": episode.timed_out,
                    "completion_guard_triggered": episode.completion_guard_triggered,
                    "stalled_guard_triggered": episode.stalled_guard_triggered,
                    "stall_reason": episode.stall_reason,
                    "interrupted": episode.interrupted,
                    "interrupt_reason": episode.interrupt_reason,
                    "thread_id": episode.thread_id,
                    "current_thread_episode_count": state["current_thread_episode_count"],
                    "total_episodes": state["total_episodes"],
                    "command": episode.command,
                    "last_message": episode.last_message,
                    "prompt_path": episode.prompt_path,
                    "session_log_path": episode.session_log_path,
                    "last_event_type": episode.last_event_type,
                    "pending_tool_calls": episode.pending_tool_calls,
                    "last_progress_at": episode.last_progress_at,
                },
            )

            validator = run_validator(case)
            case = ensure_control_plane(case)
            state["last_validator_exit_code"] = validator.returncode
            state["last_validator_ok"] = validator.passed
            state["last_validator_started_at"] = validator.started_at
            state["last_validator_finished_at"] = validator.finished_at
            save_case_state(case, state)
            append_jsonl(
                case["case_dir"] / LEDGER_FILE,
                {
                    "type": "validator",
                    "at": validator.finished_at,
                    "returncode": validator.returncode,
                    "passed": validator.passed,
                },
            )

            if validator.passed:
                finalize_thread_history(state, state["last_episode_finished_at"])
                state["status"] = "completed"
                state["completed_at"] = iso_now()
                state["last_cycle_note"] = "Validator passed."
                save_case_state(case, state)
                update_logbook(case, state, "Mission complete.")
                append_supervisor_log(case, "supervisor completed successfully")
                break

            if deadline_reached(case["config"].get("deadline")):
                state["status"] = "deadline_reached"
                state["last_cycle_note"] = "Deadline reached after validation."
                save_case_state(case, state)
                update_logbook(case, state, "Deadline reached.")
                append_supervisor_log(case, "supervisor stopped because the deadline was reached")
                break

            if episode.stalled_guard_triggered:
                rollover_thread(case, state, f"stalled:{episode.stall_reason or 'unknown'}")
                update_logbook(
                    case,
                    state,
                    f"Start a fresh thread next cycle after stalled episode: {episode.stall_reason or 'unknown'}. Re-run interrupted checks and continue from repo state.",
                )
            elif episode.interrupted:
                rollover_thread(case, state, f"interrupt:{episode.interrupt_reason or 'unknown'}")
                update_logbook(
                    case,
                    state,
                    f"Start a fresh thread next cycle after directive interrupt: {episode.interrupt_reason or 'unknown'}.",
                )
            else:
                fresh_thread, reason = should_start_fresh_thread(state, case["config"]["policy"])
                if fresh_thread:
                    rollover_thread(case, state, reason)
                else:
                    update_logbook(case, state, "Continue on the current thread.")

            completed_cycles += 1
            if max_cycles is not None and completed_cycles >= max_cycles:
                append_supervisor_log(case, f"supervisor reached max_cycles={max_cycles}")
                break

        state = read_json(case["files"]["state"], state)
        case["state"] = state
        return status_snapshot(case)
    finally:
        clear_supervisor_runtime_identity(case, expected_pid=os.getpid())
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        if previous_usr1 is not None:
            signal.signal(signal.SIGUSR1, previous_usr1)


def spawn_supervisor(case: dict[str, Any]) -> dict[str, Any]:
    existing_pid = current_supervisor_pid(case)
    if existing_pid:
        state = read_json(case["files"]["state"], case["state"])
        case["state"] = state
        stop_latched = bool(state.get("stop_requested")) or state.get("status") == "stopping"
        if stop_latched:
            return {
                "ok": False,
                "blocked": True,
                "blocked_reason": "supervisor_stopping",
                "case_name": case["case_name"],
                "supervisor_pid": existing_pid,
                "supervisor_running": True,
                "status": state.get("status"),
                "stop_requested": bool(state.get("stop_requested")),
            }
        state = mutate_case_state(case, lambda current: current.__setitem__("status", "running"))
        update_logbook(case, state, "Supervisor already running.")
        return {
            "case_name": case["case_name"],
            "supervisor_pid": existing_pid,
            "status": "running",
            "already_running": True,
        }
    clear_supervisor_runtime_identity(case)

    if case["state"].get("stop_requested"):
        clear_stop_request(case)
        case = load_case(case["project_root"], case["case_name"])

    cmd = build_supervisor_command(case)
    log_handle = case["paths"]["log"].open("a", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=log_handle,
        start_new_session=True,
        env={**os.environ},
    )
    log_handle.close()
    write_text(case["paths"]["pid"], str(proc.pid))
    write_supervisor_metadata(case, pid=proc.pid, command=cmd)
    reap_detached_process(proc)
    append_supervisor_log(case, f"spawned supervisor pid={proc.pid}")
    state = mutate_case_state(case, lambda current: current.__setitem__("status", "running"))
    update_logbook(case, state, "Supervisor started.")
    return {"case_name": case["case_name"], "supervisor_pid": proc.pid, "status": "running"}


def update_case_codex_exec_args(case: dict[str, Any], codex_exec_args: Iterable[str]) -> dict[str, Any]:
    case["config"]["codex_exec_args"] = normalize_codex_exec_args(codex_exec_args)
    write_json(case["files"]["config"], case["config"])
    return case


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Long-running mission supervisor")
    parser.add_argument("--json", action="store_true", help="Print JSON output")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_json_flag(target: argparse.ArgumentParser) -> None:
        # Suppress the default so earlier --json flags are not overwritten by
        # nested subparsers that do not see an explicit flag.
        target.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    create = sub.add_parser("create", help="Create or reopen a case")
    add_json_flag(create)
    create.add_argument("--project-dir", default=".", help="Project root")
    create.add_argument("--case", required=True, help="Case name")
    create.add_argument("--goal", required=True, help="Mission goal")
    create.add_argument("--validator", required=True, help="Validator command")
    create.add_argument("--skill", action="append", default=[], help="Requested skill name")
    create.add_argument("--deadline", default=None, help="Absolute deadline in ISO-8601")
    create.add_argument("--duration-hours", type=float, default=None, help="Relative deadline in hours")
    create.add_argument("--duration-days", type=float, default=None, help="Relative deadline in days")
    create.add_argument("--codex-exec-arg", action="append", default=[], help="Extra flag to pass to each codex exec")
    create.add_argument("--episode-hard-cap-hours", type=float, default=DEFAULT_POLICY["episode_hard_cap_hours"])
    create.add_argument("--max-episodes-per-thread", type=int, default=DEFAULT_POLICY["max_episodes_per_thread"])
    create.add_argument("--max-thread-age-hours", type=float, default=DEFAULT_POLICY["max_thread_age_hours"])
    create.add_argument("--stall-guard-seconds", type=float, default=DEFAULT_POLICY["stall_guard_seconds"])
    create.add_argument("--tool-call-stall-seconds", type=float, default=DEFAULT_POLICY["tool_call_stall_seconds"])
    create.add_argument("--liveness-poll-seconds", type=float, default=DEFAULT_POLICY["liveness_poll_seconds"])

    start = sub.add_parser("start", help="Start the supervisor in the background")
    add_json_flag(start)
    start.add_argument("--project-dir", default=".", help="Project root")
    start.add_argument("--case", required=True, help="Case name")
    start.add_argument("--codex-exec-arg", action="append", default=[], help="Extra flag to persist for each codex exec")

    status = sub.add_parser("status", help="Show case status")
    add_json_flag(status)
    status.add_argument("--project-dir", default=".", help="Project root")
    status.add_argument("--case", required=True, help="Case name")

    note = sub.add_parser("note", help="Add a steering note")
    add_json_flag(note)
    note.add_argument("--project-dir", default=".", help="Project root")
    note.add_argument("--case", required=True, help="Case name")
    note.add_argument("--message", required=True, help="Note text")
    note.add_argument("--expires-at", default=None, help="Absolute note expiration in ISO-8601")
    note.add_argument("--expires-hours", type=float, default=None, help="Relative note expiration in hours")

    notes = sub.add_parser("notes", help="List active notes")
    add_json_flag(notes)
    notes.add_argument("--project-dir", default=".", help="Project root")
    notes.add_argument("--case", required=True, help="Case name")

    note_resolve = sub.add_parser("note-resolve", help="Resolve and archive an active note")
    add_json_flag(note_resolve)
    note_resolve.add_argument("--project-dir", default=".", help="Project root")
    note_resolve.add_argument("--case", required=True, help="Case name")
    note_resolve.add_argument("--id", required=True, help="Note id")
    note_resolve.add_argument("--reason", default=None, help="Resolution note")

    note_expire = sub.add_parser("note-expire", help="Expire and archive an active note immediately")
    add_json_flag(note_expire)
    note_expire.add_argument("--project-dir", default=".", help="Project root")
    note_expire.add_argument("--case", required=True, help="Case name")
    note_expire.add_argument("--id", required=True, help="Note id")
    note_expire.add_argument("--reason", default=None, help="Expiration note")

    directive = sub.add_parser("directive", help="Manage active directives")
    add_json_flag(directive)
    directive.add_argument("--project-dir", default=".", help="Project root")
    directive.add_argument("--case", required=True, help="Case name")
    directive_sub = directive.add_subparsers(dest="directive_command", required=True)

    directive_add = directive_sub.add_parser("add", help="Add an active directive")
    add_json_flag(directive_add)
    directive_add.add_argument("--summary", required=True, help="Directive summary")
    directive_add.add_argument("--payload-json", default="{}", help="Directive payload as JSON object")
    directive_add.add_argument("--payload-file", default=None, help="Path to a JSON payload file")
    directive_add.add_argument("--mode", default="directive", choices=["directive", "override"], help="Directive mode")
    directive_add.add_argument("--priority", default="normal", choices=["low", "normal", "high"], help="Directive priority")
    directive_add.add_argument(
        "--interrupt-policy",
        default="none",
        choices=["none", "immediate"],
        help="Whether to interrupt the active episode",
    )
    directive_add.add_argument("--supersede", action="append", default=[], help="Directive id to supersede")
    directive_add.add_argument("--expires-at", default=None, help="Absolute directive expiration in ISO-8601")
    directive_add.add_argument("--expires-hours", type=float, default=None, help="Relative directive expiration in hours")

    directive_list = directive_sub.add_parser("list", help="List active directives")
    add_json_flag(directive_list)

    directive_resolve = directive_sub.add_parser("resolve", help="Resolve an active directive")
    add_json_flag(directive_resolve)
    directive_resolve.add_argument("--id", required=True, help="Directive id")
    directive_resolve.add_argument("--reason", default=None, help="Resolution note")

    directive_expire = directive_sub.add_parser("expire", help="Expire an active directive")
    add_json_flag(directive_expire)
    directive_expire.add_argument("--id", required=True, help="Directive id")
    directive_expire.add_argument("--reason", default=None, help="Expiration note")

    directive_supersede = directive_sub.add_parser("supersede", help="Supersede an active directive")
    add_json_flag(directive_supersede)
    directive_supersede.add_argument("--id", required=True, help="Directive id")
    directive_supersede.add_argument("--replacement-id", required=True, help="Replacement directive id")
    directive_supersede.add_argument("--reason", default=None, help="Supersession note")

    override = sub.add_parser("override", help="Add an urgent override directive")
    add_json_flag(override)
    override.add_argument("--project-dir", default=".", help="Project root")
    override.add_argument("--case", required=True, help="Case name")
    override.add_argument("--summary", required=True, help="Override summary")
    override.add_argument("--payload-json", default="{}", help="Override payload as JSON object")
    override.add_argument("--payload-file", default=None, help="Path to a JSON payload file")
    override.add_argument("--supersede", action="append", default=[], help="Directive id to supersede")
    override.add_argument("--expires-at", default=None, help="Absolute override expiration in ISO-8601")
    override.add_argument("--expires-hours", type=float, default=None, help="Relative override expiration in hours")
    override.add_argument(
        "--interrupt-policy",
        default="immediate",
        choices=["none", "immediate"],
        help="Whether to interrupt the active episode",
    )

    stop = sub.add_parser("stop", help="Request a stop after the current cycle")
    add_json_flag(stop)
    stop.add_argument("--project-dir", default=".", help="Project root")
    stop.add_argument("--case", required=True, help="Case name")

    tail = sub.add_parser("tail", help="Show the latest log tail")
    add_json_flag(tail)
    tail.add_argument("--project-dir", default=".", help="Project root")
    tail.add_argument("--case", required=True, help="Case name")
    tail.add_argument("--lines", type=int, default=80, help="Number of lines to show")

    supervise = sub.add_parser("supervise", help=argparse.SUPPRESS)
    add_json_flag(supervise)
    supervise.add_argument("--project-dir", default=".", help="Project root")
    supervise.add_argument("--case", required=True, help="Case name")
    supervise.add_argument("--max-cycles", type=int, default=None, help=argparse.SUPPRESS)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "create":
        payload = create_case(
            project_dir=args.project_dir,
            case_name=args.case,
            goal=args.goal,
            validator=args.validator,
            skills=args.skill,
            deadline=args.deadline,
            duration_hours=args.duration_hours,
            duration_days=args.duration_days,
            codex_exec_args=args.codex_exec_arg,
            policy_overrides={
                "episode_hard_cap_hours": args.episode_hard_cap_hours,
                "max_episodes_per_thread": args.max_episodes_per_thread,
                "max_thread_age_hours": args.max_thread_age_hours,
                "stall_guard_seconds": args.stall_guard_seconds,
                "tool_call_stall_seconds": args.tool_call_stall_seconds,
                "liveness_poll_seconds": args.liveness_poll_seconds,
            },
        )
        if args.json:
            sys.stdout.write(to_json_text(payload))
        else:
            sys.stdout.write(f"created: {payload['created']}\ncase: {payload['case_name']}\n")
        return 0

    case = load_case(args.project_dir, args.case)
    if args.command == "start":
        if args.codex_exec_arg:
            case = update_case_codex_exec_args(case, args.codex_exec_arg)
            case = load_case(args.project_dir, args.case)
        payload = spawn_supervisor(case)
    elif args.command == "status":
        payload = status_snapshot(case)
    elif args.command == "note":
        payload = append_note(case, args.message, expires_at=compute_expiration(args.expires_at, args.expires_hours))
    elif args.command == "notes":
        payload = list_notes(case)
    elif args.command == "note-resolve":
        payload = resolve_note(case, args.id, reason=args.reason)
    elif args.command == "note-expire":
        payload = expire_note(case, args.id, reason=args.reason)
    elif args.command == "directive":
        if args.directive_command == "add":
            payload = add_directive(
                case,
                summary=args.summary,
                payload=load_payload_json(payload_json=args.payload_json, payload_file=args.payload_file),
                mode=args.mode,
                priority=args.priority,
                interrupt_policy=args.interrupt_policy,
                supersedes=args.supersede,
                expires_at=compute_expiration(args.expires_at, args.expires_hours),
            )
        elif args.directive_command == "list":
            payload = list_directives(case)
        elif args.directive_command == "resolve":
            payload = resolve_directive(case, args.id, reason=args.reason)
        elif args.directive_command == "expire":
            payload = expire_directive(case, args.id, reason=args.reason)
        elif args.directive_command == "supersede":
            payload = supersede_directive(case, args.id, replacement_id=args.replacement_id, reason=args.reason)
        else:
            raise AssertionError(args.directive_command)
    elif args.command == "override":
        payload = add_directive(
            case,
            summary=args.summary,
            payload=load_payload_json(payload_json=args.payload_json, payload_file=args.payload_file),
            mode="override",
            priority="high",
            interrupt_policy=args.interrupt_policy,
            supersedes=args.supersede,
            expires_at=compute_expiration(args.expires_at, args.expires_hours),
        )
    elif args.command == "stop":
        payload = request_stop(case)
    elif args.command == "tail":
        tail_text = format_tail(case, args.lines)
        if args.json:
            payload = {"case_name": case["case_name"], "tail": tail_text}
        else:
            sys.stdout.write(tail_text)
            return 0
    elif args.command == "supervise":
        payload = supervise_case(case, max_cycles=args.max_cycles)
    else:
        raise AssertionError(args.command)

    if args.json:
        sys.stdout.write(to_json_text(payload))
    else:
        if args.command == "status":
            sys.stdout.write(render_status(payload))
        elif args.command == "notes":
            sys.stdout.write(render_notes(payload["notes"]))
        elif args.command == "directive" and args.directive_command == "list":
            sys.stdout.write(render_directives(payload["directives"]))
        elif args.command == "tail":
            sys.stdout.write(payload["tail"])
        else:
            sys.stdout.write(f"{args.command}: ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
