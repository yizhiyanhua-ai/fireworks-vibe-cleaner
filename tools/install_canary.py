#!/usr/bin/env python3
"""Exercise copied Skills with an isolated HOME and synthetic data only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vibe-canary-") as tmp:
        base = Path(tmp).resolve()
        home = base / "home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"),
                   CLAUDE_CONFIG_DIR=str(home / ".claude"), PYTHONDONTWRITEBYTECODE="1")
        env.pop("TYPESAFE_API_KEY", None)
        for harness in (".codex", ".claude"):
            install = home / harness / "skills/fireworks-vibe-cleaner"
            shutil.copytree(ROOT / "skills/fireworks-vibe-cleaner", install)
            launch = [sys.executable, str(install / "scripts/fireworks-vibe-cleaner.py")]
            def run(*args: str) -> dict:
                p = subprocess.run([*launch, *args], env=env, cwd=base, capture_output=True, text=True, timeout=30)
                if p.returncode:
                    raise RuntimeError(p.stderr)
                return json.loads(p.stdout)
            run("doctor")
            root = base / (harness[1:] + "-fixture")
            (root / "logs").mkdir(parents=True)
            log = root / "logs/old.log"
            content = os.urandom(2 * 1024 * 1024)
            log.write_bytes(content)
            os.utime(log, (time.time() - 86400 * 60,) * 2)
            inv = base / f"{harness}-scan.json"
            run("scan", "--root", f"codex={root}", "--output", str(inv))
            item = json.loads(inv.read_text())["items"][0]
            plan_path = base / f"{harness}-plan.json"
            state = base / f"{harness}-state"
            plan = run("plan", "--scan", str(inv), "--id", item["id"], "--state-dir", str(state),
                       "--max-bytes", str(len(content)), "--output", str(plan_path))
            result = run("apply", "--plan", str(plan_path), "--approve", plan["hash"], "--writers-stopped")
            assert result["immediate_reclaimed_bytes"] == 0 and not log.exists()
            assert run("verify", "--state-dir", str(state), "--run", plan["hash"])["ok"]
            run("restore", "--state-dir", str(state), "--run", plan["hash"], "--writers-stopped")
            assert hashlib.sha256(log.read_bytes()).digest() == hashlib.sha256(content).digest()
            # New inventory/plan for the second operation; never replay an old apply.
            inv2, plan2 = base / f"{harness}-scan2.json", base / f"{harness}-plan2.json"
            run("scan", "--root", f"codex={root}", "--output", str(inv2))
            p2 = run("plan", "--scan", str(inv2), "--id", item["id"], "--state-dir", str(state),
                     "--max-bytes", str(len(content)), "--output", str(plan2))
            run("apply", "--plan", str(plan2), "--approve", p2["hash"], "--writers-stopped")
            purge = run("purge", "--state-dir", str(state), "--run", p2["hash"],
                        "--approve", "purge:" + p2["hash"], "--writers-stopped")
            assert purge["deleted_logical_bytes"] == len(content)
            assert run("verify", "--state-dir", str(state), "--run", p2["hash"])["ok"]
            print(json.dumps({"harness": harness, "installed": True, "restore_hash_match": True,
                              "purged_logical_bytes": purge["deleted_logical_bytes"],
                              "observed_free_delta": purge["observed_free_delta"], "real_user_data_touched": False}))


if __name__ == "__main__":
    main()
