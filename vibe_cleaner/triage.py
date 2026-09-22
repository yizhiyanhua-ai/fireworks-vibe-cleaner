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

from . import jev, purpose, sessions, triage_evidence
from .common import Json, Refused, candidate_fd
from .scan import transcript_id

MAX_CANDIDATES = 100
BATCH_SIZE = 8
MAX_WORKERS = 3
CONFIDENCE_FLOOR = 0.5  # Preparation advice only; not calibrated deletion safety.
GOALS = {"balanced", "reclaim-space", "preserve-history"}

# Every choice binds an action to a reason supported by local facts. These are
# descriptions authored by the project, not free-text reasoning emitted by Jev.
OPTIONS = {
    "keep_protected": ("keep", "Local protection or activity prohibits cleanup; retain this object.",
                       "本地保护，保留不动", "命中保护、活跃或关联条件，本地规则已排除清理"),
    "keep_in_place": ("keep", "Retain the original; no change is justified by the available facts.",
                      "保留原件", "现有事实不足以证明需要变更，保留现状"),
    "review_uncertain": ("review", "Defer only when evidence needed for the next step is missing. Unknown recovery need blocks removal, not backup verification or preserving originals.",
                         "待人工判断", "使用需求或必要条件仍不明确，先确认再定处理方式"),
    "backup_preserve_history": ("backup", "Preserve potentially valuable history: create or reuse a verified backup and keep the original.",
                                "备份并保留原件", "内容可能仍有价值，建立或复用校验通过的备份，同时保留原件"),
    "reuse_verified_backup": ("keep", "A selected backup member matches this source now; keep both the backup and the original for convenient access.",
                             "复用已核验备份，保留原件", "选中备份成员与当前原件字节一致；继续保留原件便于访问，无需重复备份"),
    "verify_existing_backup": ("verify_backup", "A matching backup record exists, but its bytes are unverified. Check that existing copy before creating a duplicate backup; retain the original.",
                               "先校验现有备份，保留原件", "已有对应备份记录，尚未核验内容；优先检查现有副本，避免重复备份增加占用"),
    "prepare_verified_removal": ("prepare_removal", "A selected backup member matches the old main transcript now; the user accepts archive-copy recovery, selected index checks found no pin or indexed links, and no open handle was observed. Propose retaining that backup and removing the original to reclaim space. A fresh full plan, protection checks and explicit human approval are still required; native resume is unverified.",
                                 "准备保留备份、移除原件方案", "选中备份成员与当前原件字节一致，用户接受副本恢复，所选索引未见置顶或关联且未发现打开句柄；可准备移除原件方案，完整保护复核与人工批准仍不可省略"),
    "prepare_disposable_cleanup": ("prepare_cache_cleanup", "Prepare quarantine and separately approved purge for a locally eligible old log or rebuildable cache; the user must decide if debugging history is still needed.",
                                   "准备日志/缓存清理方案", "通过旧日志或可重建缓存的本地检查，可评估清理；仍须确认排障需求和写入状态"),
}


