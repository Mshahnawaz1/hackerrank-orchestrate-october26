"""Per-case pipeline. Later stages (identity, linking, state, policy, planner) plug in here."""
import sys

from . import config, intent, serialize


def fallback_row(case_id: str) -> dict:
    return {"case_id": case_id, "deletion_status": config.FALLBACK_STATUS, "steps_json": "[]"}


def solve_case(request: dict) -> dict:
    """Non-deletion requests are NOT_APPLICABLE; the rest stay INCOMPLETE until later stages land."""
    case_id = request["case_id"]
    if intent.classify(request["request_text"]).authorizes_deletion is False:
        return {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}
    return {"case_id": case_id, "deletion_status": config.FALLBACK_STATUS,
            "steps_json": serialize.serialize_steps([])}


def run(requests: list[dict]) -> list[dict]:
    """Solve every request; a per-case failure yields the fallback row instead of crashing the batch."""
    rows = []
    for req in requests:
        try:
            rows.append(solve_case(req))
        except Exception as e:
            print(f"{req['case_id']}: fallback after error: {e}", file=sys.stderr)
            rows.append(fallback_row(req["case_id"]))
    return sorted(rows, key=lambda r: r["case_id"])
