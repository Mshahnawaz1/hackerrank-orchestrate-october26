"""Evidence ingestion (one-time, cached): parse every manifest file into the ObservationStore.

The result is cached in code/cache/observations.json, keyed by a fingerprint of the manifest,
the parsed evidence files and the ingestion code, so any change to either triggers a rebuild.
"""
import logging
from pathlib import Path

from .. import cache, config, io
from ..store import ObservationStore
from . import json_, logs, multimodal, sql, text

log = logging.getLogger(__name__)

CACHE_NAME = "observations.json"
PARSERS = {".sql": sql.parse, ".json": json_.parse, ".log": logs.parse, ".txt": text.parse}
MULTIMODAL = {".pdf", ".png"}    # rows come from the extraction cache (see multimodal.py)
_CODE = sorted(Path(__file__).parent.glob("*.py")) + [Path(__file__).parents[1] / f
                                                      for f in ("store.py", "config.py")]


def ingest_all(use_cache: bool = True) -> tuple[ObservationStore, dict]:
    """Return the populated store and a per-file observation count (None = not extracted yet)."""
    manifest = io.load_manifest()
    key = _fingerprint(manifest)
    if use_cache:
        cached = cache.load(CACHE_NAME, key)
        if cached is not None:
            return ObservationStore.from_dict(cached["store"]), cached["counts"]
    store, counts = _parse_all(manifest)
    cache.save(CACHE_NAME, {"store": store.to_dict(), "counts": counts}, key)
    return store, counts


def _parse_all(manifest: list[dict]) -> tuple[ObservationStore, dict]:
    store = ObservationStore()
    counts = {}
    for evidence in manifest:
        path = config.DATASET / evidence["file_path"]
        suffix = path.suffix.lower()
        if suffix in MULTIMODAL:
            observations = multimodal.observations(evidence)
            for obs in observations or []:
                store.add(obs)
            counts[evidence["file_id"]] = None if observations is None else len(observations)
            continue
        parser = PARSERS.get(suffix)
        if parser is None:
            log.warning("no parser for %s", evidence["file_path"])
            continue
        observations, coverage = parser(evidence, path)
        for obs in observations:
            store.add(obs)
        for cov in coverage:
            store.add_coverage(cov)
        counts[evidence["file_id"]] = len(observations)
    return store, counts


def _fingerprint(manifest: list[dict]) -> str:
    files = [config.DATASET / "evidence_files.csv"]
    files += [config.DATASET / e["file_path"] for e in manifest
              if Path(e["file_path"]).suffix.lower() in PARSERS]
    extracted = sorted((config.CACHE / "extracted").glob("*.json"))
    return cache.fingerprint(files + extracted + _CODE)
