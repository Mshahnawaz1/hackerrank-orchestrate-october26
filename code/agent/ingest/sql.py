"""SQLite snapshot exports -> observations. Each table is a separate copy (replica drift)."""
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import replace

from .common import build_coverage, build_observation

CAPTURED_RE = re.compile(r"^-- Captured at:\s*(\S+)", re.M)
SKIP_TABLES = {"snapshot_scope"}


def parse(evidence: dict, path) -> tuple[list, list]:
    """Return (observations, coverage). Every table is one copy; empty tables still yield coverage."""
    text = path.read_text(encoding="utf-8")
    header = CAPTURED_RE.search(text)
    snapshot_time = header.group(1) if header else evidence["captured_at"]

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(text)
    scope = {}
    if _has_table(db, "snapshot_scope"):
        scope = {r["origin_system"]: r["captured_at"] for r in db.execute("SELECT * FROM snapshot_scope")}

    out, coverage = [], []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if table in SKIP_TABLES:
            continue
        groups = defaultdict(set)                         # (system, collection) -> resource_ids
        for row in db.execute(f'SELECT * FROM "{table}"'):
            record = dict(row)
            collection = table
            system = record.get("origin_system", "")
            if "record_json" in record:
                collection = record.pop("collection_name")
                record.update(json.loads(record.pop("record_json")))
            # a row proves presence at snapshot time; its own updated_at stays in `fields`
            obs = build_observation(evidence=evidence, source_kind="sql", collection=collection,
                                    record=record, observed_at=snapshot_time, system_id=system, copy=table)
            if obs:
                obs = replace(obs, observed_at=scope.get(obs.system_id, snapshot_time))
                out.append(obs)
                groups[(system or obs.system_id, collection)].add(obs.resource_id)
        if not groups and _columns(db, table) and "record_json" not in _columns(db, table):
            groups[("", table)] = set()                   # empty table: the copy holds nothing
        for (system, collection), resource_ids in sorted(groups.items()):
            cov = _coverage(evidence, table, collection, system, resource_ids, scope, snapshot_time)
            if cov:
                coverage.append(cov)
    db.close()
    return out, coverage


def _coverage(evidence, table, collection, system, resource_ids, scope, snapshot_time):
    cov = build_coverage(evidence=evidence, source_kind="sql", collection=collection, copy=table,
                         observed_at=snapshot_time, system_id=system, resource_ids=resource_ids)
    if cov is None:
        return None
    if scope:                                             # inventory dumps list which systems they captured
        if cov.system_id not in scope:
            return None
        cov = replace(cov, observed_at=scope[cov.system_id])
    return cov


def _columns(db, table: str) -> list[str]:
    return [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]


def _has_table(db, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None
