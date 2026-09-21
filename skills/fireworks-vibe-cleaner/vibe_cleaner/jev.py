"""Optional TypeSafe advisor. Sends allowlisted metadata, never filesystem content."""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .common import Json, Refused

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
METHODS = {"keep", "review", "backup"}


def packet(items: list[Json]) -> Json:
    if not 1 <= len(items) <= 20:
        raise Refused("Jev accepts 1..20 candidates per bounded call")
    candidates = []
    for n, item in enumerate(items):
        # Do not copy paths, names, free text reasons, or IDs derived from real paths.
        category = item.get("category")
        if category not in {"log", "bytecode", "session", "checkpoint", "asset", "worktree", "protected"}:
            category = "protected"
        candidates.append({"candidate": f"c{n}", "category": category,
                           "size_band": "large" if item["identity"]["size"] >= 1024**2 else "small",
                           "age_band": "old" if item.get("age_days", 0) >= 30 else "recent",
                           "rule_eligible": bool(item.get("eligible")),
                           "active_state": "unknown"})
    questions = {}
    for n in range(len(candidates)):
        questions[f"c{n}"] = {
            "type": "choice",
            "instructions": f"For state.candidates[{n}] only, choose a next review step. "
                            "No deletion is allowed. Active state is unknown. Metadata is incomplete.",
            "criteria": {"keep": "Retain; no further action justified",
                         "review": "Request human review of ownership and recovery evidence",
                         "backup": "Consider a private verified copy, retaining originals"},
        }
    return {"model": "jev-latest", "state": {"candidates": candidates}, "questions": questions}


def validate_response(data: Any, request: Json) -> Json:
    if not isinstance(data, dict) or not isinstance(data.get("model"), str) or not data["model"].startswith("jev-"):
        raise Refused("Unexpected provider model")
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(request["questions"]):
        raise Refused("Provider candidate IDs mismatch")
    for answer in answers.values():
        if not isinstance(answer, dict) or answer.get("type") != "choice" or answer.get("choice") not in METHODS:
            raise Refused("Invalid or forbidden advisor action")
        p = answer.get("probabilities")
        if not isinstance(p, dict) or set(p) != METHODS:
            raise Refused("Invalid probability keys")
        values = [*p.values(), answer.get("confidence")]
        if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise Refused("Invalid probability/confidence range")
        if abs(sum(p.values()) - 1) > 0.001:
            raise Refused("Probabilities do not sum to one")
    usage = data.get("usage")
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                                           for k in ("input_tokens", "output_tokens")):
        raise Refused("Invalid provider usage")
    return {"model": data["model"], "answers": answers,
            "usage": {k: usage[k] for k in ("input_tokens", "output_tokens")}}


def advise(items: list[Json], *, enabled: bool = False,
           transport: Callable[[urllib.request.Request, float], Any] | None = None) -> Json:
    if not enabled:
        return {"status": "disabled", "mode": "rules-only", "calls": 0}
    key = os.getenv("TYPESAFE_API_KEY")
    if not key:
        return {"status": "missing-key", "mode": "rules-only", "calls": 0}
    request = packet(items)
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
