# PRD — Ghost Data Still Exists: Deletion-Audit Agent

| | |
|---|---|
| **Project** | HackerRank Orchestrate (Oct 2026) — *Ghost Data Still Exists* |
| **Owner** | Mshahnawaz1 |
| **Status** | Draft v1 — 2026-10-25 |
| **Time box** | 12 hours (hackathon) |
| **Primary deliverable** | `output.csv` (518 rows) + `code.zip` (code, README, `evaluation/`) |
| **Source of truth** | `problem_statement.md`, `AGENTS.md` §6 |

---

## 1. Problem Summary

Northstar Shop's deletion workflow reports deletions as **Complete** while personal data survives in replicas, search indexes, support tickets, exports, analytics, logs, and backups. Sync jobs and restores can also bring deleted data back.

For each of the **518 requests** in `dataset/deletion_requests.csv` we must build an agent that:

1. Decides whether the request **actually authorizes deletion**. If it doesn't, the answer is `NOT_APPLICABLE` with `[]`.
2. Resolves the subject's **current and historical identifiers**: email, phone, email hash, name, and the stable `user_id`.
3. Reconstructs the **true state of every related resource at `audit_at`** from the evidence (SQL, JSON, logs, TXT, PDF, PNG). Workflow claims don't count as proof.
4. Applies `deletion_rules.csv` to decide the required treatment for each resource.
5. Emits `COMPLETE` or `INCOMPLETE` with a canonically ordered `steps_json` (findings → remediation → verification).

---

## 2. Goals and Non-Goals

### 2.1 Goals (ranked)

| # | Goal | Success metric |
|---|---|---|
| G1 | Valid submission every run | 518 rows, sorted, valid JSON, only allowed ops/states, consecutive `step_no` |
| G2 | Correct case status | ≥ 95% `deletion_status` accuracy on the 32 samples |
| G3 | Correct resource discovery | Step-level F1 ≥ 0.90 on samples |
| G4 | Correct evidence citation and ordering | Exact sequence match ≥ 70% on samples |
| G5 | Low cost, deterministic | LLM used only where text, language, or vision demands it. All LLM outputs cached. Re-runs are byte-identical |
| G6 | Required reports | `evaluation/evaluation_report.md` and `evaluation/usage_report.md` complete |

### 2.2 Non-Goals

- No UI, web service, or database server. This is a CLI batch job.
- No fine-tuning and no vector DB. The corpus is about 95 files, so exact-identifier indexing beats embeddings here.
- No use of organizer-only files, golden labels, or case-family shortcuts (`AGENTS.md` §4.3).
- No real-time mutation of any system. Remediation is a *plan*, not an execution.

---

## 3. Users and Usage

| User | Need |
|---|---|
| Grader (automated) | `output.csv` matching the hidden canonical answers |
| AI interviewer | A clear architecture and an explainable investigation trail per case |
| Developer (us) | A fast eval loop on the 32 samples, plus per-case debug traces |

**Primary command**

```bash
python3 code/main.py                       # full run -> ./output.csv
python3 code/main.py --sample              # run on sample requests
python3 code/evaluation/main.py            # score samples + custom cases
python3 code/main.py --case case_11 --trace  # explain one case
```

---

## 4. Data Landscape (from the repo survey)

### 4.1 Tabular inputs

| File | Rows | Key facts |
|---|---|---|
| `deletion_requests.csv` | 518 | 375 unique `request_text`. Reported status: 254 COMPLETE / 152 PARTIAL / 112 NOT_STARTED |
| `sample_deletion_requests.csv` + `sample_output.csv` | 32 | 22 INCOMPLETE / 10 COMPLETE (no N/A in samples, so we must build our own N/A tests) |
| `user_identities.csv` | 850 | `user_id,name,email,phone,email_hash(sha256),updated_at` |
| `user_audit_log.csv` | 306 | Changes to `email`, `email_hash`, `phone` (old → new, timestamped) |
| `system_activity.csv` | 4,011 | 15 event types (DELETE, SYNC, INDEX, REDACT, ANONYMIZE, RETAIN, BLOCK_RESTORE, DISABLE_DATA_FLOW, CHECK_*, LINK_RESOURCE_IDENTITY, CLASSIFY_REQUEST, …). Results: SUCCESS/FAILED/PARTIAL. Mostly unrelated people |
| `deletion_rules.csv` | 15 | Category → action (DELETE / REDACT / ANONYMIZE / RETAIN) |
| `evidence_files.csv` | 94 | `file_id → path, origin, captured_at` |

