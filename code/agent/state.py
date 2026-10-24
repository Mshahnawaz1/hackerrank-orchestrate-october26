"""State Reconstructor: the state of each linked resource at audit_at, with the proving evidence.

* Each replica / failover table is its own copy; every other source describes the primary copy.
* Within a copy the latest observation wins (ties: handover > SQL > JSON > log).
* A snapshot that enumerated a copy without the resource proves ABSENT for that copy: a full SQL
  table when it is newer than every direct observation of that copy, an empty JSON snapshot only
  when nothing else describes that copy. When an inference and a direct observation agree, the
  direct observation is cited.
* A replica still holding the record while the primary lost it is drift: the resource is PRESENT.
* Activity rows are claims and never set a state.
"""
from dataclasses import dataclass

from .ingest.common import category_for, system_for
from .linker import LinkedCase, visible
from .store import EMAIL_RE, ObservationStore

PRIORITY = {"txt": 5, "sql": 4, "json": 3, "log": 2, "pdf": 1, "image": 1}
PRIMARY = "primary"
# fields holding direct identifiers; the record is "exposed" when any is set
DIRECT_KEYS = {"email", "phone", "email_hash", "full_name", "name", "display_name", "requester_name",
               "requester_email", "requester_phone", "owner_email", "owner_phone", "customer_email",
               "matched_value"}
TEXT_KEYS = {"message_text", "message_excerpt"}
REFERENCE_KEYS = {"user_id", "customer_reference"}       # stable internal reference (user_id)
EXPOSED_RESULTS = {"IDENTIFIABLE"}


@dataclass(frozen=True)
class Snapshot:
    """One dated statement about one copy of a resource."""
    state: str
    observed_at: str
    evidence_id: str
    source_kind: str
    copy: str
    fields: tuple = ()
    inferred: bool = False            # derived from a snapshot's coverage, not a record

    def field(self, key):
        return dict(self.fields).get(key)


@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    category: str | None
    state: str | None                 # None when no visible evidence describes the resource
    evidence_id: str = ""
    observed_at: str = ""
    exposed: bool = False             # direct identifiers still visible
    attributable: bool = False        # a user_id reference is still present
    snapshot: Snapshot | None = None


def copy_key(copy: str) -> str:
    return copy if ("replica" in copy or "failover" in copy) else PRIMARY


def reconstruct(case: LinkedCase, store: ObservationStore) -> dict[str, ResourceState]:
    return {rid: _resource_state(rid, case, store) for rid in case.resource_ids}


def _resource_state(rid: str, case: LinkedCase, store: ObservationStore) -> ResourceState:
    observations = case.observations.get(rid, [])
    category = _category(rid, observations)
    system = observations[0].system_id if observations else _system_from_claims(rid, case)
    snapshots = [Snapshot(o.state, o.observed_at, o.evidence_id, o.source_kind, copy_key(o.copy),
                          tuple(sorted(o.fields.items(), key=lambda kv: kv[0])))
                 for o in observations]
    snapshots += _absences(rid, system, category, snapshots, case.audit_at, store)
    if not snapshots:
        return ResourceState(rid, system, category, None)

    latest = {}
    for copy in sorted({s.copy for s in snapshots}):
        in_copy = [s for s in snapshots if s.copy == copy]
        best = max(in_copy, key=_order)
        direct = [s for s in in_copy if not s.inferred]
        if best.inferred and direct and max(direct, key=_order).state == best.state:
            best = max(direct, key=_order)                # cite the record, not the inference
        latest[copy] = best
    chosen = latest.get(PRIMARY)
    for copy, snap in sorted(latest.items()):
        if copy == PRIMARY:
            continue
        drift = snap.state != "ABSENT" and (chosen is None or chosen.state == "ABSENT")
        if chosen is None or drift:
            chosen = snap
    exposed, attributable = _exposure(chosen)
    return ResourceState(rid, system, category, chosen.state, chosen.evidence_id, chosen.observed_at,
                         exposed, attributable, chosen)


def _order(snap: Snapshot) -> tuple:
    return snap.observed_at, PRIORITY.get(snap.source_kind, 0), not snap.inferred, snap.evidence_id


def _absences(rid, system, category, snapshots, audit_at, store) -> list[Snapshot]:
    out = []
    for cov in store.coverage_for(system):
        if rid in cov.resource_ids or not visible(cov, audit_at) or category_for(cov.collection) != category:
            continue
        copy = copy_key(cov.copy)
        direct = [s.observed_at for s in snapshots if s.copy == copy]
        if cov.source_kind == "sql":
            usable = not direct or cov.observed_at > max(direct)
        else:
            usable = not cov.resource_ids and not direct
        if usable:
            out.append(Snapshot("ABSENT", cov.observed_at, cov.evidence_id, cov.source_kind, copy, inferred=True))
    return out


def _exposure(snap: Snapshot) -> tuple[bool, bool]:
    f = dict(snap.fields)
    if str(f.get("result") or "").upper() in EXPOSED_RESULTS:
        return True, True
    exposed = any(f.get(k) not in (None, "", "null") for k in DIRECT_KEYS)
    exposed |= any(isinstance(f.get(k), str) and EMAIL_RE.search(f[k]) for k in TEXT_KEYS)
    attributable = exposed or any(f.get(k) not in (None, "", "null") for k in REFERENCE_KEYS)
    return exposed, attributable


def _category(rid: str, observations) -> str | None:
    """Explicit record_type wins; then specific signals; then the collection / prefix mapping."""
    stated = [o.fields.get("record_type") for o in observations if o.fields.get("record_type")]
    if stated:
        return sorted(stated)[-1] if len(set(stated)) > 1 else stated[0]
    fields = [o.fields for o in observations]
    if any(f.get("email_opt_in") is not None for f in fields):
        return "MARKETING_PROFILE"
    if any(f.get("service") == "support_replica" or f.get("event") == "contact_query_completed" for f in fields):
        return "SECONDARY_IDENTIFIER"
    if any(f.get("event") == "attachment_pii_scan" or f.get("file_name") for f in fields):
        return "SUPPORT_ATTACHMENT"
    cats = [o.category for o in observations if o.category]
    return max(set(cats), key=cats.count) if cats else category_for("", rid)


def _system_from_claims(rid: str, case: LinkedCase) -> str:
    rows = case.claims.get(rid, [])
    return system_for(rid, rows[0]["target_system"] if rows else "")
