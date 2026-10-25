# Ghost Data Still Exists: Deletion-Audit Agent

HackerRank Orchestrate, October 2026. For each request in `dataset/deletion_requests.csv`, the agent decides
whether deletion was actually requested, reconstructs what still exists at `audit_at`, applies
`deletion_rules.csv`, and writes `output.csv` with `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE` plus an
ordered list of findings, remediation and verification steps.

The full challenge contract is in [`problem_statement.md`](./problem_statement.md); the design is in
[`PRD.md`](./PRD.md).

## How it works

The core is deterministic code. An LLM is used only once, offline, to turn text extracted from PDFs and
screenshots into rows; its output is cached and committed, so a normal run needs no API key.

```
intent -> identity -> linker -> state -> policy -> planner -> serializer/validator
```

| Stage | Module (`code/agent/`) | What it does |
|---|---|---|
| Intent | `intent.py` | Multilingual regex rules decide if the text authorizes deletion (HIGH/MEDIUM/LOW confidence). Non-deletion requests become `NOT_APPLICABLE`. |
| Ingestion | `ingest/` | Parses SQL snapshots, JSON, logs and the text handover into `Observation`s, plus snapshot coverage so a record missing from a full snapshot proves absence. Cached in `code/cache/observations.json`. |
| Multimodal | `ingest/extract_text.py`, `ingest/multimodal.py` | PDF text extraction and Tesseract OCR for screenshots, then an LLM formats the text into rows. Cached in `code/cache/text/` and `code/cache/extracted/`. |
| Identity | `identity.py` | Request email (current or historical) to `user_id`, with all emails, phones and hashes. Exact match only, so decoys do not link. |
| Linker | `linker.py`, `activity.py` | Finds the subject's resources by identifier, `LINK_RESOURCE_IDENTITY` rows and the deletion-workflow rows assigned to the request. |
| State | `state.py` | State of each resource at `audit_at`: per-copy (primary and each replica), latest evidence wins, activity rows are claims only. |
| Policy | `policy.py` | Applies the deletion rules (delete, redact, anonymize, retain, disable flows, block restores). |
| Planner | `planner.py` | Findings, remediation (flows and restores first), verification. |
| Serializer | `serialize.py` | Canonical ordering, step numbering, and validation of every row before writing. |

Rules the code follows: only evidence captured at or before `audit_at` can be used for state or cited;
workflow statuses and activity results are never treated as proof.

## Setup

Python 3.10+ and the standard library are enough to produce `output.csv`.

```bash
git clone <repo-url>
cd hackerrank-orchestrate-october26
python3 code/main.py          # writes ./output.csv (518 rows, about 2 seconds)
```

Optional, only to regenerate the PDF/image extraction cache:

- `sudo apt install tesseract-ocr` (or `brew install tesseract`); `Pillow` improves OCR quality.
- Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` and `MODEL`.
  `.env` is gitignored; secrets are never logged.
- `pytest` is only needed to run the tests with pytest (`unittest` also works).

## Run

```bash
python3 code/main.py                       # full run -> output.csv
python3 code/main.py --sample              # run the 32 sample requests
python3 code/main.py --case case_11 --trace  # explain one case (linked resources, states, decisions)
python3 code/main.py --ingest-report       # observation counts per evidence file
python3 code/main.py --rebuild-cache       # force re-parse of the evidence
python3 code/main.py --extract             # PDFs/images -> text -> LLM rows (needs OCR and an API key)
python3 code/main.py --extract --no-llm    # text extraction only
```

## Evaluate and test

```bash
python3 code/evaluation/main.py            # score the samples against dataset/sample_output.csv
python3 code/evaluation/main.py --diff     # plus a per-case list of differences
python3 -m pytest code/tests -q            # unit tests
```

The evaluation reports status accuracy, step precision/recall/F1, per-field accuracy and exact-sequence
accuracy.

Current results on the 32 sample cases: status accuracy 96.9% (31/32), step F1 0.976, evidence-ID
accuracy 100% on matched steps, exact-sequence match 78.1%. The seven differing cases are listed by
`--diff`; they involve records that appear in no participant-visible evidence or that cannot be tied to a
single request.

## Caches

| Path | Content | Rebuilt when |
|---|---|---|
| `code/cache/observations.json` | Parsed evidence (derived, gitignored) | evidence, manifest, extracted rows or ingestion code change |
| `code/cache/intent.json` | Intent result per unique request text | intent rules change |
| `code/cache/text/<file_id>.json` | Raw text from each PDF/image | the file or extractor version changes |
| `code/cache/extracted/<file_id>.json` | LLM-formatted rows (kept, dropped, raw reply) | text, prompt version or model changes |
| `code/cache/usage.jsonl` | Token usage of each LLM call | appended per call |

Validation rule changes re-check the saved model reply and do not call the model again.

## Layout

```
code/main.py            CLI entry point
code/agent/             pipeline stages (see table above)
code/evaluation/main.py scoring harness
code/tests/             unit tests
code/cache/             cached ingestion, intent and extraction results
dataset/                challenge data (not included in code.zip)
output.csv              final predictions
log.txt                 agent session log (see AGENTS.md)
```

## Known limitations

- Matching deletion-workflow rows to requests that share a `reported_at` is heuristic (evidence
  identifiers first, then result vs reported status, then case order).
- Anonymized analytics records carry no identifiers, so their owner is ambiguous when several requests
  share a batch.
- Intent classification has no LLM fallback yet; every dataset request is decided with HIGH confidence by
  the rules.
- The LLM used for extraction is a free model; spot-check `code/cache/extracted/` after regenerating it.
