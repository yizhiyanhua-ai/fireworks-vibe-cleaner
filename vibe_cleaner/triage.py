"""Fast, explainable Jev routing. Produces advice, never an executable plan.

Local facts and hard boundaries precede one atomic Choice per file. Action and
reason share one choice, so independently generated answers cannot contradict.
Full source/archive hashes belong to the later, explicitly reviewed plan.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
import urllib.request

from . import jev, sessions
from .common import Json, Refused, candidate_fd
from .scan import transcript_id

MAX_CANDIDATES = 100
BATCH_SIZE = 8
MAX_WORKERS = 3
CONFIDENCE_FLOOR = 0.5  # Conservative routing rule, not an empirically calibrated safety threshold.
GOALS = {"balanced", "reclaim-space", "preserve-history"}

# Every choice binds an action to a reason supported by local facts. These are
# descriptions authored by the project, not free-text reasoning emitted by Jev.
OPTIONS = {
    "keep_in_place": ("keep", "Retain the original; no change is justified by the available facts.",
                      "保留原件", "现有事实不足以证明需要变更，保留现状"),
    "review_uncertain": ("review", "Defer: the user's recovery needs or necessary safety facts are unknown.",
                         "待人工判断", "使用需求或必要条件仍不明确，先确认再定处理方式"),
    "backup_preserve_history": ("backup", "Preserve potentially valuable history: create or reuse a verified backup and keep the original.",
                                "备份并保留原件", "内容可能仍有价值，建立或复用校验通过的备份，同时保留原件"),
    "prepare_verified_removal": ("prepare_removal", "For an old main transcript, prepare a backup-then-remove proposal to reclaim space. Verify or create a backup first; removal is conditional on protection/activity checks and human approval. Age does not mean worthless.",
                                 "准备备份后移除方案", "旧主会话可评估用备份保留历史、减少原件占用；须先核验保护状态和备份，再由用户决定是否移除"),
    "prepare_disposable_cleanup": ("prepare_cache_cleanup", "Prepare quarantine and separately approved purge for a locally eligible old log or rebuildable cache; the user must decide if debugging history is still needed.",
                                   "准备日志/缓存清理方案", "通过旧日志或可重建缓存的本地检查，可评估清理；仍须确认排障需求和写入状态"),
}


def evidence(items: list[Json], inventory: Json) -> list[Json]:
    """Cheap local evidence; never hash entire transcripts or archives here."""
    checked = jev.local_evidence(items, inventory)
    rows = []
    current_id = os.getenv("CODEX_THREAD_ID")
    for item in checked:
        known_current = bool(current_id and item.get("adapter") == "codex"
                             and transcript_id(item["relative"], "codex") == current_id)
        main = False
        if item["category"] == "session" and item["local_policy_checked"] and not known_current:
            try:
                sessions.validate_source(item, inventory["min_age_days"], inventory.get("keep", []))
                with candidate_fd(item) as fd:
                    sessions.check_header(fd, item)
                main = True
            except (Refused, OSError, ValueError, KeyError):
                pass
        protected = not item["local_policy_checked"] or known_current or item["category"] in {"protected", "worktree"}
        size = item["identity"]["size"]
        age = max(0, (time.time_ns() - item["identity"]["mtime_ns"]) / 86400e9)
        facts = {
            "category": item["category"] if item["category"] in {"session", "log", "bytecode", "checkpoint", "asset", "worktree"} else "protected",
            "size_band": "over_1_gib" if size >= 1024**3 else "over_1_mib" if size >= 1024**2 else "under_1_mib",
            "retention_met": bool(item["retention_met"]),
            "protected": protected, "old_main_header_recognized": main,
            "disposable_policy_checked": bool(item["eligible"] and not protected),
            "backup_candidate": bool(item["backup_eligible"] and not protected),
            "backup_status": "not_checked", "activity": "not_checked",
            "index_pin_and_lineage": "not_checked", "future_use": "unknown",
        }
        rows.append({"id": item["id"], "path": str(Path(item["root"]) / item["relative"]),
                     "size_bytes": size, "age_days": round(age, 1), "facts": facts})
    return rows


def allowed(facts: Json) -> list[str]:
    keys = ["keep_in_place", "review_uncertain"]
    category = facts["category"]
    if facts["protected"] or category in {"protected", "worktree"}:
        return keys
    if facts["backup_candidate"] and category in {"session", "checkpoint", "asset"}:
        keys.append("backup_preserve_history")
    if category == "session" and facts["old_main_header_recognized"] and facts["retention_met"]:
        keys.append("prepare_verified_removal")
    if category in {"log", "bytecode"} and facts["disposable_policy_checked"] and facts["retention_met"]:
        keys.append("prepare_disposable_cleanup")
    return keys


def packet(rows: list[Json], goal: str = "balanced") -> Json:
    if goal not in GOALS or not 1 <= len(rows) <= BATCH_SIZE:
        raise Refused("Invalid triage goal or batch size")
    # Facts have a closed vocabulary. Do not copy untrusted text from an inventory.
    candidates = []
    for row in rows:
        f = row["facts"]
        candidates.append({
            "category": f["category"] if f.get("category") in {"session", "log", "bytecode", "checkpoint", "asset", "worktree"} else "protected",
            "size_band": f["size_band"] if f.get("size_band") in {"over_1_gib", "over_1_mib", "under_1_mib"} else "unknown",
            **{k: f.get(k) is True for k in ("retention_met", "old_main_header_recognized", "disposable_policy_checked", "backup_candidate")},
            "protected": f.get("protected") is not False,
            "backup_status": "not_checked", "activity": "not_checked",
            "index_pin_and_lineage": "not_checked", "future_use": "unknown",
        })
    questions = {f"c{n}": {
        "type": "choice",
        "instructions": f"For state.candidates[{n}] only, choose the next review step for goal '{goal}'. "
                        "Use the stated facts. All options are advice; none permit execution. "
                        "A preparation option proposes further verification, not safe removal now. "
                        "Backup retains the original and reclaims zero bytes. Old/large does not prove low value. "
                        "Choose review_uncertain when these options do not resolve the missing evidence.",
        "criteria": {key: OPTIONS[key][1] for key in allowed(f)},
    } for n, f in enumerate(candidates)}
    return {"model": "jev-latest", "state": {"candidates": candidates}, "questions": questions}


def run(inventory: Json, ids: list[str] | None = None, *, limit: int = 40, goal: str = "balanced",
        enabled: bool = False,
        transport: Callable[[urllib.request.Request, float], Any] | None = None) -> Json:
    started = time.monotonic()
    if goal not in GOALS or not 1 <= limit <= MAX_CANDIDATES:
        raise Refused("Triage needs a supported goal and a limit of 1..100")
    if ids is not None:
        if not 1 <= len(ids) <= MAX_CANDIDATES or len(set(ids)) != len(ids):
            raise Refused("Select 1..100 unique candidate IDs")
        selected_ids = set(ids)
        items = [i for i in inventory["items"] if i["id"] in selected_ids]
        if len(items) != len(ids):
            raise Refused("Unknown candidate ID")
    else:
        items = sorted((i for i in inventory["items"] if i["category"] in {"session", "log", "bytecode", "checkpoint", "asset"}),
                       key=lambda i: i["identity"]["size"], reverse=True)[:limit]
    rows = evidence(items, inventory)
    evidence_ms = round((time.monotonic() - started) * 1000)
    batches = [rows[n:n + BATCH_SIZE] for n in range(0, len(rows), BATCH_SIZE)]
    requests = [packet(batch, goal) for batch in batches]
    payload_sizes = [len(json.dumps(p).encode()) for p in requests]
    if any(size > 16384 for size in payload_sizes) or sum(payload_sizes) > 208 * 1024:
        raise Refused("Triage request budget exceeded")
    provider_start = time.monotonic()
    def call(request: Json) -> Json:
        return jev.request_advice(request, enabled=enabled, transport=transport)
    # Bounded fan-out. Each request itself evaluates independent questions in parallel.
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures = []
    try:
        futures = [pool.submit(call, request) for request in requests]
        replies = [future.result() for future in futures]
    except BaseException:
        # Ctrl-C must not leave queued paid calls running. At most MAX_WORKERS
        # already-started requests can finish; a submitted request cannot be revoked.
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    provider_wall_ms = round((time.monotonic() - provider_start) * 1000)
    decisions = []
    for batch, request, reply in zip(batches, requests, replies):
        for n, row in enumerate(batch):
            choices = request["questions"][f"c{n}"]["criteria"]
            answer = reply.get("answers", {}).get(f"c{n}")
            choice = answer["choice"] if answer else "review_uncertain"
            overridden = bool(answer and answer["confidence"] < CONFIDENCE_FLOOR)
            if overridden:
                choice = "review_uncertain"
            decisions.append({**row, "action": OPTIONS[choice][0], "reason_code": choice,
                              "source": "jev-low-confidence" if overridden else "jev" if answer else "local-fallback",
                              "provider_status": reply["status"], "provider_choice": answer["choice"] if answer else None,
                              "confidence": answer["confidence"] if answer else None,
                              "probabilities": answer["probabilities"] if answer else {},
                              "alternatives": list(choices), "executable": False,
                              "required_next": "Fresh protection/activity checks, verified backup if transcript removal, exact plan and human approval"})
    return {"schema": 1, "kind": "triage-advice", "goal": goal, "executable": False,
            "actual_reclaimed_bytes": 0, "confidence_floor": CONFIDENCE_FLOOR,
            "scan_complete": inventory.get("complete", False), "inventory_files": len(inventory["items"]),
            "selected_files": len(rows), "not_selected_files": len(inventory["items"]) - len(rows),
            "selection": "explicit-ids" if ids is not None else "largest-within-limit",
            "selected_logical_bytes": sum(r["size_bytes"] for r in rows),
            "action_counts": dict(Counter(d["action"] for d in decisions)), "decisions": decisions,
            "timing": {"local_evidence_ms": evidence_ms, "provider_wall_ms": provider_wall_ms,
                       "total_ms": round((time.monotonic() - started) * 1000)},
            "provider": {"calls": sum(r["calls"] for r in replies), "batches": len(batches),
                         "max_concurrency": MAX_WORKERS, "request_bytes": sum(payload_sizes),
                         "statuses": dict(Counter(r["status"] for r in replies)),
                         "models": sorted({r["model"] for r in replies if "model" in r}),
                         "input_tokens": sum(r.get("usage", {}).get("input_tokens", 0) for r in replies),
                         "output_tokens": sum(r.get("usage", {}).get("output_tokens", 0) for r in replies)}}


def render(report: Json, language: str = "zh") -> str:
    """Private terminal report: every selected file, explanation, alternatives and impact."""
    zh = language == "zh"
    lines = ["筛选建议（未执行清理，不是可执行计划）" if zh else "Triage advice (no cleanup; not an executable plan)",
             f"{report['selected_files']} files / {report['selected_logical_bytes']} bytes; "
             f"Jev calls={report['provider']['calls']}, total={report['timing']['total_ms']} ms; reclaimed=0 bytes.",
             ("范围：" if zh else "Scope: ") + report["selection"] +
             f"; not selected={report['not_selected_files']}; scan complete={report['scan_complete']}",
             ""]
    for n, d in enumerate(report["decisions"], 1):
        option = OPTIONS[d["reason_code"]]
        name, reason = (option[2], option[3]) if zh else (option[0], option[1])
        # JSON quoting neutralizes terminal controls and ambiguous filenames.
        path = json.dumps(d["path"], ensure_ascii=True)
        facts = d["facts"]
        fact_text = (f"类别={facts['category']}；满足保留期={facts['retention_met']}；"
                     f"识别为旧主会话头={facts['old_main_header_recognized']}；保护/检查未通过={facts['protected']}"
                     if zh else json.dumps(facts))
        lines.extend([f"{n}. {path}", f"   {d['size_bytes']} bytes; age={d['age_days']} days; source={d['source']}",
                      f"   {'建议' if zh else 'Recommend'}: {name}",
                      f"   {'理由' if zh else 'Reason'}: {reason}",
                      f"   {'本地事实' if zh else 'Facts'}: {fact_text}",
                      f"   {'备选' if zh else 'Alternatives'}: " + " / ".join(
                          OPTIONS[k][2] if zh else OPTIONS[k][0] for k in d["alternatives"] if k != d["reason_code"])])
        if d["source"] == "jev-low-confidence":
            provider_option = OPTIONS[d["provider_choice"]]
            lines.append(f"   Jev: {provider_option[2] if zh else provider_option[0]}; "
                         f"confidence={d['confidence']} < {report['confidence_floor']}; "
                         + ("按本地规则转人工复核" if zh else "routed to review by local policy"))
    lines.extend(["", "备份：保留原件，释放 0 字节。移除方案：须验证备份并确认保护/活跃状态；移除后历史可能不可用，恢复文件不保证原生续聊。"
                  if zh else "Backup retains originals and reclaims zero bytes. Removal preparation requires verified backups and protection/activity checks; history may become unavailable and file restoration does not prove resume.",
                  "尚未检查备份、活跃状态和索引保护关系；没有读取正文判断价值。建议理由由固定选项渲染，confidence 不是删除安全概率。"
                  if zh else "Backups, activity and index protection have not been checked. No content-value analysis. Reasons render fixed choices; confidence is not deletion safety.",
                  "选定范围后生成完整计划，在对话里显示逐项方法、影响、备份位置和 plan hash，经人工明确确认才能执行。"
                  if zh else "After selecting a scope, prepare a full plan and show every method, impact, backup location and plan hash in chat; explicit human confirmation is required before execution."])
    return "\n".join(lines)
