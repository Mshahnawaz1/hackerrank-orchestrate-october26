import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config, io, pipeline  # noqa: E402
from evaluation.main import load, score  # noqa: E402


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = {r["case_id"]: r for r in io.load_requests(sample=True)}
        cls.ctx = pipeline.Context(list(cls.requests.values()))

    def solve(self, case_id):
        return pipeline.solve_case(self.requests[case_id], self.ctx)

    def steps(self, case_id):
        return {(s["operation"], s["resource_id"], s["evidence_id"])
                for s in json.loads(self.solve(case_id).row["steps_json"])}

    def test_identity_includes_history(self):
        ident = self.ctx.identities["case_12"]
        self.assertEqual(ident.user_id, "user_12")
        self.assertIn("minjun.kim90@gmail.com", ident.emails)
        self.assertIn("44a65154bfd8e408852578fbd76813d094d1944f255ac1769ee81ba90492f10e", ident.hashes)

    def test_replica_drift_keeps_record_present(self):
        self.assertIn(("REPORT_REMAINING_RECORD", "account_005", "evidence_54"), self.steps("case_05"))

    def test_absence_by_omission_is_cited(self):
        self.assertEqual(self.steps("case_01"), {("VERIFY_RECORD_ABSENT", "account_001", "evidence_54")})

    def test_later_evidence_is_ignored(self):
        # backup_4978 is also in evidence_06, captured after audit_at; the finding cites evidence_93
        self.assertIn(("REPORT_RESTORE_RISK", "backup_4978", "evidence_93"), self.steps("case_09"))

    def test_tombstone_keeps_reference_but_not_pii(self):
        self.assertIn(("REPORT_EXPOSED_PII", "tombstone_9178", "evidence_51"), self.steps("case_32"))
        self.assertIn(("VERIFY_RECORD_REDACTED", "tombstone_440", "evidence_51"), self.steps("case_31"))

    def test_decoy_email_not_linked(self):
        self.assertNotIn("search_8168", self.solve("case_28").case.resource_ids)   # smartinez6461.jr@...

    def test_sample_scores_meet_prd_floor(self):
        rows = pipeline.run(list(self.requests.values()), self.ctx)
        pred = {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in rows}
        metrics = score(pred, load(config.DATASET / "sample_output.csv"))
        self.assertGreaterEqual(metrics["status_accuracy"], 0.9)
        self.assertGreaterEqual(metrics["step_f1"], 0.9)


if __name__ == "__main__":
    unittest.main()
