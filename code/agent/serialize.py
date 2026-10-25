"""Step ordering, deterministic JSON serialization and output validation."""
import json

from . import config


def sort_steps(steps: list[dict]) -> list[dict]:
    """Canonical order: phase, operation (table order), system_id, resource_id."""
    return sorted(steps, key=lambda s: (config.PHASE_RANK[s["phase"]], config.OP_RANK[s["operation"]],
                                        s["system_id"], s["resource_id"]))


def serialize_steps(steps: list[dict]) -> str:
    """Sort canonically, renumber from 1 and emit compact JSON with a fixed key order."""
    out = []
    for i, s in enumerate(sort_steps(steps), 1):
        s = dict(s, step_no=i)
        out.append({k: s.get(k, "") for k in config.STEP_FIELDS})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def validate_row(case_id: str, status: str, steps_json: str, audit_at: str | None = None,
                 captured: dict | None = None) -> list[str]:
    """Return a list of contract violations (empty when valid).

    audit_at and captured (file_id -> captured_at) enable the evidence-time check.
    """
    errs = []
    if status not in config.STATUSES:
        errs.append(f"{case_id}: bad status {status!r}")
    try:
        steps = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return errs + [f"{case_id}: steps_json invalid ({e})"]
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        return errs + [f"{case_id}: steps_json must be an array of objects"]
    if status == "NOT_APPLICABLE" and steps:
        errs.append(f"{case_id}: NOT_APPLICABLE must have []")
    if status == "COMPLETE" and (not steps or any(s.get("phase") != "VERIFICATION" for s in steps)):
        errs.append(f"{case_id}: COMPLETE must have only VERIFICATION steps")
    if status == "INCOMPLETE" and steps and not any(s.get("phase") == "FINDING" for s in steps):
        errs.append(f"{case_id}: INCOMPLETE with steps must have a FINDING")

    seen = set()
    for i, s in enumerate(steps, 1):
        if set(s) != set(config.STEP_FIELDS):
            errs.append(f"{case_id}: step {i} has wrong fields")
            continue
        if s["step_no"] != i:
            errs.append(f"{case_id}: step_no {s['step_no']} != {i}")
        if config.OPERATIONS.get(s["operation"]) != (s["phase"], s["state"]):
            errs.append(f"{case_id}: step {i} bad operation/phase/state")
        key = tuple(s[k] for k in config.STEP_FIELDS[1:])
        if key in seen:
            errs.append(f"{case_id}: step {i} duplicates an earlier step")
        seen.add(key)

        evidence = s["evidence_id"]
        cites = s["phase"] == "FINDING" or (s["phase"] == "VERIFICATION" and status == "COMPLETE")
        if cites and not evidence:
            errs.append(f"{case_id}: step {i} missing evidence_id")
        if not cites and evidence:
            errs.append(f"{case_id}: step {i} must have empty evidence_id")
        if evidence and audit_at and captured and captured.get(evidence, "") > audit_at:
            errs.append(f"{case_id}: step {i} cites {evidence} captured after audit_at")

    ordered = all(s["phase"] in config.PHASE_RANK and s["operation"] in config.OP_RANK for s in steps)
    if ordered and sort_steps(steps) != steps:
        errs.append(f"{case_id}: steps not in canonical order")
    return errs


def validate_output(rows: list[dict], requests: list[dict], captured: dict | None = None) -> list[str]:
    """requests: dicts with case_id and audit_at; captured: file_id -> captured_at."""
    errs = []
    ids = [r["case_id"] for r in rows]
    if ids != sorted(ids):
        errs.append("rows not sorted by case_id")
    if sorted(ids) != sorted(r["case_id"] for r in requests) or len(set(ids)) != len(ids):
        errs.append("case_id set differs from requests")
    audit_at = {r["case_id"]: r["audit_at"] for r in requests}
    for r in rows:
        errs += validate_row(r["case_id"], r["deletion_status"], r["steps_json"],
                             audit_at.get(r["case_id"]), captured)
    return errs