def evidence(items: list[Json], inventory: Json, *, archives: list[Path] | None = None,
             max_verify_bytes: int = 0, inspect_activity: bool = False,
             recovery_need: str = "unknown", details: Json | None = None,
             purpose_notes: Json | None = None, inspect_purpose: bool = True) -> list[Json]:
    """Fresh bounded facts. Selected backup bytes are checked only within an explicit budget."""
    if recovery_need not in triage_evidence.RECOVERY_NEEDS:
        raise Refused("Unknown user recovery preference")
    started = time.monotonic()
    checked = jev.local_evidence(items, inventory)
    indexed = triage_evidence.index_facts(checked, inventory["min_age_days"])
    index_ms = round((time.monotonic() - started) * 1000)
    active_start = time.monotonic()
    active = triage_evidence.activity([i for i in checked if i["local_policy_checked"]
                                       and i["category"] not in {"protected", "worktree"}]) if inspect_activity else {}
    activity_ms = round((time.monotonic() - active_start) * 1000)
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
        index = indexed[item["id"]]
        activity = active.get(item["id"], "not_checked" if not inspect_activity else "unknown")
        protected = (not item["local_policy_checked"] or known_current or item["category"] in {"protected", "worktree"}
                     or index["pin"] == "pinned" or index["links"] == "linked" or activity == "open"
                     or index["current_context"] == "current")
        size = item["identity"]["size"]
        age = max(0, (time.time_ns() - item["identity"]["mtime_ns"]) / 86400e9)
        facts = {
            "category": item["category"] if item["category"] in {"session", "log", "bytecode", "checkpoint", "asset", "worktree"} else "protected",
            "size_band": "over_1_gib" if size >= 1024**3 else "100_mib_to_1_gib" if size >= 100 * 1024**2
                         else "10_to_100_mib" if size >= 10 * 1024**2 else "1_to_10_mib" if size >= 1024**2 else "under_1_mib",
            "age_band": "over_90_days" if age >= 90 else "30_to_90_days" if age >= 30 else "under_30_days",
            "retention_met": bool(item["retention_met"]),
            "protected": protected, "old_main_header_recognized": main,
            "disposable_policy_checked": bool(item["eligible"] and not protected),
            "backup_candidate": bool(item["backup_eligible"] and not protected),
            "backup_status": "not_checked", "activity": activity,
            **{key: index[key] for key in ("pin", "links", "archived", "recent_use", "current_context")},
            "recovery_need": recovery_need, "future_use": "unknown",
        }
        rows.append({"id": item["id"], "path": str(Path(item["root"]) / item["relative"]),
                     "size_bytes": size, "age_days": round(age, 1), "facts": facts, "index_evidence": index})
    purpose_start = time.monotonic()
    cards = purpose.collect(checked, {r["id"] for r in rows if r["facts"]["protected"]},
                            notes=purpose_notes, enabled=inspect_purpose)
    for row in rows:
        card = cards[row["id"]]
        row["purpose_evidence"] = card
        row["facts"].update(purpose.provider_facts(card))
        if purpose.keep_needed(row["facts"]) or card["coverage"] == "unavailable":
            row["facts"].update(protected=True, backup_candidate=False, disposable_policy_checked=False)
    purpose_ms = round((time.monotonic() - purpose_start) * 1000)
    backup_start = time.monotonic()
    backup_ids = {row["id"] for row in rows if row["facts"]["backup_candidate"]}
    backup_evidence = triage_evidence.backups([i for i in checked if i["id"] in backup_ids], archives or [],
                                             max_verify_bytes=max_verify_bytes)
    for row in rows:
        proof = backup_evidence["items"].get(row["id"], {"status": "not_checked"})
        row["facts"]["backup_status"] = proof["status"]
        row["backup_evidence"] = proof
    if details is not None:
        details.update(index_and_policy_ms=index_ms, activity_ms=activity_ms, purpose_ms=purpose_ms,
                       purpose_read_bytes=sum(c["bytes_read"] for c in cards.values()),
                       backup_ms=round((time.monotonic() - backup_start) * 1000),
                       backup={k: v for k, v in backup_evidence.items() if k != "items"},
                       recovery_need=recovery_need, inspected_activity=inspect_activity,
                       distinct_fact_patterns=len({json.dumps(r["facts"], sort_keys=True) for r in rows}))
    return rows


def allowed(facts: Json) -> list[str]:
    keys = ["keep_in_place", "review_uncertain"]
    category = facts["category"]
    if (facts["protected"] or purpose.keep_needed(facts) or category in {"protected", "worktree"} or facts.get("pin") == "pinned"
            or facts.get("links") == "linked" or facts.get("activity") == "open"
            or facts.get("current_context") == "current"):
        return keys
    verified = facts.get("backup_status") == "selected_bytes_verified"
    if facts["backup_candidate"] and category in {"session", "checkpoint", "asset"}:
        keys.append("reuse_verified_backup" if verified else "backup_preserve_history")
        if facts.get("backup_status") == "manifest_only":
            keys.append("verify_existing_backup")
    if (category == "session" and facts.get("plan_event") != "pending-plan-seen" and facts["old_main_header_recognized"] and facts["retention_met"] and verified
            and facts.get("recovery_need") == "archive-copy" and facts.get("pin") == "unpinned"
            and facts.get("links") == "no_indexed_links" and facts.get("recent_use") == "old"
            and facts.get("current_context") == "other" and facts.get("activity") == "no_open_handles"):
        keys.append("prepare_verified_removal")
    if (category in {"log", "bytecode"} and facts.get("plan_event") != "pending-plan-seen" and facts["disposable_policy_checked"] and facts["retention_met"]
            and facts.get("activity") == "no_open_handles"):
        keys.append("prepare_disposable_cleanup")
    return keys