### 4.2 Evidence corpus (`dataset/evidence/`)

| Type | Count | Format notes | Parser |
|---|---|---|---|
| `databases/*.sql` | 24 | SQLite dumps: `customer_profiles`, `customer_search_documents`, `customer_analytics_profiles`, `support_records`, `customer_exports`, `connector_subscriptions`, `backup_restore_entries`, `security_audit_records`, `snapshot_scope`, plus primary/replica/failover tables for drift | `sqlite3` in-memory load |
| `records/*.json` | 28 | Snapshot bundles (`snapshots[].records[]`), service exports (`profile_lookups` with 200/404), connector configs, export jobs, analytics reports, security ledger | Per-schema JSON walkers |
| `records/*.txt` | 1 | Handover: `time \| system \| resource \| CATEGORY \| STATE \| identifier` | Regex |
| `logs/*.log` | 26 | `key=value` structured logs: read-started/completed pairs joined by `trace_id`, plus `lookup_key=` emails | Logfmt parser + trace join |
| `documents/*.pdf` | 4 | Account history, legal retention register, security retention, delivery correction attachment | Text extraction → LLM fallback |
| `images/*.png` | 11 | Admin consoles (account, search, analytics, backup, connector, export, marketing, support, security, object storage) | **Vision LLM, cached once** |

### 4.3 Observed patterns that drive the design

- **Identifier forms vary.** Matches can be uppercase (`CHOI.JIHOON94@GMAIL.COM`), by email hash, by phone, or by `user_id` (`customer_reference`). **Decoys** are near-duplicates (`g.silva76@gmail.com` vs `g.silva76.jr@gmail.com`). Matching must be **exact after normalization**, never fuzzy.
- **Resource ID prefixes map to systems.** `account_*` → `account_service`, `search_*` → `search_service`, `support_*` → `support_platform`, `export_*` → `export_service`, `analytics_*` → `analytics_platform`, `data_flow_*` → `integration_service`, `backup_*` → `backup_service`, `audit_record_*` → `security_service`.
- **`LINK_RESOURCE_IDENTITY` activities** explicitly tie a resource to an email and `user_id`. This is a high-precision linking source.
- **A resource can appear many times across time.** State = the **latest observation with timestamp ≤ `audit_at`**. Evidence captured after `audit_at` is ignored entirely.
- **Sample-derived output rules:**
  - The INCOMPLETE verification phase always includes `VERIFY_RECORD_ABSENT` on the subject's `account_*`, even if the account wasn't a finding. It also includes `VERIFY_RECORD_PRESENT` for retained `audit_record_*`, plus one verify step per remediated resource.
  - COMPLETE cases contain only VERIFICATION steps, each with a non-empty `evidence_id`.
  - INCOMPLETE remediation and verification steps use `evidence_id: ""`.
  - Ordering: phase → operation (table order) → `system_id` → `resource_id`.

---

