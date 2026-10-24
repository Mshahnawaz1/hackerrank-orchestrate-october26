"""Orchestrates the per-case agents:

intent -> identity -> linker -> state -> policy -> planner -> serializer

The one-time stages (evidence ingestion, intent cache) and the workflow-to-request assignment
over the shared activity stream are built once in `Context`.
"""
import sys
from collections import defaultdict
from dataclasses import dataclass

from . import activity, config, ingest, intent, io, linker, planner, serialize, state
from .identity import IdentityResolver
from .policy import PolicyEngine


@dataclass
class CaseResult:
    row: dict
    intent: intent.IntentResult
    case: linker.LinkedCase | None = None
    states: dict | None = None
    verdicts: list | None = None


class Context:
    """Shared, read-only inputs for every case."""

    def __init__(self, requests: list[dict]):
        self.store, _ = ingest.ingest_all()
        self.activity = activity.ActivityIndex(io.load_activity())
        self.resolver = IdentityResolver(io.load_identities(), io.load_audit_log())
        self.policy = PolicyEngine(io.load_rules())
        # workflow rows are assigned over every known request: batches mix both request files
        everyone = {r["case_id"]: r for r in io.load_requests(sample=True) + io.load_requests()}
        everyone.update({r["case_id"]: r for r in requests})
        self.intents = intent.classify_cached(r["request_text"] for r in everyone.values())
        self.identities = {cid: self.resolver.resolve(r["email"], r["audit_at"])
                           for cid, r in everyone.items()
                           if self.intents[r["request_text"]].authorizes_deletion is not False}
        owners = defaultdict(set)
        for obs in self.store.observations:
            owners[obs.resource_id] |= obs.identifiers
        self.workflows = activity.assign_workflows(list(everyone.values()), self.identities, owners, self.activity)
        self.workflow_owner = {row["resource_id"]: cid for cid, rows in self.workflows.items() for row in rows}


def fallback_row(case_id: str) -> dict:
    return {"case_id": case_id, "deletion_status": config.FALLBACK_STATUS, "steps_json": "[]"}


def solve_case(request: dict, ctx: Context) -> CaseResult:
    case_id = request["case_id"]
    request_intent = ctx.intents[request["request_text"]]
    if request_intent.authorizes_deletion is False:
        row = {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}
        return CaseResult(row, request_intent)

    identity = ctx.identities[case_id]
    claimed = frozenset(rid for rid, owner in ctx.workflow_owner.items() if owner != case_id)
    case = linker.link(identity, request["audit_at"], ctx.store, ctx.activity, ctx.workflows.get(case_id, []),
                       claimed)
    states = state.reconstruct(case, ctx.store)
    verdicts = [v for v in (ctx.policy.evaluate(s) for s in states.values()) if v is not None]
    status, steps = planner.plan(verdicts)
    row = fallback_row(case_id) if not steps else {
        "case_id": case_id, "deletion_status": status, "steps_json": serialize.serialize_steps(steps)}
    return CaseResult(row, request_intent, case, states, verdicts)


def run(requests: list[dict], ctx: Context | None = None) -> list[dict]:
    """Solve every request; a per-case failure yields the fallback row instead of crashing the batch."""
    ctx = ctx or Context(requests)
    rows = []
    for req in requests:
        try:
            rows.append(solve_case(req, ctx).row)
        except Exception as e:
            print(f"{req['case_id']}: fallback after error: {e!r}", file=sys.stderr)
            rows.append(fallback_row(req["case_id"]))
    return sorted(rows, key=lambda r: r["case_id"])
