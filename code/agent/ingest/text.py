"""Pipe-delimited handover records: `time | system | resource | CATEGORY | STATE | identifier`."""
import re

from .common import build_observation

LINE_RE = re.compile(r"^-\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.+?)\s*$")


def parse(evidence: dict, path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        recorded_at, system, resource_id, category, result, subject = m.groups()
        record = {"resource_id": resource_id, "record_type": category, "result": result,
                  "subject_reference": subject, "recorded_at": recorded_at}
        obs = build_observation(evidence=evidence, source_kind="txt", collection=category,
                                record=record, observed_at=recorded_at, system_id=system)
        if obs:
            out.append(obs)
    return out