## 5. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR1 | **Intent classification.** Classify `request_text` (multilingual) as DELETE vs NON_DELETE. Access, export, correction, marketing opt-out, and similar requests → `NOT_APPLICABLE`, `[]` | P0 |
| FR2 | **Identity resolution.** From the request email, find `user_id` via current snapshot **or** audit-log history. Build the identifier set: all emails (current + historical), phones, hashes (stored + recomputed sha256 of normalized emails), name, `user_id` | P0 |
| FR3 | **Evidence ingestion.** Parse all 94 files into a normalized `Observation` table (§7.2). Vision/PDF extraction runs once and is cached | P0 |
| FR4 | **Linking.** Attach observations to the subject through exact identifier match, `customer_reference == user_id`, `LINK_RESOURCE_IDENTITY` activity, `trace_id` joins in logs, and transitive `resource_id` closure (once a resource is linked, every observation of that `resource_id` belongs to it) | P0 |
| FR5 | **Temporal state reconstruction.** For each linked resource, compute its state at `audit_at`: PRESENT / ABSENT / REDACTED / ANONYMIZED / ACTIVE / DISABLED / BLOCKED / RETAINED. Use the latest observation ≤ `audit_at`. Evidence observations beat activity claims. Activity `reported_result` is a claim | P0 |
| FR6 | **Policy engine.** Map resource → `data_category` → rule → required action, including conditions (support shared context → REDACT vs subject-only attachment → DELETE; analytics attributable → ANONYMIZE; security audit in retention → RETAIN; legal hold → RETAIN; backup → RETAIN + BLOCK restore; tombstone → REDACT keeping `user_id`) | P0 |
| FR7 | **Gap analysis.** Compare current state with required end state → findings (`REPORT_REMAINING_RECORD`, `REPORT_EXPOSED_PII`, `REPORT_ACTIVE_DATA_FLOW`, `REPORT_RESTORE_RISK`) | P0 |
| FR8 | **Plan generation.** Remediation steps (disable flows / block restores first), then verification steps for every remediated resource plus the required baseline (account absent, retained records present) | P0 |
| FR9 | **Evidence citation.** Each finding (and each COMPLETE verification) cites the `file_id`/`activity_id`/`audit_id` of the observation that established the state, chosen deterministically (§7.6) | P0 |
| FR10 | **Serializer and validator.** Canonical ordering, `step_no` renumbering, schema validation, 518-row guarantee (fallback row on any per-case exception) | P0 |
| FR11 | **Evaluation harness.** Status accuracy, step-level P/R/F1, field-level accuracy, sequence accuracy, per-case diff. Runs on samples + ≥3 custom cases | P0 |
| FR12 | **Usage tracking.** Count calls and input/output tokens per model, compute cost, write `usage_report.md` | P0 |
| FR13 | **Trace mode.** `--trace case_X` prints identifiers, linked observations, state timeline, and the policy decision for each resource | P1 |
| FR14 | **LLM adjudicator** for ambiguous cases (conflicting evidence, unclassifiable support context), constrained to a JSON schema and re-validated deterministically | P2 |

---

## 6. Non-Functional Requirements

| NFR | Target |
|---|---|
| Runtime | Full 518-case run < 2 min on a warm cache. Cold run (vision extraction) < 10 min |
| Determinism | Same inputs → byte-identical `output.csv` (sorted keys, stable sorts, `temperature=0`, cache-first) |
| Dependencies | Python 3.10+ stdlib core. Optional: `anthropic`, `pypdf`/`pdfplumber`. Never required for a cache-hit run |
| Secrets | `ANTHROPIC_API_KEY` from env / `.env` (gitignored). Never logged |
| Portability | All paths resolved from the repo root via `pathlib`, so it works on Windows/macOS/Linux |
| Robustness | A per-case exception produces a safe fallback row and an error log line, and never crashes the batch |

---

## 7. System Architecture

### 7.1 Design principle: deterministic core, LLM at the edges

Most of the problem is structured: joins, timestamps, policy lookup, and ordering. An LLM in the hot loop adds cost, nondeterminism, and hallucinated IDs. Three sub-problems genuinely need language or vision:

1. **Multilingual intent** (375 unique texts). Classify once per unique text and cache.
2. **Images and PDFs** (15 files). Extract structured rows once per file with a vision model and cache.
3. **Ambiguity adjudication** (optional). Only for cases where deterministic rules conflict.

Everything else is code.

### 7.2 Agent topology

