"""SQLite snapshot exports -> observations. Each table is a separate copy (replica drift)."""
import json
import re
import sqlite3

from .common import build_observation

CAPTURED_RE = re.compile(r"^-- Captured at:\s*(\S+)", re.M)
SKIP_TABLES = {"snapshot_scope"}


def parse(evidence: dict, path) -> list:
    text = path.read_text(encoding="utf-8")
    header = CAPTURED_RE.search(text)
    snapshot_time = header.group(1) if header else evidence["captured_at"]

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(text)
    scope = {}
    if _has_table(db, "snapshot_scope"):
        scope = {r["origin_system"]: r["captured_at"] for r in db.execute("SELECT * FROM snapshot_scope")}

    out = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if table in SKIP_TABLES:
            continue
        for row in db.execute(f'SELECT * FROM "{table}"'):
            record = dict(row)
            collection = table
            system = record.get("origin_system", "")
            if "record_json" in record:
                collection = record.pop("collection_name")
                record.update(json.loads(record.pop("record_json")))
            observed = record.get("updated_at") or scope.get(system) or snapshot_time
            obs = build_observation(evidence=evidence, source_kind="sql", collection=collection,
                                    record=record, observed_at=observed, system_id=system, copy=table)
            if obs:
                out.append(obs)
    db.close()
    return out


def _has_table(db, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None
