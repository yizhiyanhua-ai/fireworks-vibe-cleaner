#!/usr/bin/env python3
"""Reproducible synthetic experiments with an allowlisted, publishable result file.

All mutations are limited to a TemporaryDirectory owned by this invocation.
No model requests, real sessions, credentials or private paths enter the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vibe_cleaner import __version__, jev  # noqa: E402


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Verification requires assertions; remove -O/PYTHONOPTIMIZE")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new result file; existing evidence is never overwritten")
    rows = []
    with tempfile.TemporaryDirectory(prefix="vibe-local-experiments-") as temp:
        base = Path(temp).resolve()
        home = base / "isolated-home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"),
                   CLAUDE_CONFIG_DIR=str(home / ".claude"), PYTHONDONTWRITEBYTECODE="1")
        env.pop("TYPESAFE_API_KEY", None)
        launch = [sys.executable, str(ROOT / "scripts/fireworks-vibe-cleaner.py")]

        def run(*command: str, expected: int = 0) -> dict:
            p = subprocess.run([*launch, *command], cwd=base, env=env, text=True,
                               capture_output=True, timeout=30)
            if p.returncode != expected:
                # Deliberately omit command/path/stdout/stderr from publishable failures.
                raise RuntimeError(f"Unexpected experiment exit: {p.returncode}, expected {expected}")
            return json.loads(p.stdout if expected == 0 else p.stderr)

        def fixture(root: Path, relative: str, content: bytes, *, old: bool = True) -> Path:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            if old:
                os.utime(path, (time.time() - 60 * 86400,) * 2)
            return path

        def plan(root: Path, name: str, state: Path) -> tuple[dict, Path]:
            inv, out = base / f"{name}-scan.json", base / f"{name}-plan.json"
            run("scan", "--root", f"codex={root}", "--keep", "*/keep.log", "--output", str(inv))
            items = json.loads(inv.read_text())["items"]
            ids = [i["id"] for i in items if i["eligible"]]
            command = ["plan", "--scan", str(inv), "--state-dir", str(state),
                       "--max-bytes", str(32 * 1024**2), "--output", str(out)]
            for item_id in ids:
                command.extend(["--id", item_id])
            return run(*command), out

        def apply(p: dict, path: Path) -> None:
            run("apply", "--plan", str(path), "--approve", p["hash"], "--writers-stopped")

        root = base / "mixed-fixture"
        rng = random.Random(20260921)
        logs = [fixture(root, f"logs/old-{n}.log", rng.randbytes(4 * 1024**2)) for n in range(2)]
        protected = [
            fixture(root, "sessions/a.jsonl", b'{"synthetic": true}\n'),
            fixture(root, "archived_sessions/b.jsonl", b'{"synthetic": true}\n'),
            fixture(root, "memories/keep.md", b"synthetic memory"),
            fixture(root, "state.sqlite", b"synthetic state placeholder"),
            fixture(root, "generated_images/only.png", b"synthetic asset placeholder"),
            fixture(root, "source.py", b"value = 42\n"),
            fixture(root, "logs/recent.log", b"synthetic recent log", old=False),
            fixture(root, "logs/keep.log", b"synthetic user-kept log"),
        ]
        protected_hashes = [fingerprint(p) for p in protected]
        scan_path = base / "mixed-scan.json"
        scanned = run("scan", "--root", f"codex={root}", "--keep", "*/keep.log", "--output", str(scan_path))
        assert scanned["files"] == 10 and scanned["eligible_files"] == 2
        assert [fingerprint(p) for p in protected] == protected_hashes
        rows.append({"id": "mixed-inventory", "passed": True, "fixture_files": 10,
                     "eligible_files": 2, "protected_files": 8, "protected_hashes_unchanged": True})

        state = base / "quarantine-state"
        p, out = plan(root, "restore", state)
        log_hashes = [fingerprint(path) for path in logs]
        apply(p, out)
        assert all(not path.exists() for path in logs)
        assert run("verify", "--state-dir", str(state), "--run", p["hash"])["ok"]
        quarantined_bytes = sum((state / p["hash"] / str(n)).stat().st_size for n in range(2))
        assert quarantined_bytes == 8 * 1024**2
        run("restore", "--state-dir", str(state), "--run", p["hash"], "--writers-stopped")
        assert [fingerprint(path) for path in logs] == log_hashes
        rows.append({"id": "quarantine-restore", "passed": True, "files": 2,
                     "logical_bytes": quarantined_bytes, "quarantine_expected_reclaimed_bytes": 0,
                     "quarantine_measurement": "Same-volume move semantics, not a measured zero free-space delta.",
                     "restored_hashes_match": True})

        p, out = plan(root, "purge", state)
        apply(p, out)
        purged = run("purge", "--state-dir", str(state), "--run", p["hash"],
                     "--approve", "purge:" + p["hash"], "--writers-stopped")
        assert purged["deleted_logical_bytes"] == 8 * 1024**2
        assert run("verify", "--state-dir", str(state), "--run", p["hash"])["ok"]
        assert [fingerprint(path) for path in protected] == protected_hashes
        rows.append({"id": "approved-purge", "passed": True, "files": 2,
                     "deleted_logical_bytes": purged["deleted_logical_bytes"],
                     "observed_volume_free_delta_bytes": purged["observed_free_delta"],
                     "protected_files_unchanged": 8,
                     "measurement_note": "Volume delta includes filesystem accounting and unrelated writes."})

        changed_root = base / "changed-fixture"
        changed = fixture(changed_root, "logs/old.log", b"old synthetic log")
        p, out = plan(changed_root, "changed", base / "changed-state")
        changed.write_bytes(b"new synthetic content after plan")
        result = run("apply", "--plan", str(out), "--approve", p["hash"], "--writers-stopped", expected=2)
        assert changed.read_bytes() == b"new synthetic content after plan"
        rows.append({"id": "changed-plan-refusal", "passed": True, "exit_code": 2,
                     "source_retained": True, "error_class": result["error"]})

        conflict_root, conflict_state = base / "conflict-fixture", base / "conflict-state"
        conflict = fixture(conflict_root, "logs/old.log", b"old synthetic log")
        old_hash = fingerprint(conflict)
        p, out = plan(conflict_root, "conflict", conflict_state)
        apply(p, out)
        conflict.write_bytes(b"new synthetic work")
        run("restore", "--state-dir", str(conflict_state), "--run", p["hash"], "--writers-stopped", expected=2)
        assert conflict.read_bytes() == b"new synthetic work"
        assert fingerprint(conflict_state / p["hash"] / "0") == old_hash
        rows.append({"id": "restore-conflict", "passed": True, "exit_code": 2,
                     "new_source_preserved": True, "quarantined_original_preserved": True})

        inv = json.loads(scan_path.read_text())
        session = next(i for i in inv["items"] if i["category"] == "session")
        private = base / "private-backup"
        private.mkdir(mode=0o700)
        archive = private / "snapshot.zip"
        backed = run("backup", "--scan", str(scan_path), "--id", session["id"],
                     "--output", str(archive), "--max-bytes", "1048576")
        extracted = private / "extracted"
        run("extract", "--archive", str(archive), "--destination", str(extracted))
        source = Path(session["root"]) / session["relative"]
        assert fingerprint(extracted / "0") == fingerprint(source)
        assert not backed["source_removed"] and not backed["harness_resume_verified"]
        rows.append({"id": "session-byte-backup", "passed": True, "files": 1,
                     "original_retained": True, "extracted_hash_match": True,
                     "harness_resume_verified": False})

        sent = []
        def unavailable(request, timeout):
            sent.append(request.data.decode())
            raise urllib.error.HTTPError(jev.ENDPOINT, 503, "synthetic service failure", {}, None)
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "synthetic-not-a-real-key"}):
            advised = jev.advise([session], enabled=True, transport=unavailable)
        assert advised["status"] == "http-503" and advised["mode"] == "rules-only"
        assert len(sent) == 1 and str(base) not in sent[0] and "a.jsonl" not in sent[0] and "b.jsonl" not in sent[0]
        rows.append({"id": "jev-offline-failure", "passed": True, "simulated_http_status": 503,
                     "transport_calls": 1, "actual_network_calls": 0,
                     "fallback": "rules-only", "private_paths_sent": False,
                     "live_provider_verified": False})

    result = {"schema": 1, "date_utc": datetime.now(timezone.utc).date().isoformat(),
              "tool_version": __version__, "environment": {"os": platform.system(),
              "os_version": platform.mac_ver()[0] if sys.platform == "darwin" else platform.release(),
              "python": platform.python_version(), "architecture": platform.machine()},
              "data": "synthetic-only", "real_user_data_modified": False,
              "network_calls": 0, "temporary_fixture_removed": True,
              "passed": all(row["passed"] for row in rows), "experiments": rows}
    # Output schema contains no raw scan/plan/request, usernames, paths or session IDs.
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(serialized)
    print(json.dumps({"passed": result["passed"], "experiments": len(rows),
                      "real_user_data_modified": False, "network_calls": 0}))


if __name__ == "__main__":
    main()