```
                         ┌────────────────────────────────────────────┐
                         │            ORCHESTRATOR (main.py)          │
                         │  load → for each case: run pipeline → emit │
                         └───────────────┬────────────────────────────┘
                                         │
  ┌──────────────── one-time, cached ────┼──────────────────────────────────────┐
  │                                      ▼                                      │
  │  ┌──────────────────────┐   ┌─────────────────────┐   ┌──────────────────┐  │
  │  │ Evidence Ingestion   │   │ Multimodal Extractor │   │ Intent Classifier│  │
  │  │ Agent (deterministic)│   │ Agent (vision LLM)   │   │ Agent (LLM+rules)│  │
  │  │ SQL/JSON/LOG/TXT     │   │ PNG/PDF → rows JSON  │   │ unique texts     │  │
  │  └─────────┬────────────┘   └──────────┬──────────┘   └────────┬─────────┘  │
  │            └──────────────┬─────────────┘                       │            │
  │                           ▼                                     │            │
  │                ObservationStore (normalized,                    │            │
  │                indexed by identifier & resource_id)             │            │
  └───────────────────────────┬─────────────────────────────────────┼────────────┘
                              │                                     │
  ┌───────────────────── per case ──────────────────────────────────┼────────────┐
  │                           ▼                                     ▼            │
  │  ① Intent gate ── NON_DELETE ──────────────────────────► NOT_APPLICABLE, []  │
  │        │ DELETE                                                              │
  │        ▼                                                                     │
  │  ② Identity Resolver Agent  → IdentitySet{user_id, emails, phones, hashes}   │
  │        ▼                                                                     │
  │  ③ Evidence Linker Agent    → linked resources + observations (≤ audit_at)   │
  │        ▼                                                                     │
  │  ④ State Reconstructor      → resource state timeline → state @ audit_at     │
  │        ▼                                                                     │
  │  ⑤ Policy Agent             → category, rule, required end-state             │
  │        ▼                                                                     │
  │  ⑥ Planner Agent            → findings / remediation / verification          │
  │        ▼                                                                     │
  │  ⑦ Verifier / Critic        → schema + invariants; (P2) LLM adjudicator      │
  │        ▼                                                                     │
  │  ⑧ Serializer               → canonical order, step_no, JSON                 │
  └──────────────────────────────────────────────────────────────────────────────┘
```

"Agents" here are **single-responsibility modules with typed inputs and outputs**. Each one can be unit-tested, traced, and swapped. Only the three marked LLM agents call a model.

### 7.3 Core data model

```python
@dataclass(frozen=True)
class IdentitySet:
    user_id: str
    emails: frozenset[str]        # lowercased, current + historical
    phones: frozenset[str]        # digits-only normalized
    hashes: frozenset[str]        # stored + sha256(email) recomputed
    names: frozenset[str]
    valid_from: dict[str, str]    # identifier -> first-seen time (for audit_at checks)

@dataclass(frozen=True)
class Observation:
    evidence_id: str              # file_id | activity_id | audit_id
    source_kind: str              # sql|json|log|txt|pdf|image|activity
    observed_at: str              # record-level time if present, else file captured_at
    system_id: str
    resource_id: str
    category: str | None          # USER_PROFILE, SEARCH_INDEX_ENTRY, ... (if stated)
    state: str                    # PRESENT|ABSENT|REDACTED|ANONYMIZED|ACTIVE|DISABLED|BLOCKED|RETAINED|CLAIM_*
    identifiers: frozenset[str]   # normalized emails/phones/hashes/user_ids found on the record
    fields: dict                  # raw fields (for PII-exposed checks, shared-context flags)
    is_claim: bool                # True for activity rows / workflow messages

@dataclass
class ResourceVerdict:
    system_id: str; resource_id: str; category: str
    state_at_audit: str; state_evidence: str
    required_action: str          # DELETE|REDACT|ANONYMIZE|RETAIN|DISABLE|BLOCK
    compliant: bool
```

### 7.4 Agent specifications

#### A. Evidence Ingestion Agent (deterministic)

- **SQL:** load each dump into an in-memory `sqlite3` DB. Map every row of every known table to an `Observation`. Account for replica tables (`customer_data_primary`, `_read_replica`, `_replica_eu_west`, `_failover_replica`, …): **each replica is a separate copy**. Drift means the primary is ABSENT while a replica is PRESENT, which is a finding.
- **JSON:** schema-sniffing walkers for: snapshot bundles (`snapshots[].records[]`, per-snapshot `captured_at`), `service_exports.*.profile_lookups` (200 → PRESENT, 404 → ABSENT), result-records (`result: NOT_FOUND|FOUND|ACTIVE|DISABLED|BLOCKED|ANONYMIZED|IDENTIFIABLE`), connector configs (`enabled`), export jobs, analytics reports, security ledger.
- **Logs:** logfmt parser. Join `*_read_started lookup_key=<email>` with `*_read_completed resource_id=…` on `trace_id`. Treat `rows=0`/`not_found`/`404` as ABSENT, and `enabled=true` as ACTIVE.
- **TXT handover:** a pipe-delimited regex.
- Every observation gets `observed_at` = record time if present, else snapshot time, else manifest `captured_at`.

