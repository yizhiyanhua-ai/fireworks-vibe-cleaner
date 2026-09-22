#!/usr/bin/env python3
"""Real heterogeneous Jev comparison. Read-only sources; explicitly authorized metadata calls.

Supply the v0.4.0 Skill from a verified release as --baseline-skill. This tool
never fabricates files, timestamps, backup state, activity or user preferences.
Unknown preferences remain unknown; all outcomes remain non-executable advice.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import triage  # noqa: E402
from vibe_cleaner.common import Refused, candidate_fd, digest, file_hash, load, write  # noqa: E402


def baseline(path: Path):
    spec = importlib.util.spec_from_file_location("vibe_cleaner_v04", path / "vibe_cleaner/__init__.py",
                                                 submodule_search_locations=[str(path / "vibe_cleaner")])
    if spec is None or spec.loader is None:
        raise Refused("Choose a verified v0.4.0 Skill distribution")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.__version__ != "0.4.0":
        raise Refused("Comparison baseline must be v0.4.0")
    return importlib.import_module("vibe_cleaner_v04.triage")


def hashes(items: list[dict]) -> dict:
    values = {}
    for item in items:
        try:
            with candidate_fd(item) as fd:
                values[item["id"]] = file_hash(fd)
        except (Refused, OSError):
            values[item["id"]] = None
    return values


def public_run(name: str, result: dict, packet) -> dict:
    decisions = []
    for n, row in enumerate(result["decisions"], 1):
        # Exactly the primitive's metadata allowlist, never local proof paths or IDs.
        facts = packet([row])["state"]["candidates"][0]
        decisions.append({"sample": n, "facts": facts,
                          **{k: row[k] for k in ("action", "reason_code", "source", "provider_choice", "confidence")}})
    return {"name": name, "timing": result["timing"], "provider": result["provider"],
            "fact_patterns": len({json.dumps(d["facts"], sort_keys=True) for d in decisions}),
            "action_counts": dict(Counter(d["action"] for d in decisions)),
            "raw_choice_counts": dict(Counter(d["provider_choice"] for d in decisions if d["provider_choice"])),
            "decisions": decisions}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scan", type=Path, required=True)
    p.add_argument("--archive", type=Path, action="append", default=[])
    p.add_argument("--verify-backup-bytes", type=int, default=0)
    p.add_argument("--recovery-need", choices=sorted(triage.triage_evidence.RECOVERY_NEEDS), default="unknown")
    p.add_argument("--goal", choices=sorted(triage.GOALS), default="balanced")
    p.add_argument("--baseline-skill", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--enable-network", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--public-output", type=Path, required=True)
    args = p.parse_args()
    inv = load(args.scan)
    if not args.enable_network or not 1 <= args.repeats <= 3 or not 1 <= len(inv["items"]) <= 24:
        raise Refused("Authorize network/costs explicitly; select 1..24 existing files and 1..3 repetitions")
    if args.output.exists() or args.public_output.exists():
        raise Refused("Choose new output files")
    old = baseline(args.baseline_skill)
    details = {}
    started = time.monotonic()
    rows = triage.evidence(inv["items"], inv, archives=args.archive, max_verify_bytes=args.verify_backup_bytes,
                           inspect_activity=True, recovery_need=args.recovery_need, details=details)
    collect_ms = round((time.monotonic() - started) * 1000)
    if details["distinct_fact_patterns"] < 3:
        raise Refused("This sample lacks heterogeneous evidence; do not present it as a diverse evaluation")
    reviewable_ids = {r["id"] for r in rows if not r["facts"]["protected"]}
    stable_items = [i for i in inv["items"] if i["id"] in reviewable_ids]
    before = hashes(stable_items)
    baseline_result = old.run(inv, [i["id"] for i in inv["items"]], goal=args.goal, enabled=True)
    private_runs = []
    public_runs = [public_run("v0.4.0-baseline", baseline_result, old.packet)]
    for number in range(args.repeats):
        start = time.monotonic()
        decision = triage.decide(rows, goal=args.goal, enabled=True)
        inference_ms = round((time.monotonic() - start) * 1000)
        run = {**decision, "timing": {"fact_collection_ms": collect_ms, "inference_ms": inference_ms,
                                      "collection_plus_inference_ms": collect_ms + inference_ms,
                                      "total_ms": collect_ms + inference_ms},
               "selected_files": len(rows), "selected_logical_bytes": sum(r["size_bytes"] for r in rows),
               "selection": "explicit-real-subset", "not_selected_files": 0, "scan_complete": False,
               "confidence_floor": triage.CONFIDENCE_FLOOR, "executable": False}
        private_runs.append(run)
        public_runs.append(public_run(f"evidence-repeat-{number + 1}", run, triage.packet))
        if set(run["provider"]["statuses"]) - {"ok"}:
            break
    after = hashes(stable_items)
    write(args.output, {"rows": rows, "details": details, "baseline": baseline_result, "runs": private_runs,
                        "hashes_before": before, "hashes_after": after})
    statuses = Counter(d["facts"]["backup_status"] for d in public_runs[-1]["decisions"])
    total_input = sum(r["provider"]["input_tokens"] for r in public_runs)
    request_rows = [r for r in rows if not r["facts"]["protected"]]
    requests = [triage.packet(request_rows[n:n + triage.BATCH_SIZE], args.goal)
                for n in range(0, len(request_rows), triage.BATCH_SIZE)]
    report = {"schema": 1, "data": "real-jev-evidence", "date": datetime.now(timezone.utc).date().isoformat(),
              "date_basis": "UTC", "real_user_data_modified": False, "source_mutations_executed": False,
              "transport_mocked": False, "artificial_files_or_timestamps": False,
              "source_files": len(rows), "source_logical_bytes": sum(r["size_bytes"] for r in rows),
              "goal": args.goal, "recovery_need": args.recovery_need, "evidence": details,
              "backup_status_counts": dict(statuses), "new_request_sha256": [digest(r) for r in requests],
              "network_calls": sum(r["provider"]["calls"] for r in public_runs), "runs": public_runs,
              "verified_stable_file_count": sum(value is not None and value == after[key] for key, value in before.items()),
              "hash_checked_files": len(stable_items), "protected_or_dynamic_files_not_hashed": len(rows) - len(stable_items),
              "all_hash_checked_sources_unchanged": all(value is not None and value == after[key] for key, value in before.items()),
              "actual_reclaimed_bytes": 0, "no_accuracy_claim": True, "human_labels_available": False,
              "input_tokens": total_input, "estimated_input_cost_usd": round(total_input * 0.042 / 1_000_000, 9),
              "price_per_million_input_usd": 0.042, "price_source": "https://docs.typesafe.ai/models",
              "billing_statement_verified": False,
              "measurement_scope": "Same existing selected files for baseline and enriched advice. Fresh evidence is collected once; new repetitions reuse exactly the same prepared facts/requests. Selected backup source+member hashing is included in collection time; extra before/after source hashes, inventory selection and full scans are excluded. No full ZIP hash or native resume verification.",
              "limits": ["No labeled semantic ground truth; policy compliance is not model accuracy.",
                         "User recovery preferences are not inferred; unknown disables removal preparation.",
                         "A selected-index snapshot cannot prove global lineage completeness.",
                         "No source removal, UI continuity or disk recovery was tested."]}
    write(args.public_output, report)
    for run in public_runs:
        print(json.dumps({"run": run["name"], "timing": run["timing"], "facts": run["fact_patterns"],
                          "actions": run["action_counts"], "statuses": run["provider"]["statuses"]}))
    print(json.dumps({"network_calls": report["network_calls"], "backup_statuses": dict(statuses),
                      "stable_file_hashes_unchanged": report["all_hash_checked_sources_unchanged"],
                      "hash_checked_files": len(stable_items), "reclaimed_bytes": 0}))


if __name__ == "__main__":
    main()
