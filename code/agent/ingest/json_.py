"""JSON evidence (snapshot bundles, service exports, result ledgers) -> observations."""
import json

from .common import build_coverage, build_observation

# lookup-style collections report individual queries, not a full enumeration
LOOKUP_COLLECTIONS = {"operational_record_history"}


def parse(evidence: dict, path) -> tuple[list, list]:
    """Return (observations, coverage). Only snapshot-bundle collections yield coverage."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    file_time = doc.get("exported_at") or doc.get("captured_at") or evidence["captured_at"]
    out, coverage = [], []
    for collection, system, observed_at, records in _groups(doc, file_time):
        found = []
        for record in records:
            obs = build_observation(evidence=evidence, source_kind="json", collection=collection,
                                    record=record, observed_at=observed_at, system_id=system)
            if obs:
                out.append(obs)
                found.append(obs.resource_id)
        if "snapshots" in doc and collection not in LOOKUP_COLLECTIONS:
            cov = build_coverage(evidence=evidence, source_kind="json", collection=collection,
                                 observed_at=observed_at, system_id=system, resource_ids=found)
            if cov:
                coverage.append(cov)
    return out, coverage


def _groups(doc: dict, file_time: str):
    """Yield (collection, system, observed_at, records) for each known document shape."""
    if "snapshots" in doc:
        for snap in doc["snapshots"]:
            yield snap["collection"], snap.get("data_store", ""), snap.get("captured_at", file_time), snap["records"]
    elif "service_exports" in doc:
        for system, sections in doc["service_exports"].items():
            for collection, records in sections.items():
                yield collection, system, file_time, records
    elif "records" in doc:
        yield doc.get("collection", ""), "", file_time, doc["records"]