def packet(rows: list[Json], goal: str = "balanced") -> Json:
    if goal not in GOALS or not 1 <= len(rows) <= BATCH_SIZE:
        raise Refused("Invalid triage goal or batch size")
    # Facts have a closed vocabulary. Do not copy untrusted text from an inventory.
    candidates = []
    for row in rows:
        f = row["facts"]
        def enum(key: str, values: set[str], default: str = "unknown") -> str:
            value = f.get(key)
            return value if isinstance(value, str) and value in values else default
        candidates.append({
            "category": f["category"] if f.get("category") in {"session", "log", "bytecode", "checkpoint", "asset", "worktree"} else "protected",
            "size_band": enum("size_band", {"over_1_gib", "100_mib_to_1_gib", "10_to_100_mib", "1_to_10_mib", "under_1_mib"}),
            "age_band": enum("age_band", {"over_90_days", "30_to_90_days", "under_30_days"}),
            **{k: f.get(k) is True for k in ("retention_met", "old_main_header_recognized", "disposable_policy_checked", "backup_candidate")},
            "protected": f.get("protected") is not False,
            "backup_status": enum("backup_status", {"not_checked", "no_match_supplied", "manifest_only", "selected_bytes_verified", "invalid", "ambiguous"}),
            "activity": enum("activity", {"not_checked", "no_open_handles", "open"}),
            "pin": enum("pin", {"pinned", "unpinned"}),
            "links": enum("links", {"linked", "no_indexed_links"}),
            "archived": enum("archived", {"yes", "no"}),
            "recent_use": enum("recent_use", {"old", "recent"}),
            "current_context": enum("current_context", {"current", "other"}),
            "recovery_need": enum("recovery_need", triage_evidence.RECOVERY_NEEDS), "future_use": "unknown",
            "purpose_role": enum("purpose_role", purpose.ROLES),
            "purpose_origin": enum("purpose_origin", purpose.ORIGINS),
            "continuation": enum("continuation", purpose.CONTINUATION),
            "purpose_coverage": enum("purpose_coverage", purpose.COVERAGE),
            "turn_event": enum("turn_event", purpose.TURN_EVENTS), "plan_event": enum("plan_event", purpose.PLAN_EVENTS),
        })
    questions = {f"c{n}": {
        "type": "choice",
        "instructions": f"For state.candidates[{n}] only, choose the next step for goal '{goal}'. "
                        "Pick a useful next step that retains originals whenever removal is unavailable. "
                        "Unknown recovery need only blocks removal. A turn completion is not project completion; "
                        "purpose tags are source-bound judgments, not verified value or deletion approval. "
                        "Do not infer unused or worthless from old/large. Review only if the next step lacks necessary evidence.",
        "criteria": {key: OPTIONS[key][1] for key in allowed(f)},
    } for n, f in enumerate(candidates)}
    return {"model": "jev-latest", "state": {"candidates": candidates}, "questions": questions}


def run(inventory: Json, ids: list[str] | None = None, *, limit: int = 40, goal: str = "balanced",
        enabled: bool = False, archives: list[Path] | None = None, max_verify_bytes: int = 0,
        inspect_activity: bool = True, recovery_need: str = "unknown",
        purpose_notes: Json | None = None, inspect_purpose: bool = True, advisor: str = "jev",
        transport: Callable[[urllib.request.Request, float], Any] | None = None) -> Json:
    started = time.monotonic()
    if goal not in GOALS or advisor not in {"jev", "rules"} or not 1 <= limit <= MAX_CANDIDATES:
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
    details: Json = {}
    rows = evidence(items, inventory, archives=archives, max_verify_bytes=max_verify_bytes,
                    inspect_activity=inspect_activity, recovery_need=recovery_need, details=details,
                    purpose_notes=purpose_notes, inspect_purpose=inspect_purpose)
    evidence_ms = round((time.monotonic() - started) * 1000)
    evaluated = rules(rows, goal=goal) if advisor == "rules" else decide(rows, goal=goal, enabled=enabled, transport=transport)
    return {"schema": 2, "kind": "triage-advice", "goal": goal, "executable": False,
            "actual_reclaimed_bytes": 0, "confidence_floor": CONFIDENCE_FLOOR,
            "scan_complete": inventory.get("complete", False), "inventory_files": len(inventory["items"]),
            "selected_files": len(rows), "not_selected_files": len(inventory["items"]) - len(rows),
            "selection": "explicit-ids" if ids is not None else "largest-within-limit",
            "selected_logical_bytes": sum(r["size_bytes"] for r in rows),
            "action_counts": dict(Counter(d["action"] for d in evaluated["decisions"])),
            "decisions": evaluated["decisions"], "evidence": details,
            "timing": {"local_evidence_ms": evidence_ms, "provider_wall_ms": evaluated["provider_wall_ms"],
                       "total_ms": round((time.monotonic() - started) * 1000)}, "provider": evaluated["provider"]}


