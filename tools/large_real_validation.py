#!/usr/bin/env python3
"""Prepare and run a bounded real-session archive validation; never remove sources.

Private plans, ZIPs and manifests stay on the original volume. Full restore bytes
are streamed through SHA-256 and JSONL parsing; only small native-reader samples
are materialized. No cleanup, quarantine, resume or model calls are performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import backup  # noqa: E402
from vibe_cleaner.common import Refused, candidate_fd, digest, file_hash, load, write  # noqa: E402

GIB = 1024**3


def reject_constant(value: str) -> None:
    raise ValueError("Non-standard JSON constant")


def fingerprint(item: dict) -> str:
    with candidate_fd(item) as fd:
        return file_hash(fd)


def closed_files(items: list[dict]) -> list[dict]:
    selected = []
    for offset in range(0, len(items), 100):
        batch = items[offset:offset + 100]
        paths = [str(Path(i["root"]) / i["relative"]) for i in batch]
        p = subprocess.run(["lsof", "-nP", "-F", "pn", "--", *paths],
                           capture_output=True, text=True, timeout=30)
        if p.returncode not in (0, 1) or p.stderr or (p.returncode == 1 and p.stdout):
            raise Refused("Open-handle inspection inconclusive")
        opened = {line[1:] for line in p.stdout.splitlines() if line.startswith("n")}
        selected.extend(i for i, path in zip(batch, paths) if path not in opened)
    return selected


def prepare(inventory: dict, target_bytes: int) -> dict:
    if not GIB <= target_bytes <= 12 * GIB:
        raise Refused("Validation target must be between 1 and 12 GiB")
    selected = []
    for kind, fraction, age in (("claude", .075, 1), ("codex", .925, 7)):
        pool = sorted((i for i in inventory["items"] if i["adapter"] == kind
                       and i["category"] == "session" and i["age_days"] >= age
                       and 0 < i["identity"]["size"] <= 2 * GIB
                       and stat.S_ISREG(i["identity"]["mode"]) and i["identity"]["nlink"] == 1),
                      key=lambda i: (-i["identity"]["size"], i["id"]))
        total = 0
        for item in closed_files(pool):
            row = dict(item)
            row["sha256"] = fingerprint(row)
            selected.append(row)
            total += row["identity"]["size"]
            if total >= target_bytes * fraction:
                break
        if total < target_bytes * fraction:
            raise Refused("Not enough stable real sessions for the requested adapter share")
        print(json.dumps({"stage": "prepared", "adapter": kind, "bytes": total}), flush=True)
    plan = {"schema": 1, "action": "backup-validation-only", "created_at": time.time(),
            "source_mutations_authorized": False, "cleanup_requires_human_confirmation": True,
            "target_bytes": target_bytes, "items": selected,
            "inventory_complete": inventory["complete"],
            "excluded_boundary_count": len(inventory["errors"])}
    plan["hash"] = digest(plan)
    return plan


def run(plan: dict, evidence: Path) -> dict:
    if plan.get("action") != "backup-validation-only" or plan.get("source_mutations_authorized") is not False:
        raise Refused("This script never executes a cleanup plan")
    if plan["hash"] != digest({k: v for k, v in plan.items() if k != "hash"}):
        raise Refused("Validation plan hash mismatch")
    if evidence.exists():
        resume = load(evidence / "resume-state.json")
        if resume["plan_hash"] != plan["hash"]:
            raise Refused("Resume state belongs to a different plan")
    else:
        evidence.mkdir(mode=0o700)
        resume = {"plan_hash": plan["hash"], "locations": []}
    started = time.monotonic()
    rows, native_samples, locations = [], [], []
    for kind in ("codex", "claude"):
        items = [i for i in plan["items"] if i["adapter"] == kind]
        if not items or len({i["root"] for i in items}) != 1:
            raise Refused("Expected one selected root per adapter")
        root = Path(items[0]["root"])
        base = root / ".fireworks-vibe-cleaner"
        if base.is_symlink():
            raise Refused("Private archive parent cannot be a symlink")
        base.mkdir(mode=0o700, exist_ok=True)
        if base.stat().st_mode & 0o077:
            raise Refused("Private archive parent must be mode 0700")
        existing = next((x for x in resume["locations"] if x["adapter"] == kind), None)
        private = Path(existing["directory"]) if existing else base / ("large-real-" + uuid.uuid4().hex)
        if private.parent != base or private.is_symlink():
            raise Refused("Unsafe resumed archive directory")
        private.mkdir(mode=0o700, exist_ok=existing is not None)
        locations.append({"adapter": kind, "directory": str(private)})
        groups, current, size = [], [], 0
        for item in items:
            if current and size + item["identity"]["size"] > GIB:
                groups.append(current)
                current, size = [], 0
            current.append(item)
            size += item["identity"]["size"]
        if current:
            groups.append(current)
        sample_pool = [i for i in sorted(items, key=lambda i: i["identity"]["size"])
                       if i["identity"]["size"] <= 256 * 1024**2 and Path(i["relative"]).suffix == ".jsonl"]
        sample_ids = {i["id"] for i in sample_pool[:2]}
        before_free = shutil.disk_usage(private).free
        archive_bytes = archive_allocated = restored = invalid_lines = oversized_lines = json_lines = backup_ms = 0
        source_bytes = sum(i["identity"]["size"] for i in items)
        already_archived = sum(p.stat().st_size for p in private.glob("sessions-*.zip"))
        if before_free < source_bytes - already_archived + 2 * GIB:
            raise Refused("Insufficient worst-case archive headroom plus 2 GiB reserve")
        checkpoint = evidence / f"location-{kind}.json"
        if not checkpoint.exists():
            write(checkpoint, {"plan_hash": plan["hash"], "directory": str(private), "adapter": kind})
        for index, group in enumerate(groups):
            archive = private / f"sessions-{index:03}.zip"
            one_started = time.monotonic()
            if not archive.exists():
                backup.backup({"items": group}, [i["id"] for i in group], archive,
                              max_bytes=sum(i["identity"]["size"] for i in group))
            backup_ms += round((time.monotonic() - one_started) * 1000)
            manifest = load(archive.with_suffix(".zip.manifest.json"))
            if {m["item"]["id"]: m["sha256"] for m in manifest["files"]} != {i["id"]: i["sha256"] for i in group}:
                raise Refused("Archive manifest does not match this frozen shard")
            with zipfile.ZipFile(archive) as z:
                for member in manifest["files"]:
                    item = member["item"]
                    original = next(i for i in group if i["id"] == item["id"])
                    h, count = hashlib.sha256(), 0
                    with z.open(member["member"]) as src:
                        while line := src.readline(64 * 1024**2 + 1):
                            h.update(line)
                            count += len(line)
                            if len(line) > 64 * 1024**2:
                                oversized_lines += 1
                                json_lines += 1
                                while not line.endswith(b"\n"):
                                    line = src.readline(64 * 1024**2 + 1)
                                    if not line:
                                        break
                                    h.update(line)
                                    count += len(line)
                                continue
                            if line.strip():
                                json_lines += 1
                                try:
                                    json.loads(line, parse_constant=reject_constant)
                                except (ValueError, UnicodeDecodeError, RecursionError):
                                    invalid_lines += 1
                    if h.hexdigest() != original["sha256"] or count != original["identity"]["size"]:
                        raise Refused("Full stream restore hash/size mismatch")
                    restored += count
                    if item["id"] in sample_ids:
                        target = private / "native-restored" / item["relative"]
                        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                        if not target.exists():
                            with z.open(member["member"]) as src, target.open("xb") as dest:
                                shutil.copyfileobj(src, dest, 1024**2)
                        target.chmod(0o600)
                        native_samples.append({"adapter": kind, "item": original,
                                               "restored_root": str(private / "native-restored"),
                                               "restored_file": str(target)})
            archive_bytes += archive.stat().st_size
            archive_allocated += archive.stat().st_blocks * 512
            print(json.dumps({"stage": "archive-verified", "adapter": kind,
                              "shard": index + 1, "shards": len(groups),
                              "source_bytes_verified": restored, "archive_bytes": archive_bytes}), flush=True)
        if any(fingerprint(i) != i["sha256"] for i in items):
            raise Refused("An original changed during validation; no cleanup permitted")
        retained_bytes = sum(p.stat().st_size for p in private.rglob("*") if p.is_file())
        rows.append({"adapter": kind, "files": len(items), "source_bytes": source_bytes,
                     "source_allocated_bytes": sum(i["allocated_bytes"] for i in items),
                     "archive_bytes": archive_bytes, "archive_allocated_bytes": archive_allocated,
                     "archive_reduction_percent": round(100 * (1 - archive_bytes / source_bytes), 2),
                     "retained_evidence_bytes": retained_bytes, "shards": len(groups),
                     "full_stream_restored_bytes": restored, "jsonl_lines": json_lines,
                     "invalid_jsonl_lines": invalid_lines, "oversized_jsonl_lines": oversized_lines,
                     "strict_jsonl_valid": invalid_lines == 0 and oversized_lines == 0,
                     "native_samples_materialized": len(sample_ids), "all_source_hashes_unchanged": True,
                     "all_restore_hashes_match": True, "backup_and_readback_ms": backup_ms,
                     "observed_volume_free_delta_bytes": shutil.disk_usage(private).free - before_free})
    if any(fingerprint(i) != i["sha256"] for i in plan["items"]):
        raise Refused("Final full-source hash recheck failed")
    write(evidence / "private-locations.json", locations)
    write(evidence / "native-samples.json", native_samples)
    report = {"schema": 1, "data": "real-local-large", "date": datetime.now(timezone.utc).date().isoformat(),
              "source_files": len(plan["items"]), "source_bytes": sum(i["identity"]["size"] for i in plan["items"]),
              "plan_hash": plan["hash"], "source_snapshot_complete": plan["inventory_complete"],
              "excluded_boundaries": plan["excluded_boundary_count"], "elapsed_ms": round((time.monotonic()-started)*1000),
              "final_all_source_hashes_unchanged": True,
              "real_user_data_modified": False, "source_bytes_deleted": 0, "cleanup_bytes_reclaimed": 0,
              "cleanup_requires_human_confirmation": True, "network_calls": 0,
              "rows": rows, "native_resume_verified": False,
              "notes": ["All samples are existing real session files; no synthetic bytes.",
                        "Full restoration is streamed through SHA-256 and strict JSONL parsing, not written over originals.",
                        "Only small native-reader samples are materialized; originals and all validation artifacts retained.",
                        "Compression reduction is not reclaimed space. Volume deltas include unrelated background writes."]}
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--inventory", type=Path, required=True)
    s.add_argument("--target-bytes", type=int, default=10 * GIB)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("run")
    s.add_argument("--plan", type=Path, required=True)
    s.add_argument("--private-evidence", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.is_symlink():
        raise Refused("Evidence output already exists")
    result = prepare(load(a.inventory), a.target_bytes) if a.command == "prepare" else run(load(a.plan), a.private_evidence)
    write(a.output, result)
    print(json.dumps({"stage": "complete", "command": a.command,
                      "files": len(result["items"]) if a.command == "prepare" else result["source_files"]}), flush=True)


if __name__ == "__main__":
    main()
