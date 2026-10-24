"""Evidence Linker Agent: the subject's resources and the observations visible at audit_at."""
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .identity import IdentitySet
from .ingest.common import LOOKUP_KEYS
from .store import Observation, ObservationStore, extract_identifiers

RESOURCE_RE = re.compile(r"^(?:account|search|support|export|analytics|data_flow|backup|audit_record|tombstone)_\d+$")
# fields that point at another resource of the same subject (e.g. a search document's source account)
REFERENCE_KEYS = ("source_resource_id",)
ACCOUNT_PREFIX = "account_"


@dataclass
class LinkedCase:
    identity: IdentitySet
    audit_at: str
    observations: dict = field(default_factory=lambda: defaultdict(list))   # resource_id -> [Observation]
    claims: dict = field(default_factory=lambda: defaultdict(list))         # resource_id -> [activity row]
    seeds: dict = field(default_factory=dict)                               # resource_id -> how it was linked

    @property
    def resource_ids(self) -> list[str]:
        return sorted(set(self.observations) | set(self.claims))


def visible(obs: Observation, audit_at: str) -> bool:
    """Only evidence captured, and describing a moment, at or before audit_at may be used."""
    return obs.captured_at <= audit_at and obs.observed_at <= audit_at


def content_identifiers(obs: Observation) -> frozenset:
    """Identifiers stored in the record itself, excluding the key a lookup was issued with."""
    return extract_identifiers({k: v for k, v in obs.fields.items() if k not in LOOKUP_KEYS})


def link(identity: IdentitySet, audit_at: str, store: ObservationStore, activity, workflow_rows,
         claimed_by_others=frozenset()) -> LinkedCase:
    """Discover the subject's resources, then keep only observations visible at audit_at.

    Discovery may use any evidence: a resource's identity does not change with time, and its
    state is still decided only from what was visible at audit_at. A resource matched only by a
    lookup key (not by its content) is weak: it is dropped when another request's workflow claims
    it, and a weakly linked account is dropped when the subject's account is already known.
    """
    case = LinkedCase(identity, audit_at)
    ids = identity.identifiers
    weak = set()
    for ident in sorted(ids):                                       # exact identifier match
        for obs in store.by_identifier(ident):
            rid = obs.resource_id
            if content_identifiers(obs) & ids:
                case.seeds[rid] = f"identifier:{obs.evidence_id}"
                weak.discard(rid)
            elif rid not in claimed_by_others and rid not in case.seeds:
                case.seeds[rid] = f"lookup-key:{obs.evidence_id}"
                weak.add(rid)
    for row, named in activity.links:                               # LINK_RESOURCE_IDENTITY
        if row["event_time"] <= audit_at and named & ids:
            case.seeds.setdefault(row["resource_id"], f"link:{row['activity_id']}")
            weak.discard(row["resource_id"])
    for row in workflow_rows:                                       # assigned workflow rows (claims)
        if row["event_time"] <= audit_at:
            case.seeds.setdefault(row["resource_id"], f"workflow:{row['activity_id']}")
            weak.discard(row["resource_id"])
    for rid in list(case.seeds):                                    # references from linked records
        for obs in store.by_resource(rid):
            for key in REFERENCE_KEYS:
                ref = obs.fields.get(key)
                if isinstance(ref, str) and RESOURCE_RE.match(ref):
                    case.seeds.setdefault(ref, f"reference:{obs.evidence_id}")

    if any(r.startswith(ACCOUNT_PREFIX) and r not in weak for r in case.seeds):
        for rid in [r for r in weak if r.startswith(ACCOUNT_PREFIX)]:
            del case.seeds[rid]

    for rid in case.seeds:                                          # resource closure
        case.observations[rid] = [o for o in store.by_resource(rid) if visible(o, audit_at)]
        case.claims[rid] = [r for r in activity.by_resource.get(rid, []) if r["event_time"] <= audit_at]
    return case
