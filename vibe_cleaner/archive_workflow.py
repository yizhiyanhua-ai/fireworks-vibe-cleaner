"""A plan-bound canary restore gate before archived transcript cleanup."""

from __future__ import annotations

import json
from pathlib import Path
import time

from . import sessions
from .common import Json, Refused, load, sync_dir
from .engine import journal_save, locked_state, seal


ACTION = "canary-restore-then-remove-archived-transcripts"
RISK = (
    "The canary original is removed, verified, restored and verified before cleanup starts. "
    "Cleanup then removes only its separately frozen originals while retaining verified archives. "
    "Related indexes remain unchanged; native conversation continuation is unverified."
)


def _paths(plan: Json) -> set[tuple[str, str]]:
    return {(row["root"], row["relative"]) for row in plan["items"]}


def _archives(*plans: Json) -> set[tuple[str, str]]:
    return {(row["root"], row["relative"]) for plan in plans for row in plan["archives"]}


def _hash(plan: Json) -> str:
    value = plan.get("hash")
    if not isinstance(value, str):
        raise Refused("Archive child plan is missing its reviewed hash")
    return value


def make_plan(canary: Json, cleanup: Json) -> Json:
    sessions.check_plan(canary, _hash(canary))
    sessions.check_plan(cleanup, _hash(cleanup))
    if len(canary["items"]) != 1:
        raise Refused("A canary workflow requires exactly one canary source")
    if not cleanup["items"]:
        raise Refused("A canary workflow requires a non-empty cleanup plan")
    if canary["state_dir"] != cleanup["state_dir"]:
        raise Refused("Canary and cleanup plans must use the same private state directory")
    if _paths(canary) & _paths(cleanup):
        raise Refused("Canary and cleanup source scopes must be disjoint")
    now = time.time()
    expires = min(canary["expires_at"], cleanup["expires_at"])
    if expires <= now:
        raise Refused("A child plan expired; refresh and review it before creating the workflow")
    plan: Json = {
        "schema": 1,
        "action": ACTION,
        "created_at": now,
        "expires_at": expires,
        "state_dir": canary["state_dir"],
        "canary_plan": canary,
        "cleanup_plan": cleanup,
        "canary_files": 1,
        "cleanup_files": len(cleanup["items"]),
        "cleanup_logical_bytes": cleanup["source_logical_bytes"],
        "archives_retained": len(_archives(canary, cleanup)),
        "risk": RISK,
        "harness_resume_verified": False,
    }
    plan["hash"] = seal(plan)
    check_plan(plan, plan["hash"])
    return plan


def check_plan(plan: Json, approval: str | None, *, expired_ok: bool = False) -> None:
    if (plan.get("schema") != 1 or plan.get("action") != ACTION or plan.get("risk") != RISK
            or plan.get("harness_resume_verified") is not False):
        raise Refused("Unsupported archive workflow plan")
    if plan.get("hash") != seal(plan) or approval != plan["hash"]:
        raise Refused("Approval must match the complete reviewed archive workflow plan")
    if not expired_ok and time.time() > plan["expires_at"]:
        raise Refused("Archive workflow plan expired; refresh its child plans and review a new workflow")
    canary, cleanup = plan["canary_plan"], plan["cleanup_plan"]
    sessions.check_plan(canary, _hash(canary), expired_ok=expired_ok)
    sessions.check_plan(cleanup, _hash(cleanup), expired_ok=expired_ok)
    if (len(canary["items"]) != 1 or not cleanup["items"]
            or canary["state_dir"] != cleanup["state_dir"]
            or plan["state_dir"] != canary["state_dir"]
            or _paths(canary) & _paths(cleanup)):
        raise Refused("Archive workflow child plans no longer match the reviewed gate")
    if (plan["expires_at"] != min(canary["expires_at"], cleanup["expires_at"])
            or plan["canary_files"] != 1
            or plan["cleanup_files"] != len(cleanup["items"])
            or plan["cleanup_logical_bytes"] != cleanup["source_logical_bytes"]
            or plan["archives_retained"] != len(_archives(canary, cleanup))):
        raise Refused("Archive workflow summary does not match its frozen child plans")
    if len(json.dumps(plan, ensure_ascii=False, indent=2).encode()) > 32 * 1024**2:
        raise Refused("Archive workflow plan is too large; split the cleanup scope")


