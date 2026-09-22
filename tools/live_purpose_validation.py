#!/usr/bin/env python3
"""Opt-in real-data comparison: rules, metadata-only Jev, and source-bound purpose Jev.

Sources are existing files. Notes are frozen before calls; no labels are fabricated.
Local assistant labels are not human ground truth. No cleanup is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import purpose, triage  # noqa: E402
from vibe_cleaner.common import Refused, candidate_fd, digest, file_hash, load, write  # noqa: E402


def source_hashes(items):
    result = {}
    for item in items:
        with candidate_fd(item) as fd:
            result[item["id"]] = file_hash(fd)
    return result


def public_run(name, result, collection_ms, inference_ms):
    decisions = [{"sample": n, "facts": triage.packet([d])["state"]["candidates"][0],
                  **{k: d[k] for k in ("action", "reason_code", "source", "provider_choice", "confidence", "next_checks")}}
                 for n, d in enumerate(result["decisions"], 1)]
    return {"name": name, "collection_ms": collection_ms, "inference_ms": inference_ms,
            "collection_plus_inference_ms": collection_ms + inference_ms, "provider": result["provider"],
            "actions": dict(Counter(d["action"] for d in decisions)),
            "reasons": dict(Counter(d["reason_code"] for d in decisions)),
            "tentative_suggestions": sum(d["source"] == "jev-tentative" for d in decisions), "decisions": decisions}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scan", type=Path, required=True)
    p.add_argument("--purpose-notes", type=Path, required=True)
    p.add_argument("--archive", type=Path, action="append", default=[])
    p.add_argument("--verify-backup-bytes", type=int, default=0)
    p.add_argument("--enable-network", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--public-output", type=Path, required=True)
    a = p.parse_args()
    inv, notes = load(a.scan), purpose.load_notes(a.purpose_notes)
    if not a.enable_network or not 1 <= len(inv["items"]) <= 24 or a.output.exists() or a.public_output.exists():
        raise Refused("Explicit network authorization, 1..24 real selected files and new outputs required")
    sets, summaries, times = {}, {}, {}
    for key, enable, local_notes in (("metadata", False, None), ("purpose", True, notes)):
        details = {}
        start = time.monotonic()
        sets[key] = triage.evidence(inv["items"], inv, archives=a.archive, max_verify_bytes=a.verify_backup_bytes,
                                   inspect_activity=True, inspect_purpose=enable, purpose_notes=local_notes, details=details)
        times[key] = round((time.monotonic() - start) * 1000)
        summaries[key] = details
    annotated = sum(r["facts"]["purpose_origin"] != "unreviewed" for r in sets["purpose"])
    if annotated < 1:
        raise Refused("No reviewed local purpose tags; this is not a purpose comparison")
    requests = {}
    for key, rows in sets.items():
        candidates = [r for r in rows if not r["facts"]["protected"]]
        requests[key] = [triage.packet(candidates[n:n + triage.BATCH_SIZE]) for n in range(0, len(candidates), triage.BATCH_SIZE)]
    if len(requests["metadata"]) + 2 * len(requests["purpose"]) > 6:
        raise Refused("Comparison exceeds six-call cap")
    frozen_hash = digest({"requests": requests, "notes": notes})
    safe_ids = {r["id"] for r in sets["metadata"] if not r["facts"]["protected"]}
    stable = [i for i in inv["items"] if i["id"] in safe_ids]
    before = source_hashes(stable)
    public, private = [], []
    for name, key, use_model in (("rules-with-purpose", "purpose", False), ("jev-metadata", "metadata", True),
                                  ("jev-purpose-1", "purpose", True), ("jev-purpose-2", "purpose", True)):
        start = time.monotonic()
        result = triage.decide(sets[key], enabled=True) if use_model else triage.rules(sets[key])
        ms = round((time.monotonic() - start) * 1000)
        private.append({"name": name, "result": result})
        public.append(public_run(name, result, times[key], ms))
        if use_model and set(result["provider"]["statuses"]) - {"ok"}:
            break  # Preserve failed attempts; never silently retry or tune on results.
    after = source_hashes(stable)
    assert frozen_hash == digest({"requests": requests, "notes": notes})
    write(a.output, {"sets": sets, "notes": notes, "runs": private, "hashes_before": before, "hashes_after": after})
    tokens = sum(r["provider"]["input_tokens"] for r in public)
    report = {"schema": 1, "data": "real-purpose-comparison", "date": datetime.now(timezone.utc).date().isoformat(),
              "real_user_data_modified": False, "source_mutations_executed": False, "transport_mocked": False,
              "source_files": len(inv["items"]), "source_logical_bytes": sum(i["identity"]["size"] for i in inv["items"]),
              "recovery_need": "unknown", "evidence": summaries, "purpose_annotated_files": annotated,
              "annotation_origins": dict(Counter(r["facts"]["purpose_origin"] for r in sets["purpose"])),
              "request_sha256": {k: [digest(r) for r in v] for k, v in requests.items()},
              "frozen_requests_and_notes_sha256": frozen_hash, "runs": public,
              "network_calls": sum(r["provider"]["calls"] for r in public), "network_call_cap": 6,
              "input_tokens": tokens, "known_input_cost_estimate_usd": round(tokens * 0.042 / 1_000_000, 9),
              "price_source": "https://docs.typesafe.ai/models", "billing_statement_verified": False,
              "failed_call_usage_may_be_unknown": any(r["provider"]["errors"] for r in public),
              "all_hash_checked_sources_unchanged": before == after, "hash_checked_files": len(stable),
              "protected_or_dynamic_files_not_hashed": len(inv["items"]) - len(stable),
              "actual_reclaimed_bytes": 0, "no_cleanup_authorization": True,
              "no_accuracy_claim": True, "human_labels_available": False,
              "limits": ["Purpose annotations are local-assistant inferences from bounded text, not user ground truth.",
                         "No raw source content or annotation prose was sent to Jev; only closed purpose tags.",
                         "Rule agreement is not accuracy. No semantic advantage over the local annotator is established.",
                         "Purpose annotation preparation and before/after source hashes are outside timing; annotation time/cost was not measured.",
                         "Frozen repeated inputs show only observed consistency; no general reliability or speed claim.",
                         "No real cleanup, native resume, eligible cache deletion, Claude transcript or visual-media understanding was tested."]}
    if len(public) == 4:
        report["purpose_repeat_reason_agreement"] = sum(a["reason_code"] == b["reason_code"] for a, b in zip(public[2]["decisions"], public[3]["decisions"]))
        report["rules_purpose_reason_agreement"] = sum(a["reason_code"] == b["reason_code"] for a, b in zip(public[0]["decisions"], public[2]["decisions"]))
    write(a.public_output, report)
    for run in public:
        print(json.dumps({k: run[k] for k in ("name", "collection_ms", "inference_ms", "actions", "reasons", "tentative_suggestions")}))
    print(json.dumps({"network_calls": report["network_calls"], "unchanged": before == after, "reclaimed_bytes": 0}))


if __name__ == "__main__":
    main()
