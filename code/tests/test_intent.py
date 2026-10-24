import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.intent import HIGH, LOW, MEDIUM, classify  # noqa: E402


class IntentTests(unittest.TestCase):
    def check(self, text, authorizes, confidence, intent=None):
        r = classify(text)
        self.assertEqual((r.authorizes_deletion, r.confidence), (authorizes, confidence), text)
        if intent:
            self.assertEqual(r.intent, intent)

    def test_high_deletion_multilingual(self):
        for text in (
            "Please erase the account linked to this email address.",
            "Je demande la suppression définitive du compte associé à cette adresse e-mail.",
            "Solicito la eliminación permanente de la cuenta asociada a este correo.",
            "Solicito a exclusão permanente da conta associada a este e-mail.",
            "このメールアドレスに関連するアカウントの完全な削除を依頼します。",
            "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다.",
            "I deleted this account, but the same email is still recognized. Please remove any remaining copy of my profile.",
        ):
            self.check(text, True, HIGH, "DELETION")

    def test_high_non_deletion(self):
        self.check("Please remove me from marketing lists only. I still want receipts.", False, HIGH, "MARKETING")
        self.check("I can't access my profile. Do not close the account.", False, HIGH, "SUPPORT")
        self.check("Can you correct it without removing any of my records?", False, HIGH, "CORRECTION")

    def test_medium_single_signal(self):
        self.check("Please wipe everything.", True, MEDIUM)
        self.check("I would like a download of my order history.", None, LOW)
        self.check("Please do not delete anything.", False, MEDIUM)
        self.check("Send me a copy of my data.", False, MEDIUM, "ACCESS")

    def test_low_conflict_or_no_signal(self):
        self.check("Delete my account and send me a copy of my data.", None, LOW)
        self.check("Hello, I have a question.", None, LOW)
        self.check("", None, LOW)
        self.assertTrue(classify("").needs_llm)


if __name__ == "__main__":
    unittest.main()
