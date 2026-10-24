"""System activity: claims about workflow actions, and assignment of workflow rows to cases.

Activity rows never prove a resource's state. They are used to *discover* resources that carry
no identifiers in the evidence (a deleted account, an anonymized analytics profile):

* LINK_RESOURCE_IDENTITY rows name a resource together with an email / user_id.
* The deletion workflow for a request runs shortly before its `reported_at`. Several requests can
  share the same `reported_at`, so workflow rows of one batch are matched to requests by
  (1) identifiers already in the evidence, (2) the workflow result matching the reported status,
  (3) case order against time order.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from .store import EMAIL_RE, USER_RE, norm_email

WORKER = "deletion_worker"
ACCOUNT_PREFIX = "account_"
WINDOW_BEFORE = timedelta(hours=2)          # workflow rows start at most this long before reported_at
WINDOW_AFTER = timedelta(minutes=15)        # account deletion is submitted around reported_at
POLICY_AFTER = timedelta(hours=3)
STATUS_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def case_order(case_id: str) -> tuple:
    """Natural order: case_9 < case_10."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", case_id))


class ActivityIndex:
    def __init__(self, rows: list[dict]):
        self.rows = sorted(rows, key=lambda r: (r["event_time"], r["activity_id"]))
        self.by_resource = defaultdict(list)
        self.links = []                                   # (row, identifiers named in it)
        for r in self.rows:
            self.by_resource[r["resource_id"]].append(r)
            if r["event_type"] == "LINK_RESOURCE_IDENTITY":
                named = {norm_email(e) for e in EMAIL_RE.findall(r["details"])}
                named |= {u.lower() for u in USER_RE.findall(r["details"])}
                self.links.append((r, frozenset(named)))

    def worker_rows(self, start: datetime, end: datetime) -> list[dict]:
        return [r for r in self.rows if r["source_system"] == WORKER and start <= parse_time(r["event_time"]) <= end]


def assign_workflows(requests: list[dict], identities: dict, owners, activity: ActivityIndex) -> dict:
    """Map case_id -> workflow activity rows believed to belong to that request.

    identities: case_id -> IdentitySet for every deletion request (all request files together,
                since they share one activity stream).
    owners:     resource_id -> identifiers seen on that resource anywhere in the evidence.
    """
    batches = defaultdict(list)
    for req in requests:
        if req["case_id"] in identities:
            batches[req["reported_at"]].append(req)
    assigned = defaultdict(list)
    for reported_at, batch in sorted(batches.items()):
        _assign_batch(parse_time(reported_at), batch, identities, owners, activity, assigned)
    return dict(assigned)


def _assign_batch(reported, batch, identities, owners, activity, assigned):
    batch = sorted(batch, key=lambda r: case_order(r["case_id"]))
    rows = activity.worker_rows(reported - WINDOW_BEFORE, reported + POLICY_AFTER)
    accounts = [r for r in rows if r["resource_id"].startswith(ACCOUNT_PREFIX)
                and r["event_type"] == "DELETE_RECORD" and parse_time(r["event_time"]) <= reported + WINDOW_AFTER]
    batch_ids = {i for req in batch for i in identities[req["case_id"]].identifiers}

    def owned_by(row, ids):
        return bool(owners.get(row["resource_id"], frozenset()) & ids)

    def foreign(row):                                     # evidence ties it to nobody in this batch
        own = owners.get(row["resource_id"], frozenset())
        return bool(own) and not (own & batch_ids)

    account_of = {}
    free = [r for r in accounts if not foreign(r)]
    for req in batch:                                     # 1. identifiers in the evidence
        ids = identities[req["case_id"]].identifiers
        hit = next((r for r in free if owned_by(r, ids)), None)
        if hit:
            account_of[req["case_id"]] = hit
            free.remove(hit)
    free = [r for r in free if not owners.get(r["resource_id"])]
    for strict in (True, False):                          # 2. result matches status, 3. time order
        for req in batch:
            if req["case_id"] in account_of:
                continue
            want = STATUS_RESULT.get(req["reported_status"])
            hit = next((r for r in free if not strict or r["reported_result"] == want), None)
            if hit:
                account_of[req["case_id"]] = hit
                free.remove(hit)
    for case_id, row in account_of.items():
        assigned[case_id].append(row)

    # identifier-less policy rows (e.g. anonymized analytics): pair with the requests that have no
    # evidence-linked resource of that kind, in case order, when the counts agree
    orphans = defaultdict(list)
    for r in rows:
        prefix = _prefix(r["resource_id"])
        if prefix != ACCOUNT_PREFIX and not owners.get(r["resource_id"]):
            orphans[(prefix, r["event_type"], r["reported_result"])].append(r)
    for (prefix, _, _), group in sorted(orphans.items()):
        cases = [req["case_id"] for req in batch if req["case_id"] in account_of
                 and not _has_linked(prefix, identities[req["case_id"]].identifiers, rows, owners)]
        if len(group) == len(cases):
            for case_id, row in zip(cases, group):
                assigned[case_id].append(row)


def _prefix(resource_id: str) -> str:
    return re.sub(r"\d+$", "", resource_id)


def _has_linked(prefix, ids, rows, owners) -> bool:
    return any(_prefix(r["resource_id"]) == prefix and owners.get(r["resource_id"], frozenset()) & ids for r in rows)
