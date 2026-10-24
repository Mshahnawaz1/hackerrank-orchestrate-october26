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


def validate_row(case_id: str, status: str, steps_json: str) -> list[str]:
    """Return a list of contract violations (empty when valid)."""
    errs = []
    if status not in config.STATUSES:
        errs.append(f"{case_id}: bad status {status!r}")
    try:
        steps = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return errs + [f"{case_id}: steps_json invalid ({e})"]
    if not isinstance(steps, list):
        return errs + [f"{case_id}: steps_json not an array"]
    if status == "NOT_APPLICABLE" and steps:
        errs.append(f"{case_id}: NOT_APPLICABLE must have []")
    last_rank = 0
    seen = set()
    for i, s in enumerate(steps, 1):
        if set(s) != set(config.STEP_FIELDS):
            errs.append(f"{case_id}: step {i} has wrong fields")
            continue
        if s["step_no"] != i:
            errs.append(f"{case_id}: step_no {s['step_no']} != {i}")
        op = config.OPERATIONS.get(s["operation"])
        if not op or op != (s["phase"], s["state"]):
            errs.append(f"{case_id}: step {i} bad operation/phase/state")
        key = tuple(s[k] for k in config.STEP_FIELDS[1:])
        if key in seen:
            errs.append(f"{case_id}: step {i} duplicates an earlier step")
        seen.add(key)
        rank = config.PHASE_RANK.get(s["phase"], -1)
        if rank < last_rank:
            errs.append(f"{case_id}: step {i} phase out of order")
        last_rank = max(last_rank, rank)
        needs_evidence = s["phase"] == "FINDING" or (
            s["phase"] == "VERIFICATION" and status == "COMPLETE")
        if needs_evidence and not s["evidence_id"]:
            errs.append(f"{case_id}: step {i} missing evidence_id")
        if s["phase"] == "REMEDIATION" and s["evidence_id"]:
            errs.append(f"{case_id}: step {i} remediation must have empty evidence_id")
    return errs


def validate_output(rows: list[dict], request_ids: list[str]) -> list[str]:
    errs = []
    ids = [r["case_id"] for r in rows]
    if ids != sorted(ids):
        errs.append("rows not sorted by case_id")
    if sorted(ids) != sorted(request_ids) or len(set(ids)) != len(ids):
        errs.append("case_id set differs from requests")
    for r in rows:
        errs += validate_row(r["case_id"], r["deletion_status"], r["steps_json"])
    return errs