def decide(rows: list[Json], *, goal: str = "balanced", enabled: bool = False,
           transport: Callable[[urllib.request.Request, float], Any] | None = None) -> Json:
    """Evaluate prepared facts without IO/mutation authority; useful for frozen-request comparisons."""
    if goal not in GOALS or len(rows) > MAX_CANDIDATES or len({r["id"] for r in rows}) != len(rows):
        raise Refused("Invalid prepared candidate set")
    protected = [r for r in rows if r["facts"]["protected"] or purpose.keep_needed(r["facts"])]
    protected_ids = {r["id"] for r in protected}
    reviewable = [r for r in rows if r["id"] not in protected_ids]
    batches = [reviewable[n:n + BATCH_SIZE] for n in range(0, len(reviewable), BATCH_SIZE)]
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
            purpose_missing = (choice == "backup_preserve_history" and goal != "preserve-history"
                               and row["facts"].get("purpose_role", "unknown") == "unknown")
            low = bool(answer and answer["confidence"] < CONFIDENCE_FLOOR)
            overridden = low and OPTIONS[choice][0] in {"prepare_removal", "prepare_cache_cleanup"}
            tentative = low and not overridden and not purpose_missing and choice != "review_uncertain"
            if overridden or purpose_missing:
                choice = "review_uncertain"
            decisions.append({**row, "action": OPTIONS[choice][0], "reason_code": choice,
                              "source": "local-purpose-review" if purpose_missing else "jev-low-confidence" if overridden else "jev-tentative" if tentative else "jev" if answer else "local-fallback",
                              "provider_status": reply["status"], "provider_choice": answer["choice"] if answer else None,
                              "confidence": answer["confidence"] if answer else None,
                              "probabilities": answer["probabilities"] if answer else {},
                              "probability_rounding_tolerated": answer.get("probability_rounding_tolerated", False) if answer else False,
                              "alternatives": list(choices), "executable": False,
                              "next_checks": purpose.next_checks(row["facts"]),
                              "required_next": "Fresh protection/activity checks, verified backup if transcript removal, exact plan and human approval"})
    for row in protected:
        decisions.append({**row, "action": "keep", "reason_code": "keep_protected", "source": "local-protection",
                          "provider_status": "not-called-local-protection", "provider_choice": None, "confidence": None,
                          "probabilities": {}, "alternatives": ["keep_protected"], "executable": False,
                          "next_checks": purpose.next_checks(row["facts"]),
                          "required_next": "Retain; do not prepare a cleanup plan for a protected object"})
    indexed_decisions = {d["id"]: d for d in decisions}
    return {"decisions": [indexed_decisions[r["id"]] for r in rows], "provider_wall_ms": provider_wall_ms,
            "provider": {"calls": sum(r["calls"] for r in replies), "batches": len(batches),
                         "max_concurrency": MAX_WORKERS, "request_bytes": sum(payload_sizes),
                         "locally_protected_files": len(protected),
                         "statuses": dict(Counter(r["status"] for r in replies)),
                         "rounded_distributions": sum(a.get("probability_rounding_tolerated", False) for r in replies for a in r.get("answers", {}).values()),
                         "errors": dict(Counter(r["error_code"] for r in replies if "error_code" in r)),
                         "models": sorted({r["model"] for r in replies if "model" in r}),
                         "input_tokens": sum(r.get("usage", {}).get("input_tokens", 0) for r in replies),
                         "output_tokens": sum(r.get("usage", {}).get("output_tokens", 0) for r in replies)}}



