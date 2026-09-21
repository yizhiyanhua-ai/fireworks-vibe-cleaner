#!/usr/bin/env python3
"""Validate real historical session bytes without removing or modifying sources.

Private archives/manifests stay beside their original harness root. Only an
allowlisted aggregate report is written to --output. No model/network calls.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import stat
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import backup, engine  # noqa: E402
from vibe_cleaner.common import Refused, candidate_fd, file_hash, load, write  # noqa: E402
from vibe_cleaner.scan import classify, summarize  # noqa: E402


def fingerprint(item: dict) -> str:
    with candidate_fd(item) as fd:
        return file_hash(fd)


def validate(inventory: dict) -> dict:
    corrected = []
    rejected = []
    for source in inventory["items"]:
        item = dict(source)
        item["category"], item["reason"] = classify(Path(item["root"]), item["relative"], item["adapter"])
        if source["eligible"] and item["category"] not in {"log", "bytecode"}:
            item["eligible"] = False
            rejected.append(source)
        corrected.append(item)
    results = []
    for kind in ("codex", "claude"):
        candidates = sorted(
            (i for i in corrected if i["adapter"] == kind and i["category"] == "session"
             and i["age_days"] >= 1 and 0 < i["identity"]["size"] <= 64 * 1024**2
             and i["identity"]["nlink"] == 1 and stat.S_ISREG(i["identity"]["mode"])),
            key=lambda i: (-i["identity"]["size"], i["id"]))
        chosen, hashes = [], []
        for item in candidates:
            try:
                engine.idle_check([item])
                digest = fingerprint(item)
            except (Refused, OSError):
                continue
            if chosen and item["root"] != chosen[0]["root"]:
                continue
            chosen.append(item)
            hashes.append(digest)
            if len(chosen) == 2:
                break
        if not chosen:
            results.append({"adapter": kind, "status": "no-stable-sample"})
            continue
        base = Path(chosen[0]["root"]) / ".fireworks-vibe-cleaner"
        if base.is_symlink():
            raise Refused("Private validation parent must not be a symlink")
        base.mkdir(mode=0o700, exist_ok=True)
        if base.stat().st_mode & 0o077:
            raise Refused("Private validation parent must be mode 0700")
        private = base / ("real-validation-" + uuid.uuid4().hex)
        private.mkdir(mode=0o700)
        free_before = shutil.disk_usage(private).free
        total = sum(i["identity"]["size"] for i in chosen)
        archive = private / "sessions.zip"
        started = time.monotonic()
        backup.backup(inventory, [i["id"] for i in chosen], archive, max_bytes=128 * 1024**2)
        backup_ms = round((time.monotonic() - started) * 1000)
        with tempfile.TemporaryDirectory(prefix="verify-", dir=private) as tmp:
            backup.extract(archive, Path(tmp) / "extracted", max_bytes=128 * 1024**2)
            manifest = load(archive.with_suffix(".zip.manifest.json"))
            by_id = {row["item"]["id"]: row["sha256"] for row in manifest["files"]}
            if any(by_id[i["id"]] != h for i, h in zip(chosen, hashes)):
                raise Refused("Archive differs from pre-backup source bytes")
        if [fingerprint(i) for i in chosen] != hashes:
            raise Refused("Source bytes changed during validation")
        retained = sum(p.stat().st_size for p in private.iterdir() if p.is_file())
        results.append({"adapter": kind, "status": "bytes-verified", "files": len(chosen),
                        "source_bytes_before": total, "source_bytes_after": total,
                        "archive_bytes": archive.stat().st_size,
                        "archive_reduction_percent": round(100 * (1 - archive.stat().st_size / total), 2),
                        "retained_artifact_bytes": retained, "backup_elapsed_ms": backup_ms,
                        "source_hashes_unchanged": True, "extracted_hashes_match": True,
                        "source_bytes_deleted": 0, "cleanup_bytes_reclaimed": 0,
                        "observed_volume_free_delta_bytes": shutil.disk_usage(private).free - free_before,
                        "harness_resume_verified": False})
    return {"schema": 1, "data": "real-local", "date": datetime.now(timezone.utc).date().isoformat(),
            "environment": {"os": platform.system(), "release": platform.mac_ver()[0] or platform.release(),
                            "architecture": platform.machine(), "python": platform.python_version()},
            "source_snapshot_complete": inventory["complete"],
            "excluded_boundaries": dict(Counter(e["error"] for e in inventory["errors"])),
            "inventory_before_fix": inventory["summary"], "inventory_after_fix_same_snapshot": summarize(corrected),
            "custom_log_candidates_rejected": len(rejected),
            "custom_log_allocated_bytes_protected": sum(i["allocated_bytes"] for i in rejected),
            "real_user_data_modified": False, "network_calls": 0, "cleanup_bytes_reclaimed": 0,
            "backups": results, "notes": [
                "Real existing files; no fixtures, no mocked transport, no source deletion.",
                "Archives and private manifests retained; temporary extracted copies removed.",
                "Archive reduction is compression only, not recovered disk space.",
                "Volume free deltas include concurrent unrelated writes and are not cleanup gains.",
                "Before/after policy comparison uses the identical frozen real inventory."]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("Choose a new output file; existing evidence is never overwritten")
    report = validate(load(args.inventory))
    write(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
