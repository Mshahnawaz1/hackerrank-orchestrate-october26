"""On-disk JSON cache for the one-time stages (ingestion, intent, later multimodal).

Each cache file stores a `fingerprint` of everything that produced it; a mismatch means stale.
Writes are deterministic (sorted keys, fixed separators) so committed caches diff cleanly.
"""
import hashlib
import json
from pathlib import Path

from . import config


def fingerprint(paths, extra: str = "") -> str:
    """sha256 over the given files' bytes (in the given order) plus an extra tag."""
    h = hashlib.sha256(extra.encode("utf-8"))
    for path in paths:
        h.update(str(Path(path).name).encode("utf-8"))
        h.update(Path(path).read_bytes())
    return h.hexdigest()


def load(name: str, expected_fingerprint: str | None = None):
    """Return the cached payload, or None when missing, unreadable or stale."""
    path = config.CACHE / name
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if expected_fingerprint is not None and doc.get("fingerprint") != expected_fingerprint:
        return None
    return doc.get("payload")


def save(name: str, payload, fingerprint_value: str = "") -> Path:
    path = config.CACHE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"fingerprint": fingerprint_value, "payload": payload}
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return path
