"""Observation model, identifier normalization and the indexed ObservationStore."""
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_RE = re.compile(r"\buser_\d+\b", re.I)
HASH_RE = re.compile(r"[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class Observation:
    evidence_id: str          # manifest file_id
    source_kind: str          # sql | json | log | txt | pdf | image
    observed_at: str          # record-level time if present, else snapshot / file time
    captured_at: str          # manifest capture time of the evidence file
    system_id: str
    resource_id: str
    category: str | None
    state: str                # PRESENT|ABSENT|ACTIVE|DISABLED|BLOCKED|REDACTED|ANONYMIZED
    identifiers: frozenset
    fields: dict = field(compare=False, hash=False, default_factory=dict)
    copy: str = ""            # table / topology the record came from (replica drift)
    is_claim: bool = False


@dataclass(frozen=True)
class Coverage:
    """A snapshot that enumerated one copy of a system at a point in time.

    Resources absent from `resource_ids` were not in that copy when it was captured. Whether
    that proves deletion (full scan vs partial extract) is decided by the state stage.
    """
    evidence_id: str
    source_kind: str
    observed_at: str
    captured_at: str
    system_id: str
    collection: str
    copy: str
    resource_ids: frozenset


def _to_dict(obj) -> dict:
    d = asdict(obj)
    for k, v in d.items():
        if isinstance(v, (set, frozenset)):
            d[k] = sorted(v)
    return d


def norm_email(value: str) -> str:
    return value.strip().lower()


def norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value)


def extract_identifiers(fields: dict) -> frozenset:
    """Collect normalized emails, user ids, hashes and phones from every scalar field."""
    found = set()
    for key, value in _walk(fields):
        if not isinstance(value, str):
            continue
        found.update(norm_email(m) for m in EMAIL_RE.findall(value))
        found.update(m.lower() for m in USER_RE.findall(value))
        if HASH_RE.fullmatch(value.strip()):
            found.add(value.strip().lower())
        if "phone" in key and norm_phone(value):
            found.add(norm_phone(value))
    return frozenset(found)


def _walk(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj


class ObservationStore:
    def __init__(self):
        self.observations: list[Observation] = []
        self.coverage: list[Coverage] = []
        self._by_identifier = defaultdict(list)
        self._by_resource = defaultdict(list)
        self._coverage_by_system = defaultdict(list)

    def add(self, obs: Observation) -> None:
        self.observations.append(obs)
        self._by_resource[obs.resource_id].append(obs)
        for ident in obs.identifiers:
            self._by_identifier[ident].append(obs)

    def add_coverage(self, cov: Coverage) -> None:
        self.coverage.append(cov)
        self._coverage_by_system[cov.system_id].append(cov)

    def coverage_for(self, system_id: str) -> list[Coverage]:
        return self._coverage_by_system.get(system_id, [])

    def by_identifier(self, ident: str) -> list[Observation]:
        return self._by_identifier.get(ident, [])

    def by_resource(self, resource_id: str) -> list[Observation]:
        return self._by_resource.get(resource_id, [])

    def __len__(self) -> int:
        return len(self.observations)

    def to_dict(self) -> dict:
        return {"observations": [_to_dict(o) for o in self.observations],
                "coverage": [_to_dict(c) for c in self.coverage]}

    @classmethod
    def from_dict(cls, data: dict) -> "ObservationStore":
        store = cls()
        for o in data["observations"]:
            store.add(Observation(**{**o, "identifiers": frozenset(o["identifiers"])}))
        for c in data["coverage"]:
            store.add_coverage(Coverage(**{**c, "resource_ids": frozenset(c["resource_ids"])}))
        return store
