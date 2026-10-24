"""Multimodal extraction (one-time, cached): PDFs and images -> rows.

Stage 1  text extraction (extract_text.py)   -> code/cache/text/<file_id>.json
Stage 2  LLM formats the text into rows      -> code/cache/extracted/<file_id>.json

Both stages are cached with fingerprints, so a re-run makes no OCR or API calls unless the file,
the extractor, the prompt or the model changed. Rows are validated after the LLM step and bad
rows are dropped (recorded under `dropped`).
"""
import re
from collections import Counter
from pathlib import Path

from .. import cache, config, io, llm
from ..store import EMAIL_RE, Observation, extract_identifiers
from .extract_text import ExtractorUnavailable, extract_text, extractor_version

PROMPT_VERSION = "2"
SOURCE_SUFFIXES = {".pdf", ".png"}
RESOURCE_PREFIXES = ("account|search|support|export|analytics|data_flow|backup|audit_record|tombstone|"
                     "marketing|email_delivery|cache|legal_hold|object")
RESOURCE_RE = re.compile(rf"^(?:{RESOURCE_PREFIXES})_\d+$")
VALIDATION_VERSION = "2"      # bump when validate_rows changes: cached replies are re-validated, not re-asked
ID_IN_TEXT_RE = re.compile(rf"\b(?:{RESOURCE_PREFIXES})_\d+\b")
ROW_FIELDS = ("system", "resource_id", "record_type", "status", "identifiers", "timestamp", "notes")

SYSTEM_PROMPT = (
    "You convert text extracted (by OCR or PDF text extraction) from business documents and admin "
    "console screenshots into structured rows. Copy identifiers exactly as written; never infer, "
    "guess or complete values that are not in the text. Reply with one JSON object and nothing else."
)
USER_PROMPT = """Extract every record the text describes as rows of this JSON shape:

{{"rows": [{{"system": string|null, "resource_id": string|null, "record_type": string|null,
            "status": string|null, "identifiers": [string], "timestamp": string|null, "notes": string|null}}]}}

- resource_id: an id such as account_123, search_45, support_7, export_9, analytics_12, data_flow_3,
  backup_8, audit_record_5, tombstone_2, marketing_1 or object_19, only if it appears verbatim; otherwise null. An id may sit
  inside a longer reference: in "reference CS-4827 / support_001" the resource_id is support_001.
- identifiers: every email address, user id (user_N), phone number or hash on that record, verbatim.
- system: the service the record belongs to if the text names it (for example account_service).
- record_type: the kind of record (for example USER_PROFILE, SUPPORT_MESSAGE, SECURITY_AUDIT_LOG).
- status: the state shown for the record (for example ACTIVE, DISABLED, deleted, retained), or null.
- timestamp: the record's own date/time as written, or null. notes: one short factual remark, or null.
- Skip layout text. Emit one row per record; do not merge different records.

Document: {name}
--- TEXT START ---
{text}
--- TEXT END ---"""


def format_with_llm(name: str, text: str, hint: str = "") -> dict:
    prompt = USER_PROMPT.format(name=name, text=text) + (f"\n\n{hint}" if hint else "")
    return llm.complete_json(SYSTEM_PROMPT, prompt, agent="multimodal_format")


def uncovered_ids(text: str, rows: list[dict]) -> list[str]:
    """Resource ids written in the text that no row carries (the model overlooked them)."""
    found = {m.group() for m in ID_IN_TEXT_RE.finditer(text)}
    return sorted(found - {r["resource_id"] for r in rows if r["resource_id"]})


def validate_rows(rows) -> tuple[list[dict], list[dict]]:
    """Return (kept, dropped). A row needs a valid resource_id or at least one identifier."""
    kept, dropped = [], []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            dropped.append({"row": raw, "reason": "not an object"})
            continue
        row = {k: raw.get(k) for k in ROW_FIELDS}
        identifiers = row["identifiers"] if isinstance(row["identifiers"], list) else []
        row["identifiers"] = [str(i).strip() for i in identifiers if str(i).strip()]
        rid = row["resource_id"]
        if rid is not None and not (isinstance(rid, str) and RESOURCE_RE.match(rid)):
            dropped.append({"row": raw, "reason": f"bad resource_id {rid!r}"})
        elif any("@" in i and not EMAIL_RE.fullmatch(i) for i in row["identifiers"]):
            dropped.append({"row": raw, "reason": "bad email"})
        elif rid is None and not row["identifiers"]:
            dropped.append({"row": raw, "reason": "no resource_id or identifier"})
        else:
            kept.append(row)
    return kept, dropped


def sources() -> list[dict]:
    return [e for e in io.load_manifest() if (config.DATASET / e["file_path"]).suffix.lower() in SOURCE_SUFFIXES]


def run(use_llm: bool = True, formatter=format_with_llm, force: bool = False, progress=None) -> dict[str, str]:
    """Process every PDF/PNG in the manifest; returns file_id -> outcome.

    `progress(file_id, name, outcome_or_None)` is called before and after each file.
    """
    outcome = {}
    for evidence in sources():
        file_id = evidence["file_id"]
        if progress:
            progress(file_id, evidence["file_path"], None)
        outcome[file_id] = process(evidence, use_llm, formatter, force)
        if progress:
            progress(file_id, evidence["file_path"], outcome[file_id])
    return outcome