#### B. Multimodal Extractor Agent (LLM, one-shot per file, cached)

- Input: one PNG or PDF (PDF: try `pypdf` text first, and fall back to page images if the text is empty).
- Prompt: "Extract every table row as JSON `{system, resource_id, record_type, status, identifiers[], timestamp, notes}`. Copy IDs verbatim. Do not infer." The response is constrained by a JSON schema.
- Output is written to `code/cache/extracted/<file_id>.json` and **committed**, so graders can rerun without an API key.
- A post-check validates every `resource_id` regex and email format. Bad rows are dropped, and we spot-check by eye.

#### C. Intent Classifier Agent (rules + LLM, cached)

- Stage 1 rules: multilingual keyword lexicon (delete/erase/remove/close account/borrar/supprimer/löschen/削除/…) plus negative intents (export/copy/access/correct/update/unsubscribe/opt-out). Handle negation ("do **not** delete, just export").
- Stage 2 LLM (only when rules are low-confidence or detect a non-English language): `{"authorizes_deletion": bool, "intent": "...", "language": "...", "confidence": 0-1}`.
- Cache by `sha256(request_text)`. There are 375 unique texts, so at most 375 small calls (in practice far fewer).

#### D. Identity Resolver Agent

1. Normalize the request email (lowercase and trim).
2. Look it up in the current emails. If there's no hit, look it up in the audit-log `old_value`/`new_value` for `email`, then follow to `user_id`.
3. Collect all emails, phones, and hashes for that `user_id` from the snapshot plus all audit rows (both old and new values). Recompute `sha256(email)` for each email.
4. **Decoy guard:** exact match only. No substring, no edit-distance.
5. Unresolvable email: proceed with the identifier set {request email, its hash} and search the evidence directly (the account may exist only in evidence).

#### E. Evidence Linker Agent

Seed links (high precision):
- An observation whose `identifiers ∩ IdentitySet ≠ ∅`
- `customer_reference == user_id`
- A `LINK_RESOURCE_IDENTITY` activity naming our email or `user_id` (with `event_time ≤ audit_at`)

Expansion: **resource closure**. Every observation (any file, any time ≤ `audit_at`) with a linked `resource_id` is pulled in, including anonymized or 404 rows that carry no identifiers. This is how ABSENT and ANONYMIZED states get discovered.

Filter: drop observations with `observed_at > audit_at` and files with `captured_at > audit_at`.

#### F. State Reconstructor

- Per `(system_id, resource_id)` (and per replica table): sort observations by `observed_at`. The **latest evidence observation** wins. Activity rows (`is_claim`) only fill gaps:
  - `SYNC_RECORD`/`INDEX_RECORD`/`RESTORE_BACKUP` after a delete → possible re-creation, so the state is PRESENT unless later evidence shows ABSENT.
  - `DELETE_RECORD SUCCESS` alone is **not** proof of ABSENT. Look for a corroborating observation.
- Exposed-PII check for REDACT/ANONYMIZE categories: state = REDACTED/ANONYMIZED only if prohibited fields (name, email, phone, email_hash) are null or masked. Otherwise PRESENT (exposed).
- Data flows: ACTIVE if `enabled=1`/ACTIVE at the latest observation ≤ `audit_at`.
- Backups: ACTIVE restore risk unless BLOCKED is evidenced.

#### G. Policy Agent

