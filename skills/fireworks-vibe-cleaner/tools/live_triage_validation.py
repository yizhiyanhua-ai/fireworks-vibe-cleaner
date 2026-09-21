#!/usr/bin/env python3
"""Opt-in, real provider serial/concurrent comparison on a selected private scan.

Sources are read only. Reports under --output remain private; --public-output
contains aggregate timings and anonymous decisions, with no source paths/IDs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import triage  # noqa: E402
from vibe_cleaner.common import Refused, candidate_fd, file_hash, load, write  # noqa: E402


def hashes(inventory: dict) -> list[str]:
    result = []
    for item in inventory["items"]:
        with candidate_fd(item) as fd:
            result.append(file_hash(fd))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scan", type=Path, required=True, help="Private inventory containing only the selected real files")
    p.add_argument("--enable-network", action="store_true")
    p.add_argument("--goal", choices=sorted(triage.GOALS), default="balanced")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--public-output", type=Path, required=True)
    args = p.parse_args()
    if not args.enable_network:
        raise Refused("Requires explicit network/cost authorization and --enable-network")
    if args.output.exists() or args.public_output.exists():
        raise Refused("Choose new output paths")
    inventory = load(args.scan)
    ids = [i["id"] for i in inventory["items"]]
    if not 1 <= len(ids) <= triage.MAX_CANDIDATES:
        raise Refused("Select 1..100 real files before benchmarking")
    before = hashes(inventory)
    runs = []
    workers = triage.MAX_WORKERS
    try:
        for concurrency in (1, workers):
            triage.MAX_WORKERS = concurrency
            run = triage.run(inventory, ids, goal=args.goal, enabled=True)
            runs.append(run)
            if set(run["provider"]["statuses"]) != {"ok"}:
                break  # No automatic retries; retain failed observations.
    finally:
        triage.MAX_WORKERS = workers
    unchanged = before == hashes(inventory)
    write(args.output, {"runs": runs, "source_hashes_unchanged": unchanged})
    public = {
        "schema": 1, "data": "real-jev-triage", "date": datetime.now(timezone.utc).date().isoformat(),
        "date_basis": "UTC",
        "transport_mocked": False, "real_user_data_modified": False,
        "network_calls": sum(r["provider"]["calls"] for r in runs),
        "source_files": len(ids), "source_logical_bytes": sum(i["identity"]["size"] for i in inventory["items"]),
        "source_hashes_unchanged": unchanged, "actual_reclaimed_bytes": 0,
        "goal": args.goal, "source_mutations_executed": False, "runs": [],
        "measurement_scope": "Fresh local eligibility/header checks and real provider calls; reuses a selected scan. Benchmark-only before/after full-source hashes are outside timed triage. No full disk scan or archive verification is timed.",
        "no_accuracy_claim": True, "no_cleanup_authorization": True,
        "price_per_million_input_usd": 0.042, "price_source": "https://docs.typesafe.ai/models",
        "billing_statement_verified": False,
    }
    for r in runs:
        public["runs"].append({"timing": r["timing"], "provider": r["provider"], "action_counts": r["action_counts"],
                              "decisions": [{k: d[k] for k in ("action", "reason_code", "source", "confidence", "provider_choice")}
                                            for d in r["decisions"]]})
    public["estimated_input_cost_usd"] = round(sum(r["provider"]["input_tokens"] for r in runs) * 0.042 / 1_000_000, 9)
    write(args.public_output, public)
    for r in runs:
        print({"workers": r["provider"]["max_concurrency"], "timing": r["timing"],
               "statuses": r["provider"]["statuses"], "actions": r["action_counts"]})
    print({"source_hashes_unchanged": unchanged, "calls": public["network_calls"], "reclaimed_bytes": 0})


if __name__ == "__main__":
    main()
