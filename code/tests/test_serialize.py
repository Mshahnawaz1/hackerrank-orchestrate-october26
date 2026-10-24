import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config, io, serialize  # noqa: E402


def step(phase, op, system, resource, evidence=""):
    return {"phase": phase, "operation": op, "state": config.OPERATIONS[op][1],
            "system_id": system, "resource_id": resource, "evidence_id": evidence}


class SerializeTests(unittest.TestCase):
    def test_sort_and_renumber(self):
        steps = [step("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_1"),
                 step("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_1", "evidence_1"),
                 step("REMEDIATION", "DELETE_RECORD", "search_service", "search_1")]
        out = json.loads(serialize.serialize_steps(steps))
        self.assertEqual([s["step_no"] for s in out], [1, 2, 3])
        self.assertEqual([s["phase"] for s in out], ["FINDING", "REMEDIATION", "VERIFICATION"])

    def test_validator_flags_bad_rows(self):
        bad = json.dumps([step("FINDING", "REPORT_REMAINING_RECORD", "a", "b")])  # no evidence, no step_no
        self.assertTrue(serialize.validate_row("c", "INCOMPLETE", bad))
        self.assertTrue(serialize.validate_row("c", "NOT_APPLICABLE", serialize.serialize_steps(
            [step("REMEDIATION", "DELETE_RECORD", "a", "b")])))
        self.assertTrue(serialize.validate_row("c", "MAYBE", "[]"))

    def test_gold_samples_are_valid_and_canonically_ordered(self):
        for row in io.read_csv(config.DATASET / "sample_output.csv"):
            self.assertEqual(serialize.validate_row(row["case_id"], row["deletion_status"], row["steps_json"]), [])
            steps = json.loads(row["steps_json"])
            self.assertEqual(serialize.sort_steps(steps), steps, row["case_id"])


if __name__ == "__main__":
    unittest.main()