| Resource / signal | Category | Required end state |
|---|---|---|
| `account_*` (no retained dependents) | USER_PROFILE | ABSENT |
| `account_*` with retained records referencing `user_id` | ACCOUNT_TOMBSTONE | REDACTED (keep `user_id`, strip name/email/phone/hash) |
| secondary emails/phones records | SECONDARY_IDENTIFIER | ABSENT |
| `search_*` | SEARCH_INDEX_ENTRY | ABSENT |
| cache entries | CACHE_ENTRY | ABSENT |
| `support_*` with shared order/agent context | SUPPORT_MESSAGE | REDACTED |
| `support_*` attachment owned only by subject | SUPPORT_ATTACHMENT | ABSENT |
| `analytics_*` attributable | ANALYTICS_PROFILE | ANONYMIZED |
| telemetry attributable | PRODUCT_TELEMETRY | ANONYMIZED |
| `export_*` | USER_EXPORT | ABSENT |
| marketing profile | MARKETING_PROFILE | ABSENT |
| email delivery log containing email | EMAIL_DELIVERY_LOG | REDACTED |
| `audit_record_*` in retention | SECURITY_AUDIT_LOG | PRESENT (retain) |
| legal-hold record (active hold) | LEGAL_HOLD_RECORD | PRESENT (retain) |
| `backup_*` | BACKUP_ARCHIVE | RETAIN + restore BLOCKED |
| `data_flow_*` touching subject | (recreation path) | DISABLED |

The category is taken from the evidence when stated (handover/JSON `record_type`), and inferred from the prefix and table otherwise. Condition evaluation (shared context, retention period, legal hold active) reads `fields`, the legal/security PDFs, and their extracted rows.

> **Open question OQ1 (resolve from samples by hour 4):** `case_12` shows `analytics_*` → `REPORT_REMAINING_RECORD` + `DELETE_RECORD` instead of ANONYMIZE. Find the distinguishing condition (rule_07 "still attributable" vs a record that is a pure identity copy) and encode it.

#### H. Planner Agent

```
findings     = [gap(r) for r in resources if not r.compliant]
remediation  = DISABLE_DATA_FLOW / BLOCK_RESTORE first,
               then DELETE / REDACT / ANONYMIZE (downstream before source)
verification = baseline (account ABSENT or tombstone REDACTED, retained PRESENT)
               ∪ verify(r) for each remediated r
status       = INCOMPLETE if findings else COMPLETE
COMPLETE     → verification steps only, each citing its proving evidence
```

Finding mapping:

| Gap | Finding op |
|---|---|
| Must be ABSENT, is PRESENT | `REPORT_REMAINING_RECORD` |
| Must be REDACTED/ANONYMIZED, PII visible | `REPORT_EXPOSED_PII` |
| Data flow ACTIVE | `REPORT_ACTIVE_DATA_FLOW` |
| Backup restorable | `REPORT_RESTORE_RISK` |

#### I. Serializer and Verifier

- Canonical sort key: `(PHASE_RANK, OP_RANK[operation], system_id, resource_id)`, with `OP_RANK` following the problem-statement table order. Then renumber `step_no` from 1.
- Invariants checked per row: allowed `(phase, operation, state)` triples; findings have `evidence_id`; INCOMPLETE remediation/verify have `""`; COMPLETE has only VERIFICATION with non-empty evidence; cited evidence `captured_at ≤ audit_at`; no duplicate steps.
- `json.dumps(steps, ensure_ascii=False, separators=(",", ":"))` with a fixed key order.

### 7.5 Ordering rules (canonical)

```
PHASE:  FINDING < REMEDIATION < VERIFICATION
OPS:    REPORT_REMAINING_RECORD < REPORT_EXPOSED_PII < REPORT_ACTIVE_DATA_FLOW < REPORT_RESTORE_RISK
        DISABLE_DATA_FLOW < BLOCK_RESTORE < DELETE_RECORD < REDACT_RECORD < ANONYMIZE_RECORD
        VERIFY_RECORD_ABSENT < VERIFY_RECORD_PRESENT < VERIFY_RECORD_REDACTED
          < VERIFY_RECORD_ANONYMIZED < VERIFY_DATA_FLOW_DISABLED < VERIFY_RESTORE_BLOCKED
THEN:   system_id ASC, resource_id ASC (string compare — confirm vs samples)
```

