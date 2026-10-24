import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import cache, config, llm  # noqa: E402
from agent.ingest import extract_text, multimodal  # noqa: E402

PDF = config.DATASET / "evidence/documents/delivery_correction_attachment.pdf"
EVIDENCE = {"file_id": "evidence_58", "file_path": "evidence/documents/delivery_correction_attachment.pdf",
            "origin": "x", "captured_at": "2026-09-12T07:30:00Z"}


def fake_formatter(calls):
    def fmt(name, text, hint=""):
        calls.append(name)
        return {"rows": [
            {"system": "support_platform", "resource_id": "support_001", "record_type": "SUPPORT_ATTACHMENT",
             "status": None, "identifiers": ["priya.raman@gmail.com", "+91 98765 73142"],
             "timestamp": "18 Jun 2026", "notes": None},
            {"resource_id": "not-an-id", "identifiers": ["x@y.com"]},
            {"resource_id": None, "identifiers": []}]}
    return fmt


class ExtractTextTests(unittest.TestCase):
    def test_pdf_text_rows_keep_cells_together(self):
        text = extract_text.extract_text(PDF)
        self.assertIn("support_001", text)
        self.assertIn("Detail | priya.raman@gmail.com", text)

    def test_all_pdfs_yield_text(self):
        for pdf in sorted((config.DATASET / "evidence/documents").glob("*.pdf")):
            self.assertGreater(len(extract_text.extract_text(pdf)), 100, pdf.name)

    def test_image_without_ocr_is_reported_not_crashed(self):
        with mock.patch("shutil.which", return_value=None), mock.patch.dict(sys.modules, {"pytesseract": None}):
            with self.assertRaises(extract_text.ExtractorUnavailable):
                extract_text.image_text(config.DATASET / "evidence/images/account_admin_console_20260926.png")


class RetryTests(unittest.TestCase):
    def test_overlooked_resource_id_triggers_one_retry(self):
        answers = [{"rows": [{"resource_id": None, "identifiers": ["a@b.co"]}]},
                   {"rows": [{"resource_id": "support_001", "identifiers": ["a@b.co"]}]}]
        seen = []

        def fmt(name, text, hint=""):
            seen.append(hint)
            return answers[len(seen) - 1]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "CACHE", Path(tmp)):
            multimodal.process(EVIDENCE, formatter=fmt)
            doc = json.loads((Path(tmp) / "extracted/evidence_58.json").read_text())["payload"]
        self.assertEqual(len(seen), 2)
        self.assertIn("support_001", seen[1])
        self.assertEqual(doc["rows"][0]["resource_id"], "support_001")
        self.assertEqual(doc["uncovered_resource_ids"], [])


class JsonRetryTests(unittest.TestCase):
    def test_invalid_json_is_retried_once(self):
        replies = iter([ValueError("bad json"), {"rows": [{"resource_id": "support_001", "identifiers": ["a@b.co"]}]}])
        hints = []

        def fmt(name, text, hint=""):
            hints.append(hint)
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "CACHE", Path(tmp)):
            result = multimodal.process(EVIDENCE, formatter=fmt)
        self.assertTrue(result.startswith("extracted 1 rows"), result)
        self.assertIn("not valid JSON", hints[1])


class RevalidateTests(unittest.TestCase):
    def test_validation_change_does_not_call_llm_again(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "CACHE", Path(tmp)):
            multimodal.process(EVIDENCE, formatter=fake_formatter(calls))
            with mock.patch.object(multimodal, "VALIDATION_VERSION", "next"):
                result = multimodal.process(EVIDENCE, formatter=fake_formatter(calls))
        self.assertTrue(result.startswith("revalidated"), result)
        self.assertEqual(len(calls), 1)

    def test_all_resource_types_are_valid(self):
        for rid in ("marketing_001", "email_delivery_7693", "cache_4493", "legal_hold_3", "object_19", "support_9"):
            self.assertTrue(multimodal.RESOURCE_RE.match(rid), rid)


class OcrCleanupTests(unittest.TestCase):
    def test_restores_dropped_underscores_only_on_ids(self):
        fixed = extract_text._fix_ocr_ids("user 17 Retained; user13 and account 5762; support 9538; Support CS-8538; user 9")
        self.assertEqual(fixed, "user_17 Retained; user_13 and account_5762; support_9538; Support CS-8538; user 9")


class ValidateTests(unittest.TestCase):
    def test_drops_bad_rows(self):
        kept, dropped = multimodal.validate_rows([
            {"resource_id": "account_12", "identifiers": ["a@b.co"]},
            {"resource_id": "acct-12"}, {"resource_id": None, "identifiers": ["bad@"]},
            {"resource_id": None, "identifiers": []}, "junk"])
        self.assertEqual([r["resource_id"] for r in kept], ["account_12"])
        self.assertEqual(len(dropped), 4)


class CacheFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patch = mock.patch.object(config, "CACHE", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_text_and_rows_are_cached_and_reused(self):
        calls = []
        self.assertTrue(multimodal.process(EVIDENCE, formatter=fake_formatter(calls)).startswith("extracted 1 rows"))
        doc = json.loads((config.CACHE / "extracted/evidence_58.json").read_text())
        self.assertEqual(doc["payload"]["rows"][0]["resource_id"], "support_001")
        self.assertEqual(len(doc["payload"]["dropped"]), 2)
        self.assertTrue((config.CACHE / "text/evidence_58.json").exists())
        self.assertEqual(multimodal.process(EVIDENCE, formatter=fake_formatter(calls)), "cached")
        self.assertEqual(len(calls), 1)                      # second run made no LLM call

    def test_no_llm_caches_text_only(self):
        calls = []
        result = multimodal.process(EVIDENCE, use_llm=False, formatter=fake_formatter(calls))
        self.assertIn("skipped", result)
        self.assertEqual(calls, [])
        self.assertTrue(cache.load("text/evidence_58.json", cache.digest(
            PDF.read_bytes(), extract_text.extractor_version(PDF))))
        self.assertFalse((config.CACHE / "extracted/evidence_58.json").exists())

    def test_missing_api_key_is_reported(self):
        with mock.patch.object(llm, "settings", return_value={}):
            result = multimodal.process(EVIDENCE)
        self.assertIn("OPENROUTER_API_KEY", result)

    def test_changed_prompt_invalidates_rows_not_text(self):
        calls = []
        multimodal.process(EVIDENCE, formatter=fake_formatter(calls))
        with mock.patch.object(multimodal, "PROMPT_VERSION", "next"):
            multimodal.process(EVIDENCE, formatter=fake_formatter(calls))
        self.assertEqual(len(calls), 2)


class LLMParseTests(unittest.TestCase):
    def test_parse_json_object_tolerates_fences(self):
        self.assertEqual(llm.parse_json_object('```json\n{"rows": []}\n```'), {"rows": []})
        with self.assertRaises(ValueError):
            llm.parse_json_object("no json here")


if __name__ == "__main__":
    unittest.main()
