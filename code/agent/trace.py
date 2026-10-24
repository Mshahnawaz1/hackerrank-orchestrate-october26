"""Per-case explanation: identity, linked resources, state at audit_at and the policy decision."""
from .pipeline import CaseResult


def format_trace(request: dict, result: CaseResult) -> str:
    lines = [f"case {request['case_id']}  email={request['email']}  audit_at={request['audit_at']}",
             f"  intent: {result.intent}"]
    if result.case is None:
        return "\n".join(lines + [f"  -> {result.row['deletion_status']}"])
    ident = result.case.identity
    lines.append(f"  identity: user_id={ident.user_id} emails={sorted(ident.emails)} phones={sorted(ident.phones)}")
    verdicts = {v.resource.resource_id: v for v in result.verdicts}
    for rid in result.case.resource_ids:
        st = result.states[rid]
        v = verdicts.get(rid)
        decision = (f"{v.action} required={v.required_state} current={v.current_state} finding={v.finding}"
                    if v else "not governed")
        lines.append(f"  {rid:<20} via {result.case.seeds.get(rid, '?'):<28} {st.category or '-':<20} "
                     f"state={st.state} evidence={st.evidence_id or '-'} @ {st.observed_at or '-'}")
        lines.append(f"  {'':<20} {decision}")
        for obs in sorted(result.case.observations.get(rid, []), key=lambda o: o.observed_at):
            lines.append(f"  {'':<22}- {obs.observed_at} {obs.evidence_id:<12} {obs.state:<9} {obs.copy}")
        for row in result.case.claims.get(rid, []):
            lines.append(f"  {'':<22}~ {row['event_time']} {row['activity_id']:<14} "
                         f"{row['event_type']} {row['reported_result']} (claim)")
    lines.append(f"  -> {result.row['deletion_status']} {result.row['steps_json']}")
    return "\n".join(lines)
