"""Policy Agent: data category -> deletion rule -> required end state, and the compliance gap."""
from dataclasses import dataclass

from .state import ResourceState

# deletion_rules.csv action -> required end state
ACTION_STATE = {"DELETE": "ABSENT", "REDACT": "REDACTED", "ANONYMIZE": "ANONYMIZED", "RETAIN": "PRESENT"}
# resources the rules file does not cover: recreation paths
FLOW_CATEGORIES = {"DATA_FLOW": "DISABLED"}
BACKUP_CATEGORY = "BACKUP_ARCHIVE"


@dataclass
class Verdict:
    resource: ResourceState
    action: str                     # DELETE | REDACT | ANONYMIZE | RETAIN | DISABLE | BLOCK
    required_state: str             # ABSENT | REDACTED | ANONYMIZED | PRESENT | DISABLED | BLOCKED
    current_state: str | None       # as above, or EXPOSED / None (unknown)
    finding: str | None             # finding operation when the resource is not compliant

    @property
    def compliant(self) -> bool:
        return self.current_state is not None and self.finding is None


class PolicyEngine:
    def __init__(self, rules: list[dict]):
        self.actions = {r["data_category"]: r["required_action"] for r in rules}

    def evaluate(self, res: ResourceState) -> Verdict | None:
        """None when the resource's category is not governed (nothing to require)."""
        cat = res.category
        if cat in FLOW_CATEGORIES:
            current = _flow_state(res)
            finding = "REPORT_ACTIVE_DATA_FLOW" if current == "ACTIVE" else None
            return Verdict(res, "DISABLE", "DISABLED", current, finding)
        if cat == BACKUP_CATEGORY:                        # retained, but restore must be blocked
            current = _flow_state(res)
            finding = "REPORT_RESTORE_RISK" if current == "ACTIVE" else None
            return Verdict(res, "BLOCK", "BLOCKED", "BLOCKED" if current == "ABSENT" else current, finding)
        action = self.actions.get(cat)
        if action is None:
            return None
        required = ACTION_STATE[action]
        current = _treated_state(res, action)
        finding = None
        if current is not None and current != required:
            if action == "DELETE":
                finding = "REPORT_REMAINING_RECORD" if current != "ABSENT" else None
            elif action in ("REDACT", "ANONYMIZE"):
                finding = "REPORT_EXPOSED_PII" if current == "EXPOSED" else None
        return Verdict(res, action, required, current, finding)


def _flow_state(res: ResourceState) -> str | None:
    if res.state in ("ACTIVE", "DISABLED", "BLOCKED", "ABSENT"):
        return res.state
    return None if res.state is None else "ACTIVE"


def _treated_state(res: ResourceState, action: str) -> str | None:
    """Map the observed state onto the vocabulary of the required treatment."""
    state = res.state
    if state is None:
        return None
    if action in ("DELETE", "RETAIN"):
        return "ABSENT" if state == "ABSENT" else "PRESENT"
    if state == "ABSENT":
        return "ABSENT"
    if state in ("REDACTED", "ANONYMIZED"):
        return ACTION_STATE[action]
    if action == "REDACT":                                # a stable user_id reference may stay
        return "EXPOSED" if res.exposed else "REDACTED"
    return "EXPOSED" if res.attributable else "ANONYMIZED"
