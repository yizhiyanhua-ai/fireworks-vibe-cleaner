"""Bounded local purpose evidence. Raw content and locators never enter a provider packet.

Recorded turn/plan events are observations, not proof that a project is complete.
Optional human/host annotations are source-bound judgments, never cleanup approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .common import Json, Refused, candidate_fd, digest, load

WINDOW_BYTES = 32768
MAX_FILES = 100
PARSER = "purpose-v1"
ROLES = {"unknown", "knowledge-reference", "implementation-history", "delivery-record", "diagnostic-history", "generated-draft", "deliverable"}
ORIGINS = {"unreviewed", "local-assistant", "user"}
CONTINUATION = {"unknown", "needed"}
TURN_EVENTS = {"unknown", "completion-event-seen", "interruption-event-seen", "start-event-seen"}
PLAN_EVENTS = {"unknown", "pending-plan-seen", "completed-plan-seen"}
COVERAGE = {"not-read", "full", "head-tail", "partial", "unavailable"}


def _records(block: bytes, offset: int, total: int):
    """Ignore partial boundary lines; never decode or emit a free-text excerpt."""
    cursor = 0
    if offset:
        end = block.find(b"\n")
        if end < 0:
            return
        cursor = end + 1
    for line in block[cursor:].splitlines(keepends=True):
        at = offset + cursor
        cursor += len(line)
        if not line.endswith(b"\n") and at + len(line) != total:
            continue
        if len(line) > WINDOW_BYTES:
            yield None, at, len(line), None
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            yield None, at, len(line), None
            continue
        yield record, at, len(line), hashlib.sha256(line).hexdigest()


def _event(record: Json, adapter: str) -> tuple[str | None, str | None]:
    turn, plan = None, None
    payload = record.get("payload")
    if adapter == "codex" and record.get("type") == "event_msg" and isinstance(payload, dict):
        event_type = payload.get("type")
        turn = {"task_complete": "completion-event-seen", "task_started": "start-event-seen",
                "turn_aborted": "interruption-event-seen"}.get(event_type) if isinstance(event_type, str) else None
    if adapter == "claude" and record.get("type") == "assistant":
        message = record.get("message")
        if (isinstance(message, dict) and message.get("role", "assistant") == "assistant"
                and message.get("stop_reason") == "end_turn"):
            turn = "completion-event-seen"
    # A recorded plan is a model/tool assertion. It is not business acceptance.
    if adapter == "codex" and record.get("type") == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "function_call" and payload.get("name") == "update_plan":
            arguments = payload.get("arguments")
            try:
                data = json.loads(arguments) if isinstance(arguments, str) else arguments
            except (ValueError, RecursionError):
                data = None
            steps = data.get("plan") if isinstance(data, dict) else None
            if isinstance(steps, list) and 1 <= len(steps) <= 100 and all(isinstance(s, dict) for s in steps):
                states = [s.get("status") for s in steps]
                if all(s in ("pending", "in_progress", "completed") for s in states):
                    plan = "pending-plan-seen" if any(s != "completed" for s in states) else "completed-plan-seen"
    return turn, plan


def inspect(item: Json, *, read_session: bool = True) -> Json:
    card: Json = {"parser": PARSER, "source_identity": item["identity"], "coverage": "not-read", "bytes_read": 0,
                  "records_read": 0, "invalid_records": 0, "turn_event": "unknown", "plan_event": "unknown",
                  "locators": {}, "windows": [], "role": "unknown", "continuation": "unknown",
                  "annotation_origin": "unreviewed", "project_completion": "unverified"}
    try:
        with candidate_fd(item) as fd:
            size = item["identity"]["size"]
            if read_session and item["category"] == "session" and item["adapter"] in {"codex", "claude"}:
                starts = [0] if size <= 2 * WINDOW_BYTES else [0, size - WINDOW_BYTES]
                for start in starts:
                    length = size if len(starts) == 1 else WINDOW_BYTES
                    block = os.pread(fd, length, start)
                    if len(block) != length:
                        raise Refused("Incomplete purpose read")
                    card["bytes_read"] += len(block)
                    card["windows"].append({"offset": start, "length": len(block), "sha256": hashlib.sha256(block).hexdigest()})
                    for record, offset, count, sha in _records(block, start, size):
                        if record is None:
                            card["invalid_records"] += 1
                            continue
                        card["records_read"] += 1
                        turn, plan = _event(record, item["adapter"])
                        for key, value in (("turn_event", turn), ("plan_event", plan)):
                            if value and not (key == "plan_event" and card[key] == "pending-plan-seen"):
                                card[key] = value
                                card["locators"][key] = {"offset": offset, "length": count, "sha256": sha}
                card["coverage"] = "partial" if card["invalid_records"] else "full" if len(starts) == 1 else "head-tail"
        with candidate_fd(item):
            pass
    except (Refused, OSError, ValueError, TypeError):
        card.update(coverage="unavailable", turn_event="unknown", plan_event="unknown", windows=[], locators={})
    card["source_binding"] = digest({"parser": PARSER, "identity": item["identity"], "windows": card["windows"]})
    return card


def collect(items: list[Json], protected_ids: set[str], *, notes: Json | None = None, enabled: bool = True) -> dict[str, Json]:
    if len(items) > MAX_FILES:
        raise Refused("Purpose evidence accepts at most 100 selected files")
    cards = {i["id"]: inspect(i, read_session=enabled and i["id"] not in protected_ids) for i in items}
    if notes is None:
        return cards
    if notes.get("schema") != 1 or notes.get("kind") != "purpose-notes" or not isinstance(notes.get("notes"), list):
        raise Refused("Unsupported purpose notes schema")
    if len(notes["notes"]) > MAX_FILES:
        raise Refused("Too many purpose notes")
    seen = set()
    for note in notes["notes"]:
        if not isinstance(note, dict) or not isinstance(note.get("id"), str) or note["id"] in seen:
            raise Refused("Malformed or duplicate purpose note")
        seen.add(note["id"])
        if set(note) != {"id", "source_binding", "role", "continuation", "origin"}:
            raise Refused("Purpose notes only accept the documented closed fields")
        if (not all(isinstance(note[k], str) for k in ("role", "continuation", "origin", "source_binding"))
                or note["role"] not in ROLES or note["continuation"] not in CONTINUATION or note["origin"] not in ORIGINS):
            raise Refused("Invalid purpose note enum")
        if note["origin"] == "unreviewed" and (note["role"] != "unknown" or note["continuation"] != "unknown"):
            raise Refused("A purpose judgment must declare its human or local-assistant origin")
        card = cards.get(note["id"])
        if card is None:
            continue
        if card["coverage"] == "unavailable" or note["source_binding"] != card["source_binding"]:
            raise Refused("Purpose note is stale or source is unavailable; review a fresh template")
        card.update(role=note["role"], continuation=note["continuation"], annotation_origin=note["origin"])
    return cards


def load_notes(path: Path | None) -> Json | None:
    if path is None:
        return None
    if path.stat().st_size > 256 * 1024:
        raise Refused("Purpose notes exceed 256 KiB")
    return load(path)


def template(rows: list[Json]) -> Json:
    return {"schema": 1, "kind": "purpose-notes", "notes": [
        {"id": r["id"], "source_binding": r["purpose_evidence"]["source_binding"],
         "role": "unknown", "continuation": "unknown", "origin": "unreviewed"} for r in rows
        if not r["facts"]["protected"] and r["purpose_evidence"]["coverage"] != "unavailable"],
        "instructions": "Private local judgments only. Fill role/continuation/origin after reviewing the exact source. Never mark an assistant judgment as user-confirmed. No field authorizes cleanup."}


def provider_facts(card: Json) -> Json:
    """Rebuild a closed allowlist; no paths, IDs, hashes, locators or free text."""
    values = {"purpose_role": ("role", ROLES), "purpose_origin": ("annotation_origin", ORIGINS),
              "continuation": ("continuation", CONTINUATION), "purpose_coverage": ("coverage", COVERAGE),
              "turn_event": ("turn_event", TURN_EVENTS), "plan_event": ("plan_event", PLAN_EVENTS)}
    result: dict[str, Any] = {}
    for key, (source, allowed) in values.items():
        value = card.get(source)
        result[key] = value if isinstance(value, str) and value in allowed else "unknown"
    return result


def keep_needed(facts: Json) -> bool:
    return facts.get("continuation") == "needed"


def next_checks(facts: Json) -> list[str]:
    """Concrete missing checks, independent of model prose or cleanup authority."""
    if facts.get("protected") or keep_needed(facts):
        return ["retain-and-resolve-protection"]
    checks = []
    if facts.get("plan_event") == "pending-plan-seen":
        checks.append("review-observed-pending-plan-before-removal")
    if facts.get("backup_status") == "manifest_only":
        checks.append("verify-existing-backup-bytes")
    if facts.get("purpose_role", "unknown") == "unknown":
        checks.append("review-local-purpose")
    if facts.get("category") == "session" and facts.get("recovery_need") == "unknown":
        checks.append("ask-resume-or-file-copy-before-removal")
    if facts.get("category") in {"asset", "checkpoint"}:
        checks.append("check-project-references-before-any-removal")
    if facts.get("activity") in {"unknown", "not_checked"}:
        checks.append("refresh-open-handle-check-before-cleanup")
    return checks
