"""Evidence ingestion: dispatch every manifest file to its parser and fill the ObservationStore."""
import logging

from .. import config, io
from ..store import ObservationStore
from . import json_, logs, sql, text

log = logging.getLogger(__name__)

PARSERS = {".sql": sql.parse, ".json": json_.parse, ".log": logs.parse, ".txt": text.parse}
DEFERRED = {".pdf", ".png"}      # multimodal extraction, handled by a later stage


def ingest_all() -> tuple[ObservationStore, dict]:
    """Return the populated store and a per-file observation count (None = deferred)."""
    store = ObservationStore()
    counts = {}
    for evidence in io.load_manifest():
        path = config.DATASET / evidence["file_path"]
        suffix = path.suffix.lower()
        if suffix in DEFERRED:
            counts[evidence["file_id"]] = None
            continue
        parser = PARSERS.get(suffix)
        if parser is None:
            log.warning("no parser for %s", evidence["file_path"])
            continue
        observations = parser(evidence, path)
        for obs in observations:
            store.add(obs)
        counts[evidence["file_id"]] = len(observations)
    return store, counts