def rules(rows: list[Json], *, goal: str = "balanced") -> Json:
    """Transparent comparison baseline and explicit offline mode, not ground truth."""
    if goal not in GOALS or len(rows) > MAX_CANDIDATES:
        raise Refused("Invalid rules triage selection")
    decisions = []
    for row in rows:
        facts = row["facts"]
        options = allowed(facts)
        choice = "review_uncertain"
        protected = facts["protected"] or purpose.keep_needed(facts)
        if protected:
            choice, options = "keep_protected", ["keep_protected"]
        elif goal == "reclaim-space" and "prepare_verified_removal" in options:
            choice = "prepare_verified_removal"
        elif "reuse_verified_backup" in options:
            choice = "reuse_verified_backup"
        elif "verify_existing_backup" in options:
            choice = "verify_existing_backup"
        elif facts.get("purpose_role") in purpose.ROLES - {"unknown"} and "backup_preserve_history" in options:
            choice = "backup_preserve_history"
        elif "prepare_disposable_cleanup" in options:
            choice = "prepare_disposable_cleanup"
        decisions.append({**row, "action": OPTIONS[choice][0], "reason_code": choice,
                          "source": "local-protection" if protected else "local-rules", "provider_status": "not-called-rules",
                          "provider_choice": None, "confidence": None, "probabilities": {}, "alternatives": options,
                          "executable": False, "next_checks": purpose.next_checks(facts),
                          "required_next": "Advice only; exact plan and human approval before any cleanup"})
    return {"decisions": decisions, "provider_wall_ms": 0,
            "provider": {"calls": 0, "batches": 0, "max_concurrency": 0, "request_bytes": 0,
                         "locally_protected_files": sum(d["source"] == "local-protection" for d in decisions),
                         "statuses": {"local-rules": len(rows)}, "errors": {}, "models": [], "input_tokens": 0, "output_tokens": 0}}


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
        def fact_label(key: str) -> str:
            labels = {
                "unknown": "未知", "not_checked": "未检查", "no_match_supplied": "所提供归档中未匹配",
                "manifest_only": "仅清单匹配，字节未验证", "selected_bytes_verified": "所选原件与备份成员字节一致",
                "invalid": "验证失败", "ambiguous": "对应关系不明确", "no_open_handles": "当次未观察到打开句柄",
                "open": "观察到打开句柄", "pinned": "已置顶", "unpinned": "未置顶",
                "linked": "有关联", "no_indexed_links": "本次索引未发现关联",
                "archive-copy": "用户明确接受文件副本恢复", "native-resume": "需要继续原对话",
                "current": "当前会话", "other": "已知不是当前会话", "old": "超过保留期", "recent": "近期有更新",
            }
            value = facts.get(key, "unknown")
            return labels.get(value, value)
        fact_text = (f"类别={facts['category']}；满足保留期={'是' if facts['retention_met'] else '否'}；"
                     f"备份={fact_label('backup_status')}；活跃={fact_label('activity')}；"
                     f"置顶={fact_label('pin')}；关联={fact_label('links')}；"
                     f"会话身份={fact_label('current_context')}；索引最近更新={fact_label('recent_use')}；"
                     f"恢复需求={fact_label('recovery_need')}"
                     if zh else json.dumps(facts))
        lines.extend([f"{n}. {path}", f"   {d['size_bytes']} bytes; age={d['age_days']} days; source={d['source']}",
                      f"   {'建议' if zh else 'Recommend'}: {name}",
                      f"   {'理由' if zh else 'Reason'}: {reason}",
                      f"   {'本地事实' if zh else 'Facts'}: {fact_text}",
                      f"   {'备选' if zh else 'Alternatives'}: " + " / ".join(
                          OPTIONS[k][2] if zh else OPTIONS[k][0] for k in d["alternatives"] if k != d["reason_code"])])
        purpose_names = {"unknown": "用途未知", "knowledge-reference": "知识参考", "implementation-history": "实现历史",
                         "diagnostic-history": "排障记录", "delivery-record": "交付过程记录", "generated-draft": "生成草稿", "deliverable": "交付素材"}
        origin_names = {"unreviewed": "尚未判断", "local-assistant": "本地助手判断，非用户确认", "user": "用户提供的用途判断"}
        next_names = {"review-observed-pending-plan-before-removal": "移除前核实记录中未完成的计划是否已结束",
                      "retain-and-resolve-protection": "保留；先处理保护或继续使用的需求",
                      "verify-existing-backup-bytes": "先核验已有备份字节，避免重复备份",
                      "review-local-purpose": "补充本地用途判断",
                      "ask-resume-or-file-copy-before-removal": "准备移除前确认：继续对话，还是文件副本即可",
                      "check-project-references-before-any-removal": "检查项目引用；当前素材不支持移除",
                      "refresh-open-handle-check-before-cleanup": "清理前重新检查打开句柄"}
        if zh:
            coverage_names = {"unknown": "未知", "not-read": "未读正文", "full": "按预算读取完整小文件",
                              "head-tail": "仅读取首尾", "partial": "部分记录未能解析", "unavailable": "来源不可用"}
            event_names = {"unknown": "未观察到", "completion-event-seen": "记录了本轮结束", "interruption-event-seen": "记录了中止",
                           "start-event-seen": "记录了开始", "pending-plan-seen": "观察到未完成计划", "completed-plan-seen": "记录了计划完成声明"}
            lines.append("   用途依据: " + purpose_names.get(facts.get("purpose_role"), "用途未知") + "；" +
                         origin_names.get(facts.get("purpose_origin"), "尚未判断") +
                         f"；采样={coverage_names.get(facts.get('purpose_coverage'), '未知')}；轮次={event_names.get(facts.get('turn_event'), '未观察到')}；"
                         f"计划={event_names.get(facts.get('plan_event'), '未观察到')}（均不代表项目完成）")
        checks = d.get("next_checks", [])
        if checks:
            lines.append(("   下一步补查: " if zh else "   Next checks: ") + " / ".join(next_names[k] if zh else k for k in checks))
        backup = d.get("backup_evidence", {})
        if backup.get("archive"):
            lines.append(f"   {'备份位置' if zh else 'Backup location'}: " + json.dumps(backup["archive"], ensure_ascii=True))
        if d["source"] == "local-purpose-review":
            lines.append("   Jev 倾向新增备份，但用途依据缺失；先补用途，避免增加无必要占用" if zh else
                         "   Jev suggested a new backup, but purpose is unknown; review purpose before adding storage")
        if d["source"] == "jev-tentative":
            lines.append(f"   confidence={d['confidence']}; " + ("置信度偏低，仅作为保留原件的可选建议，不自动执行" if zh else "Low confidence: tentative original-preserving suggestion; never automatic execution"))
        if d["source"] == "jev-low-confidence":
            provider_option = OPTIONS[d["provider_choice"]]
            lines.append(f"   Jev: {provider_option[2] if zh else provider_option[0]}; "
                         f"confidence={d['confidence']} < {report['confidence_floor']}; "
                         + ("按本地规则转人工复核" if zh else "routed to review by local policy"))
    lines.extend(["", "备份：保留原件，释放 0 字节。移除方案：须验证备份并确认保护/活跃状态；移除后历史可能不可用，恢复文件不保证原生续聊。"
                  if zh else "Backup retains originals and reclaims zero bytes. Removal preparation requires verified backups and protection/activity checks; history may become unavailable and file restoration does not prove resume.",
                  "备份验证仅涵盖明确标记通过的选中成员，不代表整个归档或原生续聊验证通过。活跃与索引结果是当次观察；未知项须补查。没有读取正文判断价值，confidence 不是删除安全概率。"
                  if zh else "Backup verification covers only explicitly verified selected members, not the whole archive or native resume. Activity/index facts are snapshots; unknowns need checking. No content-value analysis; confidence is not deletion safety.",
                  "选定范围后生成完整计划，在对话里显示逐项方法、影响、备份位置和 plan hash，经人工明确确认才能执行。"
                  if zh else "After selecting a scope, prepare a full plan and show every method, impact, backup location and plan hash in chat; explicit human confirmation is required before execution."])
    return "\n".join(lines)
