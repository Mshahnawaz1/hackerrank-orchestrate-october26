import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import cache, ingest, intent, io  # noqa: E402


class IngestCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fresh, cls.fresh_counts = ingest.ingest_all(use_cache=False)
        cls.cached, cls.cached_counts = ingest.ingest_all(use_cache=True)

    def test_round_trip_is_lossless(self):
        self.assertEqual(self.fresh.to_dict(), self.cached.to_dict())
        self.assertEqual(self.fresh_counts, self.cached_counts)
        self.assertEqual(len(self.fresh.by_identifier("keiko.nakamura@gmail.com")),
                         len(self.cached.by_identifier("keiko.nakamura@gmail.com")))

    def test_stale_fingerprint_is_rejected(self):
        self.assertIsNone(cache.load(ingest.CACHE_NAME, "not-the-fingerprint"))

    def test_coverage_records_absence_by_omission(self):
        def covers(evidence_id, system):
            return [c for c in self.cached.coverage if c.evidence_id == evidence_id and c.system_id == system]
        failover = covers("evidence_54", "account_service")             # replica lists other accounts
        self.assertTrue(failover and all("account_001" not in c.resource_ids for c in failover))
        self.assertIn([], [sorted(c.resource_ids) for c in covers("evidence_51", "account_service")])
        self.assertEqual([sorted(c.resource_ids) for c in covers("evidence_90", "account_service")], [[]])


class IntentCacheTests(unittest.TestCase):
    def test_cached_results_match_rules_for_every_request(self):
        texts = [r["request_text"] for r in io.load_requests() + io.load_requests(sample=True)]
        results = intent.classify_cached(texts)
        self.assertEqual(len(results), len(set(texts)))
        for text in set(texts):
            self.assertEqual(results[text], intent.classify(text))
        entries = cache.load(intent.CACHE_NAME)
        self.assertTrue(all(e["version"] == intent.RULES_VERSION for e in entries.values()))


if __name__ == "__main__":
    unittest.main()
