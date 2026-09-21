"""Optional TypeSafe advisor. Sends allowlisted metadata, never filesystem content."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .common import Json, Refused, candidate_fd
from .engine import idle_check, validate_candidate
from .scan import classify

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
METHODS = {"keep", "review", "backup", "delete"}


def local_evidence(items: list[Json], inventory: Json, *, inspect_activity: bool = False) -> list[Json]:
    """Recheck local eligibility; a no-open-handles snapshot is not stopped-writer proof."""
    rows = []
    for original in items:
        item = dict(original)
        item.update(active_state="unknown", local_policy_checked=False, backup_eligible=False,
                    eligible=False, retention_met=False)
        try:
            category, _ = classify(Path(item["root"]), item["relative"], item["adapter"])
            if category != item["category"]:
                raise Refused("Classification changed")
            with candidate_fd(item):
                pass
            kept = any((Path(item["root"]) / item["relative"]).match(p) for p in inventory.get("keep", []))
            if kept or item["identity"]["nlink"] != 1:
                raise Refused("Kept or hardlinked candidate")
            item["backup_eligible"] = category in {"session", "checkpoint", "asset"}
            item["retention_met"] = (inventory["min_age_days"] >= 1 and
                                     (time.time_ns() - item["identity"]["mtime_ns"]) / 86400e9 >= inventory["min_age_days"])
            if category in {"log", "bytecode"}:
                validate_candidate(original, inventory["min_age_days"], inventory.get("keep", []))
                item.update(eligible=True, retention_met=True)
            item["local_policy_checked"] = True
            if inspect_activity:
                try:
                    idle_check([item])
                    item["active_state"] = "no_open_handles"
                except (Refused, OSError, subprocess.TimeoutExpired):
                    item["active_state"] = "open_or_unknown"
        except (Refused, OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            item.update(eligible=False, backup_eligible=False)
        rows.append(item)
    return rows


def packet(items: list[Json]) -> Json:
    if not 1 <= len(items) <= 20:
        raise Refused("Jev accepts 1..20 candidates per bounded call")
    candidates = []
    for n, item in enumerate(items):
        # Do not copy paths, names, free text reasons, or IDs derived from real paths.
        category = item.get("category")
        if category not in {"log", "bytecode", "session", "checkpoint", "asset", "worktree", "protected"}:
            category = "protected"
        activity = item.get("active_state", "unknown")
        if activity not in {"unknown", "no_open_handles", "open_or_unknown"}:
            activity = "unknown"
        actions = ["keep", "review"]
        if (category in {"session", "checkpoint", "asset"} and activity != "open_or_unknown"
                and item.get("backup_eligible") and item.get("local_policy_checked")):
            actions.append("backup")
        if (category in {"log", "bytecode"} and item.get("eligible") and item.get("retention_met")
                and item.get("local_policy_checked") and activity == "no_open_handles"):
            actions.append("delete")
        candidates.append({"candidate": f"c{n}", "category": category,
                           "size_band": "large" if item["identity"]["size"] >= 1024**2 else "small",
                           "age_band": "old" if item.get("age_days", 0) >= 30 else "recent",
                           "rule_eligible": bool(item.get("eligible")),
                           "active_state": activity, "allowed_actions": actions,
                           "retention_met": bool(item.get("retention_met")),
                           "local_policy_checked": bool(item.get("local_policy_checked"))})
    questions = {}
    for n in range(len(candidates)):
        questions[f"c{n}"] = {
            "type": "choice",
            "instructions": f"For state.candidates[{n}] only, recommend one allowed action. "
                            "Advice never authorizes execution. Human approval and fresh local checks are required. "
                            "No-open-handles is only a snapshot; metadata may be incomplete. Choose review if uncertain.",
            "criteria": {action: {
                "keep": "Retain; protected or no further action justified",
                "review": "Insufficient evidence; ask the human to review ownership and recovery needs",
                "backup": "Back up and verify; any later transcript removal needs a separate approved archive plan",
                "delete": "Suggest quarantine then separately approved purge of eligible logs/caches, without a backup",
            }[action] for action in candidates[n]["allowed_actions"]},
        }
    return {"model": "jev-latest", "state": {"candidates": candidates}, "questions": questions}


def validate_response(data: Any, request: Json) -> Json:
    if (not isinstance(data, dict) or not isinstance(data.get("model"), str)
            or not re.fullmatch(r"jev-[A-Za-z0-9._-]{1,64}", data["model"])):
        raise Refused("Unexpected provider model")
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(request["questions"]):
        raise Refused("Provider candidate IDs mismatch")
    sanitized = {}
    for key, answer in answers.items():
        allowed = set(request["questions"][key]["criteria"])
        if not isinstance(answer, dict) or answer.get("type") != "choice" or answer.get("choice") not in allowed:
            raise Refused("Invalid or forbidden advisor action")
        p = answer.get("probabilities")
        if not isinstance(p, dict) or set(p) != allowed:
            raise Refused("Invalid probability keys")
        values = [*p.values(), answer.get("confidence")]
        if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise Refused("Invalid probability/confidence range")
        if abs(sum(p.values()) - 1) > 0.001:
            raise Refused("Probabilities do not sum to one")
        if p[answer["choice"]] < max(p.values()):
            raise Refused("Choice does not match the highest probability")
        sanitized[key] = {"type": "choice", "choice": answer["choice"], "probabilities": p,
                          "confidence": answer["confidence"]}
    usage = data.get("usage")
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                                           for k in ("input_tokens", "output_tokens")):
        raise Refused("Invalid provider usage")
    return {"model": data["model"], "answers": sanitized,
            "usage": {k: usage[k] for k in ("input_tokens", "output_tokens")}}


def advise(items: list[Json], *, enabled: bool = False,
           transport: Callable[[urllib.request.Request, float], Any] | None = None) -> Json:
    if not enabled:
        return {"status": "disabled", "mode": "rules-only", "calls": 0}
    if not os.getenv("TYPESAFE_API_KEY"):
        return {"status": "missing-key", "mode": "rules-only", "calls": 0}
    return request_advice(packet(items), enabled=enabled, transport=transport)


def request_advice(request: Json, *, enabled: bool = False,
                   transport: Callable[[urllib.request.Request, float], Any] | None = None) -> Json:
    """One bounded typed request; never retries or invokes an executor."""
    if not enabled:
        return {"status": "disabled", "mode": "rules-only", "calls": 0}
    key = os.getenv("TYPESAFE_API_KEY")
    if not key:
        return {"status": "missing-key", "mode": "rules-only", "calls": 0}
    raw = json.dumps(request).encode()
    if len(raw) > 16384:
        raise Refused("Provider payload exceeds 16 KiB cap")
    req = urllib.request.Request(ENDPOINT, data=raw,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    started = time.monotonic()
    try:
        if transport:
            data = transport(req, 8.0)
        else:
            # Do not forward credentials to redirected hosts; no automatic retries.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                    return None
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=8) as response:
                body = response.read(65537)
                if len(body) > 65536:
                    raise Refused("Oversize provider response")
                data = json.loads(body)
        validated = validate_response(data, request)
        return {"status": "ok", "mode": "advisory-only", "calls": 1,
                "elapsed_ms": round((time.monotonic() - started) * 1000), **validated}
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        return {"status": f"http-{code}", "mode": "rules-only", "calls": 1}
    except (OSError, ValueError, Refused):
        return {"status": "unavailable-or-invalid", "mode": "rules-only", "calls": 1}