def process(evidence: dict, use_llm: bool = True, formatter=format_with_llm, force: bool = False) -> str:
    file_id = evidence["file_id"]
    path = config.DATASET / evidence["file_path"]
    text_key = cache.digest(path.read_bytes(), extractor_version(path))
    text_cache = f"text/{file_id}.json"
    cached_text = None if force else cache.load(text_cache, text_key)
    if cached_text is None:
        try:
            text = extract_text(path)
        except ExtractorUnavailable as exc:
            return f"no text extractor: {exc}"
        except Exception as exc:
            return f"text extraction failed: {exc}"
        cache.save(text_cache, {"file_path": evidence["file_path"], "text": text}, text_key)
    else:
        text = cached_text["text"]
    if not text.strip():
        return "no text found"

    model = llm.model_name() or "unconfigured"
    rows_cache = f"extracted/{file_id}.json"
    rows_key = cache.digest(text, PROMPT_VERSION, model)
    cached = None if force else cache.load(rows_cache, rows_key)
    if cached is not None:
        if cached.get("validation_version") == VALIDATION_VERSION:
            return "cached"
        raw = cached.get("raw_rows") or cached["rows"] + [d["row"] for d in cached["dropped"]]
        kept, dropped = validate_rows(raw)                # rules changed: no new LLM call needed
        _save_rows(rows_cache, rows_key, evidence, model, raw, kept, dropped, uncovered_ids(text, kept))
        return f"revalidated {len(kept)} rows ({len(dropped)} dropped)"
    if not use_llm:
        return "text cached; LLM formatting skipped (--no-llm)"
    try:
        raw = _ask(formatter, path.name, text).get("rows")
        kept, dropped = validate_rows(raw)
        missing = uncovered_ids(text, kept)
        if missing:                                       # one targeted retry for overlooked ids
            hint = (f"Your previous answer left out these resource ids that appear in the text: "
                    f"{', '.join(missing)}. Give each one a row (or set it as resource_id on the "
                    f"row it belongs to).")
            raw = _ask(formatter, path.name, text, hint).get("rows")
            kept, dropped = validate_rows(raw)
            missing = uncovered_ids(text, kept)
    except llm.LLMUnavailable as exc:
        return f"text cached; {exc}"
    except Exception as exc:
        return f"text cached; LLM formatting failed: {exc}"
    _save_rows(rows_cache, rows_key, evidence, model, raw, kept, dropped, missing)
    return f"extracted {len(kept)} rows ({len(dropped)} dropped)"


def _save_rows(name, key, evidence, model, raw, kept, dropped, missing) -> None:
    cache.save(name, {"file_id": evidence["file_id"], "file_path": evidence["file_path"],
                      "captured_at": evidence["captured_at"], "model": model,
                      "prompt_version": PROMPT_VERSION, "validation_version": VALIDATION_VERSION,
                      "raw_rows": raw if isinstance(raw, list) else [], "rows": kept, "dropped": dropped,
                      "uncovered_resource_ids": missing}, key)


def _ask(formatter, name: str, text: str, hint: str = "") -> dict:
    """Call the formatter; one retry when the reply was not valid JSON."""
    try:
        return formatter(name, text, hint)
    except ValueError:                                    # includes json.JSONDecodeError
        retry = (hint + "\n\n" if hint else "") + (
            "Your previous reply was not valid JSON. Reply with only one complete, valid JSON object "
            "and keep notes short.")
        return formatter(name, text, retry)


def summary(outcome: dict[str, str]) -> str:
    kinds = Counter(re.split(r"[:;(]", v)[0].strip() for v in outcome.values())
    return ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))


def observations(evidence: dict) -> list[Observation] | None:
    """Observations from the cached rows of one PDF/PNG; None when it has not been extracted.

    Only rows that name a resource_id become observations. The model's `record_type` is kept as
    `llm_record_type` and never used as the category (it is unreliable): the category comes from
    the id prefix, and a support record found in a PDF/attachment-like row is an attachment.
    """
    payload = cache.load(f"extracted/{evidence['file_id']}.json")
    if payload is None:
        return None
    suffix = Path(evidence["file_path"]).suffix.lower()
    out = []
    for row in payload["rows"]:
        rid = row.get("resource_id")
        if not rid:
            continue
        fields = {k: v for k, v in row.items() if k != "record_type"}
        fields["llm_record_type"] = row.get("record_type")
        prefix = next((p for p in config.PREFIX_SYSTEM if rid.startswith(p)), None)
        category = config.PREFIX_CATEGORY.get(prefix)
        if prefix == "support_" and (suffix == ".pdf" or "attachment" in str(row.get("notes") or "").lower()):
            category = "SUPPORT_ATTACHMENT"
        out.append(Observation(
            evidence_id=evidence["file_id"], source_kind="pdf" if suffix == ".pdf" else "image",
            observed_at=evidence["captured_at"], captured_at=evidence["captured_at"],
            system_id=config.PREFIX_SYSTEM.get(prefix) or row.get("system") or "",
            resource_id=rid, category=category, state=_row_state(row), identifiers=extract_identifiers(fields),
            fields=fields))
    return out


def _row_state(row: dict) -> str:
    """A resource shown on a console exists (PRESENT) unless the row states a known state."""
    return config.RESULT_STATE.get(str(row.get("status") or "").strip().upper(), "PRESENT")