### 7.6 Evidence-citation policy

For each step that needs a citation, choose the **observation that determined `state_at_audit`**: the latest non-claim observation ≤ `audit_at` for that resource. Break ties by evidence-type priority (consolidated snapshot/handover > SQL > JSON > log > image/PDF > activity), then by `evidence_id` ascending. Validate the choice against the samples. The samples often cite a single consolidated file (e.g. `evidence_03`, `evidence_92`, `evidence_94`) for every step in a case, which suggests that a file covering *all* of a case's resources at the latest time ≤ `audit_at` is preferred. Encode this as rule **C1: prefer one file that covers all resources** and measure both variants.

---

## 8. Code Layout

```
code/
├── main.py                    # CLI orchestrator (argparse: --sample, --case, --trace, --no-llm)
├── agent/
│   ├── config.py              # paths, constants, OP_RANK, prefix→system map, model ids
│   ├── io.py                  # CSV loaders, output writer, manifest
│   ├── intent.py              # Agent C
│   ├── identity.py            # Agent D
│   ├── ingest/
│   │   ├── sql.py  json_.py  logs.py  text.py
│   │   └── multimodal.py      # Agent B (vision + PDF), cache-first
│   ├── store.py               # ObservationStore + indexes (by identifier, by resource_id)
│   ├── linker.py              # Agent E
│   ├── state.py               # Agent F
│   ├── policy.py              # Agent G
│   ├── planner.py             # Agent H
│   ├── serialize.py           # Agent I (ordering, validation)
│   ├── llm.py                 # thin client: caching, retries, token/cost accounting
│   └── trace.py               # per-case explanation
├── cache/
│   ├── extracted/<file_id>.json   # committed vision/PDF extractions
│   └── intent.json                # committed intent cache
└── evaluation/
    ├── main.py                # metrics + per-case diff
    ├── custom_cases.csv       # ≥3 hand-built cases (incl. NOT_APPLICABLE, multilingual, decoy)
    └── custom_expected.csv
evaluation/
├── evaluation_report.md
└── usage_report.md
README.md
```

---

## 9. LLM Usage Plan

| Agent | Model | Calls (est.) | When |
|---|---|---|---|
| Multimodal Extractor | `claude-sonnet-5-5` (vision) | 15 files (+ PDF pages) | Once, cached and committed |
| Intent Classifier | `claude-haiku-5-5` | ≤ 375 (only ambiguous or non-English after rules) | Once per unique text, cached |
| Adjudicator (P2) | `claude-sonnet-5-5` | ≤ 30 | Only flagged conflict cases |

- `temperature=0`, JSON-schema-constrained outputs, and a deterministic prompt version hash in the cache key.
- `llm.py` records `{agent, model, input_tokens, output_tokens, cached}` per call to `code/cache/usage.jsonl`. `usage_report.md` is generated from it, with pricing pulled from current published rates at report time.
- `--no-llm` mode runs from caches only, and falls back to rules when the cache misses.

---

## 10. Evaluation Plan

**Metrics** (`code/evaluation/main.py`, against `sample_output.csv` and custom cases):

| Metric | Definition |
|---|---|
| Status accuracy | % cases with the exact `deletion_status` |
| Step-level P/R/F1 | Match on the tuple `(phase, system_id, resource_id, operation, state, evidence_id)` |
| Field-level accuracy | Per-field accuracy over aligned steps (aligned by `(phase, resource_id, operation)`) |
| Sequence accuracy | % cases whose full step array matches exactly, in order |
| Evidence accuracy | % findings/verifications citing the expected `evidence_id` |

**Custom cases (≥3, more is better):**
1. Non-deletion request (data export / access in Spanish) → `NOT_APPLICABLE`, `[]`.
2. Historical email (request uses the pre-change address from the audit log) with a replica still holding the old email.
3. Decoy: a near-identical email in the evidence must **not** be linked.
4. Evidence after `audit_at` shows the deletion done, but the state at `audit_at` is INCOMPLETE.
5. Tombstone: an account with a retained security audit record → REDACT, not DELETE.

