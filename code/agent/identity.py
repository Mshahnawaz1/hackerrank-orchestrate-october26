"""Identity Resolver Agent: request email -> the subject's current and historical identifiers."""
import hashlib
from dataclasses import dataclass

from .store import norm_email, norm_phone


@dataclass(frozen=True)
class IdentitySet:
    user_id: str | None
    emails: frozenset
    phones: frozenset
    hashes: frozenset
    names: frozenset

    @property
    def identifiers(self) -> frozenset:
        """Every normalized value used for exact-match linking (names are excluded: decoy risk)."""
        ids = set(self.emails) | set(self.phones) | set(self.hashes)
        if self.user_id:
            ids.add(self.user_id)
        return frozenset(ids)


def email_hash(email: str) -> str:
    return hashlib.sha256(norm_email(email).encode("utf-8")).hexdigest()


class IdentityResolver:
    def __init__(self, identities: list[dict], audit_log: list[dict]):
        self._by_user = {r["user_id"]: r for r in identities}
        self._by_email = {norm_email(r["email"]): r["user_id"] for r in identities}
        self._audit = sorted(audit_log, key=lambda r: (r["event_time"], r["audit_id"]))
        self._audit_email = {}
        for r in self._audit:
            if r["field_name"] == "email":
                for value in (r["old_value"], r["new_value"]):
                    self._audit_email.setdefault(norm_email(value), r["user_id"])

    def resolve(self, email: str, audit_at: str) -> IdentitySet:
        """Exact match on the current snapshot, then on audit-log email history."""
        key = norm_email(email)
        user_id = self._by_email.get(key) or self._audit_email.get(key)
        emails, phones, hashes, names = {key}, set(), set(), set()
        if user_id:
            snap = self._by_user.get(user_id)
            if snap:
                emails.add(norm_email(snap["email"]))
                phones.add(norm_phone(snap["phone"]))
                hashes.add(snap["email_hash"].lower())
                names.add(snap["name"])
            for r in self._audit:
                if r["user_id"] != user_id or r["event_time"] > audit_at:
                    continue
                values = (r["old_value"], r["new_value"])
                if r["field_name"] == "email":
                    emails.update(norm_email(v) for v in values if v)
                elif r["field_name"] == "phone":
                    phones.update(norm_phone(v) for v in values if v)
                elif r["field_name"] == "email_hash":
                    hashes.update(v.lower() for v in values if v)
        hashes.update(email_hash(e) for e in emails)
        return IdentitySet(user_id, frozenset(emails), frozenset(p for p in phones if p),
                           frozenset(hashes), frozenset(names))
