"""Shared record -> Observation conversion used by every parser."""
from .. import config
from ..store import Coverage, Observation, extract_identifiers

# alternate spellings of the lookup key across log formats
LOOKUP_KEYS = ("lookup_key", "match_key", "subject_key", "scan_key", "subject_ref", "correlation_key")


def clean(value):
    """Treat textual nulls as missing."""
    return None if value in ("null", "None", "") else value


def truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def flatten(record: dict) -> dict:
    """Merge one level of nested dicts (e.g. search `document`) into the top level."""
    flat = {}
    for key, value in record.items():
        if isinstance(value, dict) and key != "metrics":
            flat.update({k: v for k, v in value.items() if k not in flat})
        else:
            flat.setdefault(key, value)
    return flat


def system_for(resource_id: str, default: str = "") -> str:
    for prefix, system in config.PREFIX_SYSTEM.items():
        if resource_id.startswith(prefix):
            return system
    return default


def category_for(collection: str, resource_id: str = "") -> str | None:
    for fragment, category in config.COLLECTION_CATEGORY.items():
        if fragment in collection:
            return category
    for prefix, category in config.PREFIX_CATEGORY.items():
        if resource_id.startswith(prefix):
            return category
    return None


def derive_state(f: dict) -> str:
    """State a single record/event asserts about its own resource."""
    if f.get("status_code") is not None:
        return "ABSENT" if str(f["status_code"]) == "404" else "PRESENT"
    result = str(f.get("result") or "").upper()
    if result in config.RESULT_STATE:
        return config.RESULT_STATE[result]
    if f.get("archive_present") is not None and not truthy(f["archive_present"]):
        return "ABSENT"
    if f.get("enabled") is not None:
        return "ACTIVE" if truthy(f["enabled"]) else "DISABLED"
    if f.get("restore_allowed") is not None:
        return "ACTIVE" if truthy(f["restore_allowed"]) else "BLOCKED"
    if f.get("eligible") is not None:
        return "ACTIVE" if truthy(f["eligible"]) and not truthy(f.get("deletion_block")) else "BLOCKED"
    if f.get("http_status") is not None:
        return "ABSENT" if str(f["http_status"]) == "404" else "PRESENT"
    if "rows" in f and str(f["rows"]) == "0":
        return "ABSENT"
    if "hits" in f and not f["hits"]:
        return "ABSENT"
    return "PRESENT"


def build_observation(*, evidence, source_kind, collection, record, observed_at,
                      system_id="", copy="", is_claim=False) -> Observation | None:
    """Turn one raw record into an Observation; None when it names no resource."""
    f = {k: clean(v) if isinstance(v, str) else v for k, v in flatten(record).items()}
    resource_id = f.get("resource_id")
    if not resource_id:
        return None
    category = f.get("record_type") or category_for(collection, resource_id)
    return Observation(
        evidence_id=evidence["file_id"],
        source_kind=source_kind,
        observed_at=f.get("recorded_at") or f.get("observed_at") or observed_at,
        captured_at=evidence["captured_at"],
        system_id=system_for(resource_id, system_id or f.get("system", "")),
        resource_id=resource_id,
        category=category,
        state=derive_state(f),
        identifiers=extract_identifiers(f),
        fields=f,
        copy=copy,
        is_claim=is_claim,
    )


def build_coverage(*, evidence, source_kind, collection, observed_at, system_id, resource_ids,
                   copy="") -> Coverage | None:
    """Record that a snapshot enumerated `collection` of `system_id`; None if the system is unknown."""
    system = system_id or config.CATEGORY_SYSTEM.get(category_for(collection) or "", "")
    if not system:
        return None
    return Coverage(evidence_id=evidence["file_id"], source_kind=source_kind, observed_at=observed_at,
                    captured_at=evidence["captured_at"], system_id=system, collection=collection,
                    copy=copy or collection, resource_ids=frozenset(resource_ids))
