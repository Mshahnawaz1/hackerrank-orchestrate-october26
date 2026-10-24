"""Paths and constants shared across the pipeline."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
EVIDENCE = DATASET / "evidence"
CACHE = REPO_ROOT / "code" / "cache"
OUTPUT = REPO_ROOT / "output.csv"

STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
FALLBACK_STATUS = "INCOMPLETE"

PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}

# operation -> (phase, required state)
OPERATIONS = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}

# canonical operation order: the table order of the problem statement
OP_RANK = {op: i for i, op in enumerate(OPERATIONS)}

STEP_FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
OUTPUT_COLUMNS = ("case_id", "deletion_status", "steps_json")

# resource_id prefix -> owning system, longest prefix first
PREFIX_SYSTEM = {
    "audit_record_": "security_service",
    "data_flow_": "integration_service",
    "analytics_": "analytics_platform",
    "account_": "account_service",
    "backup_": "backup_service",
    "export_": "export_service",
    "search_": "search_service",
    "support_": "support_platform",
    "tombstone_": "identity_service",
}

# table / collection name fragment -> deletion_rules data_category
COLLECTION_CATEGORY = {
    "customer_profiles": "USER_PROFILE",
    "search_documents": "SEARCH_INDEX_ENTRY",
    "index_queries": "SEARCH_INDEX_ENTRY",
    "analytics": "ANALYTICS_PROFILE",
    "profiles": "ANALYTICS_PROFILE",
    "support_records": "SUPPORT_MESSAGE",
    "support_conversations": "SUPPORT_MESSAGE",
    "tickets": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "export": "USER_EXPORT",
    "connector": "DATA_FLOW",
    "backup": "BACKUP_ARCHIVE",
    "restore_entries": "BACKUP_ARCHIVE",
    "security_audit": "SECURITY_AUDIT_LOG",
    "audit_records": "SECURITY_AUDIT_LOG",
    "retained_order": "LEGAL_HOLD_RECORD",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
}

# fallback when the collection name is uninformative (logs, service exports)
PREFIX_CATEGORY = {
    "audit_record_": "SECURITY_AUDIT_LOG",
    "data_flow_": "DATA_FLOW",
    "analytics_": "ANALYTICS_PROFILE",
    "account_": "USER_PROFILE",
    "backup_": "BACKUP_ARCHIVE",
    "export_": "USER_EXPORT",
    "search_": "SEARCH_INDEX_ENTRY",
    "support_": "SUPPORT_MESSAGE",
    "tombstone_": "ACCOUNT_TOMBSTONE",
}

# data_category -> owning system (for tables whose rows do not name their system)
CATEGORY_SYSTEM = {
    "USER_PROFILE": "account_service",
    "SEARCH_INDEX_ENTRY": "search_service",
    "ANALYTICS_PROFILE": "analytics_platform",
    "SUPPORT_MESSAGE": "support_platform",
    "SUPPORT_ATTACHMENT": "support_platform",
    "USER_EXPORT": "export_service",
    "DATA_FLOW": "integration_service",
    "BACKUP_ARCHIVE": "backup_service",
    "SECURITY_AUDIT_LOG": "security_service",
    "ACCOUNT_TOMBSTONE": "identity_service",
    "LEGAL_HOLD_RECORD": "legal_service",
}

# explicit result vocabulary -> observation state
RESULT_STATE = {
    "FOUND": "PRESENT", "IDENTIFIABLE": "PRESENT", "HIT": "PRESENT",
    "NOT_FOUND": "ABSENT", "MISS": "ABSENT",
    "ACTIVE": "ACTIVE", "DISABLED": "DISABLED", "BLOCKED": "BLOCKED",
    "ANONYMIZED": "ANONYMIZED", "REDACTED": "REDACTED",
}