**Error analysis loop:** per-case diff printout → categorize failures (identity / linking / state / policy / citation / ordering) → fix the top category → re-run. Each iteration is logged in `evaluation_report.md` under "Failures found and improvements made".

---

## 11. 12-Hour Delivery Plan

| Hour | Milestone | Exit criteria |
|---|---|---|
| 0–1 | Skeleton: loaders, config, serializer, validator, eval harness | `main.py` writes 518 valid rows (all fallback); eval runs |
| 1–3 | Ingestion: SQL, JSON, logs, TXT → ObservationStore | Every non-image file parsed; counts per file sane; trace shows observations for a sample case |
| 3–4 | Identity + Linker + time filter | Sample cases resolve `user_id`; linked resources ⊇ expected resources |
| 4–6 | State + Policy + Planner, resolve OQ1 | Sample status ≥ 90%, step F1 ≥ 0.8 |
| 6–7 | Multimodal extraction (vision/PDF) + cache commit | 15 files extracted, spot-checked |
| 7–8 | Intent classifier (rules + LLM + cache), custom N/A cases | N/A cases correct; no deletion request misclassified |
| 8–10 | Error-analysis iterations: citation policy C1, ordering, replicas, tombstones | Sample targets in §2.1 met |
| 10–11 | Full run, usage report, evaluation report, README | All deliverables present |
| 11–12 | Buffer: clean-clone test, `code.zip` packaging, submit | Submitted |

**Cut-line if behind:** drop the P2 adjudicator, then drop LLM intent (use rules only), and keep the multimodal cache. A valid 518-row output is always protected by the fallback.

---

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Decoy identifiers cause false links | Wrong findings | Exact normalized match only. Custom decoy test case |
| Evidence after `audit_at` leaks in | Wrong status | Filter at linker level on both file `captured_at` and record `observed_at`. Validator rejects late citations |
| Trusting activity `SUCCESS` | False COMPLETE | Claims never override evidence. DELETE needs corroboration |
| Vision extraction hallucinates IDs | Phantom resources | Schema plus regex validation. Manual spot-check. Committed cache |
| Citation choice mismatches the grader | Field-level loss | Measure variants on samples (§7.6), pick the best |
| Ordering mismatch on `resource_id` (string vs numeric) | Sequence loss | Confirm on samples; config toggle |
| API outage or no key at grading | Run fails | Committed caches + `--no-llm` fallback |
| Overfitting to the 32 samples | Hidden-set loss | Rules derived from the policy text, not sample IDs. Custom cases |

---

## 13. Acceptance Criteria (Definition of Done)

- [ ] `python3 code/main.py` from a clean clone (no API key, caches committed) writes `./output.csv` with exactly 518 rows, sorted, all schema-valid.
- [ ] Sample metrics meet the §2.1 targets, and are recorded in `evaluation/evaluation_report.md` with ≥3 custom cases and a failures/improvements log.
- [ ] `evaluation/usage_report.md` lists providers, models, call counts, tokens (in/out/total/avg per request), and cost (total and per request), per model and overall.
- [ ] README has setup, env vars, run, and eval commands.
- [ ] `code.zip` excludes `dataset/`, venvs, caches of secrets, `.env`, and nested zips.
- [ ] `log.txt` is up to date per `AGENTS.md` §5.

---

## 14. Open Questions

| ID | Question | Plan |
|---|---|---|
| OQ1 | When is an `analytics_*` record DELETE vs ANONYMIZE? (`case_12`) | Inspect case_12's evidence fields by hour 4 |
| OQ2 | When does an account become ACCOUNT_TOMBSTONE (REDACT) vs USER_PROFILE (DELETE)? | Check whether retained records reference `user_id`. Examine the deleted-account-reference image and samples |
| OQ3 | Which `evidence_id` does the grader expect when several files prove the same state? | §7.6 variant testing |
| OQ4 | Does each replica table count as a separate resource, or the same `resource_id` with the worst state? | Inspect the drift files against the samples that cite SQL evidence (`evidence_05`) |
| OQ5 | Do `SECONDARY_IDENTIFIER` / `CACHE_ENTRY` / `MARKETING_PROFILE` ever appear as resources? | grep the evidence for their prefixes during ingestion |
