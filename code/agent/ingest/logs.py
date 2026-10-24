"""Structured service logs (six line formats) -> observations.

Every line is normalized to a dict; `*_started` lines carry the lookup key and are joined to
their `*_completed` event through trace_id.
"""
import json
import re

from .common import LOOKUP_KEYS, build_observation, clean

KV_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
BRACKET_RE = re.compile(r"^\[(\w+)\] \[(\w+)\] \[([\w-]+)\] (\w+): (.*)$")        # [LEVEL] [svc] [trace] event: kv
SYSLOG_RE = re.compile(r"^<\d+>1 \S+ (\w+) ([\w-]+) - - (.*)$")                  # <pri>1 node svc trace - - kv
EVENT_ENDS = ("_completed",)
EVENTS = {"record_lookup", "analytics_profile_read", "message_pii_scan", "attachment_pii_scan",
          "analytics_identity_scan", "connector_heartbeat", "restore_candidate_evaluated"}


def parse(evidence: dict, path) -> list:
    events = [e for e in (_parse_line(l) for l in path.read_text(encoding="utf-8").splitlines()) if e]
    keys = {}
    for e in events:
        for name in LOOKUP_KEYS:
            if clean(e.get(name)) and e.get("trace_id"):
                keys.setdefault(e["trace_id"], e[name])
    out = []
    for e in events:
        event = e.get("event", "")
        if not e.get("resource_id") or not (event.endswith(EVENT_ENDS) or event in EVENTS):
            continue
        record = {k: v for k, v in e.items() if k not in ("ts", "level")}
        if not any(clean(e.get(n)) for n in LOOKUP_KEYS) and e.get("trace_id") in keys:
            record["lookup_key"] = keys[e["trace_id"]]
        obs = build_observation(evidence=evidence, source_kind="log", collection=e.get("service", ""),
                                record=record, observed_at=e["ts"], system_id=e.get("service", ""))
        if obs:
            out.append(obs)
    return out


def _kv(text: str) -> dict:
    return {k: _unquote(v) for k, v in KV_RE.findall(text)}


def _unquote(value: str) -> str:
    return value[1:-1].replace('\\"', '"') if value.startswith('"') else value


def _parse_line(line: str) -> dict | None:
    ts, _, rest = line.partition(" ")
    if not rest:
        return None
    rest = rest.strip()
    if rest.startswith("{"):
        try:
            e = json.loads(rest)
        except json.JSONDecodeError:
            return None
        e = {k: str(v) if v is not None else v for k, v in e.items()}
    elif (m := BRACKET_RE.match(rest)):
        e = {"service": m[2], "trace_id": m[3], "event": m[4], **_kv(m[5])}
    elif rest.startswith("| "):
        parts = [p.strip() for p in line.split(" | ", 5)]
        if len(parts) < 6:
            return None
        e = {"service": parts[2], "trace_id": parts[3], "event": parts[4], **_kv(parts[5])}
    elif (m := SYSLOG_RE.match(rest)):
        e = {"service": m[1], "trace_id": m[2], **_kv(m[3])}
    else:
        e = _kv(rest)
        if "message" in e:                                    # cloud-runtime wrapper
            e = {"service": e.get("function"), "trace_id": e.get("requestId"), **_kv(e["message"])}
    e["ts"] = ts
    return e
