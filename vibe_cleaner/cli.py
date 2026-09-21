"""CLI entry point; network and mutation are always explicit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from . import __version__, backup, engine, history, jev, native_history, sessions
from .common import Json, Refused, load, write
from .scan import roots_default, scan


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fireworks-vibe-cleaner", description="Inspect, plan, quarantine, verify. Offline by default.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only capability report; no network")
    s = sub.add_parser("history-audit", help="Read-only Codex index count/size pressure; never archive automatically")
    s.add_argument("--codex-home", type=Path, default=Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))))
    s.add_argument("--total-bytes", type=int, default=3 * history.GIB, help="Total known session bytes; default 3 GiB")
    s.add_argument("--single-bytes", type=int, default=3 * history.GIB, help="Single session bytes; default 3 GiB")
    s.add_argument("--count-limit", type=int, default=200, help="Unarchived index count; default 200")
    s.add_argument("--min-age-days", type=int, default=30)
    s.add_argument("--keep-recent", type=int, default=100)
    s.add_argument("--keep-thread", action="append", default=[])
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("history-plan", help="Review exact native Codex history archive scope, including descendants")
    s.add_argument("--audit", type=Path, required=True)
    s.add_argument("--id", action="append", required=True, help="Selected top-level native thread ID")
    s.add_argument("--state-dir", type=Path, required=True)
    s.add_argument("--codex", default="codex")
    s.add_argument("--ttl-seconds", type=int, default=3600)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("history-apply", help="Native archive of an approved closure; zero disk reclaim")
    s.add_argument("--plan", type=Path, required=True)
    s.add_argument("--approve", required=True, help="Exact reviewed plan hash")
    s.add_argument("--writers-stopped", action="store_true")
    for name in ("history-verify", "history-restore"):
        s = sub.add_parser(name)
        s.add_argument("--state-dir", type=Path, required=True)
        s.add_argument("--run", required=True)
        if name == "history-restore":
            s.add_argument("--approve", required=True, help="unarchive:<run> authorizes this recovery scope")
            s.add_argument("--writers-stopped", action="store_true")
    s = sub.add_parser("scan", help="Read-only inventory; no transcript contents read")
    s.add_argument("--root", action="append", help="Explicit kind=path (codex, claude, project)")
    s.add_argument("--min-age-days", type=int, default=30)
    s.add_argument("--max-files", type=int, default=200000)
    s.add_argument("--keep", action="append", default=[])
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("report", help="Show inventory summary and optional growth")
    s.add_argument("--scan", type=Path, required=True)
    s.add_argument("--previous", type=Path)
    s.add_argument("--format", choices=["json", "markdown"], default="json")
    s = sub.add_parser("plan", help="Hash selected eligible files into a reviewable plan")
    s.add_argument("--scan", type=Path, required=True)
    s.add_argument("--id", action="append", required=True)
    s.add_argument("--state-dir", type=Path, required=True)
    s.add_argument("--max-bytes", type=int, required=True)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("apply", help="Quarantine exactly an approved plan; frees zero bytes")
    s.add_argument("--plan", type=Path, required=True)
    s.add_argument("--approve", required=True, help="Exact reviewed plan hash")
    s.add_argument("--writers-stopped", action="store_true")
    s.add_argument("--state-cap-bytes", type=int, default=1024**3)
    for name in ("verify", "restore", "purge"):
        s = sub.add_parser(name)
        s.add_argument("--state-dir", type=Path, required=True)
        s.add_argument("--run", required=True)
        if name != "verify":
            s.add_argument("--writers-stopped", action="store_true")
        if name == "purge":
            s.add_argument("--approve", required=True, help="purge:<run> authorizes permanent deletion")
    s = sub.add_parser("backup", help="Private same-volume snapshot; retains all source files")
    s.add_argument("--scan", type=Path, required=True)
    s.add_argument("--id", action="append", required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--max-bytes", type=int, required=True)
    s = sub.add_parser("extract", help="Restore backup bytes into a new directory, never live harness state")
    s.add_argument("--archive", type=Path, required=True)
    s.add_argument("--destination", type=Path, required=True)
    s.add_argument("--max-bytes", type=int, default=1024**3)
    s = sub.add_parser("archive-plan", help="Review removal of old transcripts already in verified archives")
    s.add_argument("--scan", type=Path, required=True)
    s.add_argument("--id", action="append", required=True)
    s.add_argument("--archive", type=Path, action="append", required=True)
    s.add_argument("--ttl-seconds", type=int, default=3600, help="Review expiry, at most 86400 seconds")
    s.add_argument("--state-dir", type=Path, required=True)
    s.add_argument("--max-bytes", type=int, required=True)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("archive-apply", help="Remove only approved, archived transcripts; retain backups")
    s.add_argument("--plan", type=Path, required=True)
    s.add_argument("--approve", required=True)
    s.add_argument("--writers-stopped", action="store_true")
    s.add_argument("--acknowledge-history-risk", action="store_true")
    for name in ("archive-verify", "archive-restore"):
        s = sub.add_parser(name)
        s.add_argument("--state-dir", type=Path, required=True)
        s.add_argument("--run", required=True)
        if name == "archive-restore":
            s.add_argument("--writers-stopped", action="store_true")
    s = sub.add_parser("advise", help="Optional one-call Jev review (no deletion authority)")
    s.add_argument("--scan", type=Path, required=True)
    s.add_argument("--id", action="append", required=True)
    s.add_argument("--enable-network", action="store_true")
    s.add_argument("--inspect-activity", action="store_true", help="Read-only local lsof checks to refine advice")
    s.add_argument("--output", type=Path, required=True)
    return p


def doctor() -> Json:
    versions = {}
    for name in ("codex", "claude"):
        try:
            result = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=5)
            versions[name] = result.stdout.strip()[:120] if result.returncode == 0 else "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            versions[name] = "unavailable"
    return {"version": __version__, "python": platform.python_version(), "platform": sys.platform,
            "harness_versions": versions, "lsof_available": bool(shutil.which("lsof")),
            "jev_key_present": bool(os.getenv("TYPESAFE_API_KEY")), "network_tested": False,
            "jev_recommended": True,
            "jev_setup": "Inject TYPESAFE_API_KEY from a secret manager or process environment; never paste it in chat",
            "session_deletion": "verified-archive-and-exact-human-approval-required",
            "native_history": {"audit": "recognized-state_5-schema-only",
                               "write_contract": "macOS, codex-cli 0.154.0, complete audit, exact approval",
                               "runtime_verified_this_call": False, "reclaimed_bytes": 0},
            "harness_resume_verified": False, "cross_volume_moves": "disabled",
            "roots": [{"kind": kind, "path": str(path.resolve()), "exists": path.exists()}
                      for kind, path in roots_default()]}


def execute(a: argparse.Namespace) -> Json:
    if a.command == "doctor":
        return doctor()
    if a.command == "history-audit":
        result = history.audit(a.codex_home, total_bytes=a.total_bytes, single_bytes=a.single_bytes,
                               count_limit=a.count_limit, min_age_days=a.min_age_days,
                               keep_recent=a.keep_recent, keep_ids=a.keep_thread)
        write(a.output, result)
        return {"output": str(a.output), "complete": result["complete"], "thresholds": result["thresholds"],
                **result["summary"]}
    if a.command == "history-plan":
        result = native_history.make_plan(load(a.audit), a.id, a.state_dir, codex=a.codex, ttl=a.ttl_seconds)
        write(a.output, result)
        return result
    if a.command == "history-apply":
        return native_history.apply(load(a.plan), a.approve, quiescent=a.writers_stopped)
    if a.command in {"history-verify", "history-restore"}:
        state = a.state_dir.expanduser().absolute()
        if a.command == "history-verify":
            return native_history.verify(state, a.run)
        return native_history.restore(state, a.run, a.approve, quiescent=a.writers_stopped)
    if a.command == "scan":
        roots = []
        if a.root:
            for value in a.root:
                kind, sep, path = value.partition("=")
                if not sep:
                    raise Refused("Use --root kind=path")
                roots.append((kind, Path(path)))
        else:
            roots = [(kind, path) for kind, path in roots_default() if path.exists()]
        result = scan(roots, min_age_days=a.min_age_days, max_files=a.max_files, keep=a.keep)
        write(a.output, result)
        return {"output": str(a.output), "complete": result["complete"], **result["summary"]}
    if a.command == "report":
        current = load(a.scan)
        result = {"summary": current["summary"], "complete": current["complete"],
                  "errors": current["errors"], "eligible": [i for i in current["items"] if i["eligible"]],
                  "archive_candidates": [i for i in current["items"] if i.get("archive_eligible")]}
        if a.previous:
            before = load(a.previous)
            if before["roots"] != current["roots"] or not before["complete"] or not current["complete"]:
                raise Refused("Growth comparison requires complete scans of identical roots")
            if current["created_at"] <= before["created_at"]:
                raise Refused("Previous scan must be older")
            result["logical_growth_bytes"] = (sum(i["identity"]["size"] for i in current["items"]) -
                                               sum(i["identity"]["size"] for i in before["items"]))
        return result
    if a.command == "plan":
        result = engine.make_plan(load(a.scan), a.id, a.state_dir, max_bytes=a.max_bytes)
        write(a.output, result)
        # The approval hash is shown alongside the entire selected scope, never alone.
        return result
    if a.command == "apply":
        return engine.apply(load(a.plan), a.approve, quiescent=a.writers_stopped, state_cap=a.state_cap_bytes)
    if a.command in {"verify", "restore", "purge"}:
        state = a.state_dir.expanduser().absolute()
        if a.command == "verify":
            return engine.verify(state, a.run)
        if a.command == "restore":
            return engine.restore(state, a.run, quiescent=a.writers_stopped)
        return engine.purge(state, a.run, a.approve, quiescent=a.writers_stopped)
    if a.command == "backup":
        return backup.backup(load(a.scan), a.id, a.output, max_bytes=a.max_bytes)
    if a.command == "extract":
        return backup.extract(a.archive, a.destination, max_bytes=a.max_bytes)
    if a.command == "archive-plan":
        result = sessions.make_plan(load(a.scan), a.id, a.archive, a.state_dir, max_bytes=a.max_bytes, ttl=a.ttl_seconds)
        write(a.output, result)
        return result
    if a.command == "archive-apply":
        return sessions.apply(load(a.plan), a.approve, quiescent=a.writers_stopped,
                              acknowledge_risk=a.acknowledge_history_risk)
    if a.command in {"archive-verify", "archive-restore"}:
        state = a.state_dir.expanduser().absolute()
        if a.command == "archive-verify":
            return sessions.verify(state, a.run)
        return sessions.restore(state, a.run, quiescent=a.writers_stopped)
    if a.command == "advise":
        inventory = load(a.scan)
        items = [i for i in inventory["items"] if i["id"] in a.id]
        if len(items) != len(a.id):
            raise Refused("Unknown or duplicate ID")
        items = jev.local_evidence(items, inventory, inspect_activity=a.inspect_activity)
        result = jev.advise(items, enabled=a.enable_network)
        # Private local mapping, never included in the provider request.
        result["candidate_ids"] = {f"c{n}": item["id"] for n, item in enumerate(items)}
        write(a.output, result)
        return result
    raise Refused("Unknown command")


def main() -> int:
    try:
        if os.name != "posix":
            raise Refused("v0.1 supports macOS/Linux only")
        args = parser().parse_args()
        result = execute(args)
        if args.command == "report" and args.format == "markdown":
            print("# Space inventory\n\n| Category | Files | Logical bytes | Allocated bytes |\n| --- | ---: | ---: | ---: |")
            for name, row in result["summary"]["categories"].items():
                print(f"| {name} | {row['files']} | {row['logical_bytes']} | {row['allocated_bytes']} |")
            print(f"\nComplete: {result['complete']}. Eligible is preliminary, not verified reclaimable space.")
            print(f"\nExcluded boundaries or errors: {len(result['errors'])}.")
            if "logical_growth_bytes" in result:
                print(f"\nLogical growth: {result['logical_growth_bytes']} bytes.")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0 if result.get("ok", True) else 3
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        # Never print provider request/response payloads or auth headers on errors.
        print(json.dumps({"error": type(exc).__name__, "message": str(exc) if isinstance(exc, Refused)
                          else "Operation failed; check paths, permissions, input schema and dependencies."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
