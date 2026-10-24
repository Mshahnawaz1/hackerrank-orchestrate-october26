import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import ingest  # noqa: E402
from agent.store import extract_identifiers  # noqa: E402


class IdentifierTests(unittest.TestCase):
    def test_normalizes_email_phone_hash_user(self):
        fields = {"email": "Choi.Jihoon94@GMAIL.COM", "phone": "+82 10-1234-5678",
                  "ref": "user_12", "h": "A" * 64, "integrity_seal": "sha256:" + "0" * 64}
        self.assertEqual(extract_identifiers(fields),
                         {"choi.jihoon94@gmail.com", "821012345678", "user_12", "a" * 64})


class IngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store, cls.counts = ingest.ingest_all()

    def test_every_text_file_parsed_images_pdfs_deferred(self):
        deferred = [f for f, n in self.counts.items() if n is None]
        self.assertEqual(len(deferred), 15)

    def test_observations_are_well_formed(self):
        for o in self.store.observations:
            self.assertTrue(o.system_id and o.resource_id and o.category)
        states = Counter(o.state for o in self.store.observations)
        self.assertGreater(states["ABSENT"], 0)
        self.assertGreater(states["ACTIVE"], 0)

    def test_replica_tables_are_separate_copies(self):
        copies = {o.copy for o in self.store.observations if o.source_kind == "sql"}
        self.assertIn("customer_data_read_replica", copies)
        self.assertIn("customer_data_primary", copies)


if __name__ == "__main__":
    unittest.main()