def _directory(state: Path, run: str) -> Path:
    if len(run) != 64 or any(char not in "0123456789abcdef" for char in run):
        raise Refused("Invalid workflow run identifier")
    return state / ("workflow-" + run)


def _save_stage(state: Path, run: str, stage: str, *, error: str | None = None) -> None:
    with locked_state(state):
        directory = _directory(state, run)
        journal = load(directory / "journal.json")
        journal["stage"] = stage
        journal["updated_at"] = time.time()
        if error:
            journal["error"] = error
        journal_save(directory, journal)


def _require_removed(result: Json, count: int) -> None:
    if (not result["ok"] or result["status"] != "removed" or len(result["items"]) != count
            or any(row["location"] != "archive-only" or not row["valid"] for row in result["items"])):
        raise Refused("Removal verification did not establish valid archive-only state")


def _require_restored(result: Json) -> None:
    if (not result["ok"] or result["status"] != "restored" or len(result["items"]) != 1
            or result["items"][0]["location"] != "source" or not result["items"][0]["valid"]):
        raise Refused("Canary restoration was not verified at its original path; cleanup is blocked")


def apply(plan: Json, approval: str, *, quiescent: bool, acknowledge_risk: bool) -> Json:
    check_plan(plan, approval)
    if not quiescent or not acknowledge_risk:
        raise Refused("Stop writers and explicitly acknowledge the reviewed history/continuation risk")
    state = Path(plan["state_dir"])
    canary, cleanup = plan["canary_plan"], plan["cleanup_plan"]
    run = plan["hash"]
    with locked_state(state):
        directory = _directory(state, run)
        if directory.exists():
            raise Refused("Workflow run already exists; verify its journals instead of replaying it")
        if ((state / canary["hash"]).exists() or (state / cleanup["hash"]).exists()):
            raise Refused("A child plan already has a journal; do not reuse it in a new workflow")
        directory.mkdir(mode=0o700)
        sync_dir(state)
        journal_save(directory, {"schema": 1, "plan": plan, "stage": "prepared", "updated_at": time.time()})
    try:
        sessions.apply(canary, canary["hash"], quiescent=True, acknowledge_risk=True)
        _save_stage(state, run, "canary_removed")
        canary_removed = sessions.verify(state, canary["hash"])
        _require_removed(canary_removed, 1)
        _save_stage(state, run, "canary_removal_verified")
        sessions.restore(state, canary["hash"], quiescent=True)
        canary_restored = sessions.verify(state, canary["hash"])
        _require_restored(canary_restored)
        _save_stage(state, run, "canary_restored_verified")
        cleanup_result = sessions.apply(cleanup, cleanup["hash"], quiescent=True, acknowledge_risk=True)
        _save_stage(state, run, "cleanup_removed")
        cleanup_verified = sessions.verify(state, cleanup["hash"])
        _require_removed(cleanup_verified, len(cleanup["items"]))
        _save_stage(state, run, "verified")
        return {
            "run": run,
            "status": "verified",
            "canary": sessions.summarize_verification(canary_restored),
            "cleanup": sessions.summarize_verification(cleanup_verified),
            "cleanup_apply": cleanup_result,
            "archives_retained": True,
            "harness_resume_verified": False,
        }
    except BaseException as exc:
        try:
            _save_stage(state, run, "interrupted", error=type(exc).__name__)
        except BaseException:
            pass
        raise


def verify(state: Path, run: str) -> Json:
    with locked_state(state):
        journal = load(_directory(state, run) / "journal.json")
    plan = journal["plan"]
    check_plan(plan, run, expired_ok=True)
    result: Json = {"run": run, "stage": journal["stage"], "harness_resume_verified": False}
    for name in ("canary", "cleanup"):
        child = plan[name + "_plan"]
        if (state / child["hash"]).exists():
            result[name] = sessions.summarize_verification(sessions.verify(state, child["hash"]))
        else:
            result[name] = {"status": "not-started"}
    result["ok"] = (result["stage"] == "verified" and result["canary"].get("ok") is True
                    and result["canary"].get("status") == "restored"
                    and result["cleanup"].get("ok") is True
                    and result["cleanup"].get("status") == "removed")
    return result
