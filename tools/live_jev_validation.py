#!/usr/bin/env python3
"""Real provider comparison using only allowlisted metadata from a private plan."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import jev  # noqa: E402
from vibe_cleaner.common import Refused, digest, load, write  # noqa: E402


def validate(plan: dict, repeats: int) -> dict:
    if not 1 <= repeats <= 3:
        raise Refused("At most three explicit comparison calls; no automatic retries")
    items = sorted(plan["items"], key=lambda i: (i["adapter"], i["age_days"], i["identity"]["size"]))
    count = min(20, len(items))
    sample = [items[round(n * (len(items) - 1) / max(1, count - 1))] for n in range(count)]
    sample = jev.local_evidence(sample, {"min_age_days": plan.get("min_age_days", 30), "keep": plan.get("keep", [])},
                                inspect_activity=True)
    request = jev.packet(sample)
    runs = []
    for _ in range(repeats):
        result = jev.advise(sample, enabled=True)
        row = {"status": result["status"], "calls": result["calls"], "mode": result["mode"]}
        if result["status"] == "ok":
            answers = {key: {field: value[field] for field in ("choice", "confidence", "probabilities")}
                       for key, value in result["answers"].items()}
            row.update(model=result["model"], elapsed_ms=result["elapsed_ms"], answers=answers, usage=result["usage"])
        runs.append(row)
        print(json.dumps({"attempt": len(runs), "status": row["status"],
                          "elapsed_ms": row.get("elapsed_ms")}), flush=True)
        if result["status"] != "ok":
            break
    successful = [r for r in runs if r["status"] == "ok"]
    input_tokens = sum(r["usage"]["input_tokens"] for r in successful)
    return {"schema": 1, "data": "real-live-jev", "date": datetime.now(timezone.utc).date().isoformat(),
            "transport_mocked": False, "real_user_data_modified": False,
            "network_calls": sum(r["calls"] for r in runs), "successful_calls": len(successful),
            "dataset_files": len(items), "dataset_bytes": sum(i["identity"]["size"] for i in items),
            "sample_files": len(sample), "sample_metadata": request["state"]["candidates"],
            "request_sha256": digest(request), "runs": runs,
            "decisions": dict(Counter(a["choice"] for r in successful for a in r["answers"].values())),
            "median_end_to_end_ms": statistics.median(r["elapsed_ms"] for r in successful) if successful else None,
            "same_choices_across_repeats": all(
                [a["choice"] for a in r["answers"].values()] ==
                [a["choice"] for a in successful[0]["answers"].values()] for r in successful) if successful else None,
            "input_tokens": input_tokens,
            "estimated_input_cost_usd": round(input_tokens * .042 / 1_000_000, 9),
            "price_per_million_input_usd": .042, "price_source": "https://docs.typesafe.ai/models",
            "billing_statement_verified": False, "deletion_actions": 0,
            "rule_baseline": "Retain all original sessions; no cleanup without human confirmation.",
            "notes": ["Twenty representative metadata-only candidates at most; not transcript semantic review.",
                      "Repeated live calls measure observed consistency and round-trip latency only.",
                      "No labeled ground truth: accuracy or superiority over rules is not established.",
                      "Token-price estimate is not an authoritative billing receipt; failed-call usage is unknown."]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--enable-network", action="store_true")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not args.enable_network:
        raise Refused("Live provider testing requires explicit --enable-network and applicable authorization")
    if args.output.exists() or args.output.is_symlink():
        raise Refused("Choose a new evidence output")
    write(args.output, validate(load(args.plan), args.repeats))


if __name__ == "__main__":
    main()
