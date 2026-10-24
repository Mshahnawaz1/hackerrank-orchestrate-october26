"""Deterministic intent classifier: does `request_text` authorize deletion?

Rules only (v1). Every result carries one of three confidence levels:

  HIGH    independent signals agree (deletion verb + data object, or an explicit
          refusal of deletion together with another non-deletion intent)
  MEDIUM  a single signal (deletion verb alone, non-deletion intent alone, or a bare negation)
  LOW     no signal, or deletion and non-deletion signals conflict. `authorizes_deletion`
          is None and `needs_llm` is True; an LLM fallback is planned for these.
"""
import re
from dataclasses import dataclass

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"

_FLAGS = re.IGNORECASE

# Deletion verbs across English, French, Spanish, Portuguese, German, Japanese and Korean.
DELETE_VERB = re.compile(
    r"\b(?:delet\w*|eras\w*|wipe|purge"
    r"|remov\w*\s+(?:\w+\s+){0,3}(?:account|profile|personal|data|records?|copy|file|export|result)"
    r"|been\s+(?:removed|erased)|(?:is|are)\s+gone"
    r"|clos\w*\s+(?:my|the|this)?\s*account"
    r"|suppression|supprim\w*|eliminaci[oó]n|eliminar|borrar|exclus[aã]o|excluir|apagar"
    r"|l[oö]sch\w*)\b"
    r"|削除|消去|삭제",
    _FLAGS,
)
# What is being deleted: the account or its personal data.
DELETE_OBJECT = re.compile(
    r"\b(?:account|profile|personal|data|records?|copy|file|export|compte|cuenta|conta|konto)\b|アカウント|계정|個人情報|개인정보",
    _FLAGS,
)
# Explicit refusal of deletion ("do not delete", "not a request to erase", "without removing").
NEGATED_DELETE = re.compile(
    r"\b(?:do\s*n[o']?t|don'?t|never|not|without)\s+(?:\w+\s+){0,3}(?:delet\w*|eras\w*|clos\w*|remov\w*)"
    r"|\bnot\s+(?:asking|requesting)\s+for\s+(?:deletion|erasure)",
    _FLAGS,
)
# Requests for something other than deletion.
OTHER_INTENTS = {
    "ACCESS": re.compile(
        r"what\s+personal\s+information|(?:send|give|provide|need|want)\s+(?:me\s+)?a\s+copy\s+of|\bdownload\s+my\b|portable\s+format|data\s+access", _FLAGS),
    "CORRECTION": re.compile(
        r"misspell|\bcorrect\s+(?:it|my|the)\b|out\s+of\s+date|\breplace\s+it\b"
        r"|change\s+the\s+(?:email|address|number)|\bupdate\s+my\b", _FLAGS),
    "MARKETING": re.compile(r"marketing|promotional|unsubscribe|opt[\s-]?out|newsletter", _FLAGS),
    "SUPPORT": re.compile(r"reset(?:ting)?\s+the\s+login|reset\s+(?:my\s+)?password|can'?t\s+access", _FLAGS),
}
# Statements that the account should stay, which reinforce a non-deletion reading.
KEEP_ACCOUNT = re.compile(
    r"\bkeep\b|\bleave\b[^.]{0,40}\bin\s+place|continue\s+using|still\s+(?:use|need|want)|as\s+it\s+is|leave\s+the\s+account",
    _FLAGS,
)


@dataclass(frozen=True)
class IntentResult:
    authorizes_deletion: bool | None    # None when undecided
    intent: str                          # DELETION | ACCESS | CORRECTION | MARKETING | SUPPORT | UNKNOWN
    confidence: str                      # HIGH | MEDIUM | LOW

    @property
    def needs_llm(self) -> bool:
        return self.confidence == LOW


def classify(request_text: str) -> IntentResult:
    text = request_text or ""
    negated = bool(NEGATED_DELETE.search(text))
    positive_text = NEGATED_DELETE.sub(" ", text)          # a negated verb is not a deletion signal
    has_verb = bool(DELETE_VERB.search(positive_text))
    has_object = bool(DELETE_OBJECT.search(positive_text))
    other = next((name for name, rx in OTHER_INTENTS.items() if rx.search(text)), None)

    if negated:
        confidence = HIGH if other or KEEP_ACCOUNT.search(text) else MEDIUM
        return IntentResult(False, other or "UNKNOWN", confidence)
    if has_verb and other:
        return IntentResult(None, "UNKNOWN", LOW)           # conflicting signals
    if has_verb:
        return IntentResult(True, "DELETION", HIGH if has_object else MEDIUM)
    if other:
        return IntentResult(False, other, HIGH if KEEP_ACCOUNT.search(text) else MEDIUM)
    return IntentResult(None, "UNKNOWN", LOW)
