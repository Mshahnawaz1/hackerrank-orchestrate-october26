"""Planner Agent: findings, ordered remediation and verification steps for one case."""
from .policy import Verdict

FIX = {
    "REPORT_REMAINING_RECORD": ("DELETE_RECORD", "ABSENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("DISABLE_DATA_FLOW", "DISABLED"),
    "REPORT_RESTORE_RISK": ("BLOCK_RESTORE", "BLOCKED"),
}
EXPOSED_FIX = {"REDACT": ("REDACT_RECORD", "REDACTED"), "ANONYMIZE": ("ANONYMIZE_RECORD", "ANONYMIZED")}
FINDING_STATE = {"REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
                 "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE"}
VERIFY = {"ABSENT": "VERIFY_RECORD_ABSENT", "PRESENT": "VERIFY_RECORD_PRESENT",
          "REDACTED": "VERIFY_RECORD_REDACTED", "ANONYMIZED": "VERIFY_RECORD_ANONYMIZED",
          "DISABLED": "VERIFY_DATA_FLOW_DISABLED", "BLOCKED": "VERIFY_RESTORE_BLOCKED"}
ACCOUNT_CATEGORY = "USER_PROFILE"


def step(phase, operation, state, verdict: Verdict, evidence_id=""):
    res = verdict.resource
    return {"phase": phase, "system_id": res.system_id, "resource_id": res.resource_id,
            "operation": operation, "state": state, "evidence_id": evidence_id}


def plan(verdicts: list[Verdict]) -> tuple[str, list[dict]]:
    """Return (deletion_status, unordered steps). The serializer applies canonical order."""
    gaps = [v for v in verdicts if v.finding]
    if not gaps:
        return "COMPLETE", _complete_checks(verdicts)

    steps = []
    remediated = set()
    for v in gaps:
        steps.append(step("FINDING", v.finding, FINDING_STATE[v.finding], v, v.resource.evidence_id))
        operation, state = EXPOSED_FIX[v.action] if v.finding == "REPORT_EXPOSED_PII" else FIX[v.finding]
        steps.append(step("REMEDIATION", operation, state, v))
        steps.append(step("VERIFICATION", VERIFY[state], state, v))
        remediated.add(v.resource.resource_id)
    for v in verdicts:                                    # baseline: account gone, retained records kept
        if v.resource.resource_id in remediated:
            continue
        if v.resource.category == ACCOUNT_CATEGORY or v.action == "RETAIN":
            steps.append(step("VERIFICATION", VERIFY[v.required_state], v.required_state, v))
    return "INCOMPLETE", steps


def _complete_checks(verdicts: list[Verdict]) -> list[dict]:
    """A COMPLETE case proves each required state with the evidence that established it."""
    return [step("VERIFICATION", VERIFY[v.current_state], v.current_state, v, v.resource.evidence_id)
            for v in verdicts if v.compliant and v.current_state in VERIFY]
