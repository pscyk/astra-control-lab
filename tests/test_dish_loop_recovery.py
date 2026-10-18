from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from resume_dish_loop import recover_cases


class DishLoopRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.plan = {"maximum_queue_seconds": 1000, "cases": [
            {"seed": seed, "reference": str(seed), "reference_sha256": str(seed), "status": "pending", "native_success": None}
            for seed in range(514001, 514201)]}
        self.previous = {"rows": deepcopy(self.plan["cases"]), "phase": "running", "started_unix": 100}

    def result(self, success):
        directory = self.output / "seed-514001"
        directory.mkdir()
        value = {"seed": 514001, "reference_sha256": "514001", "feedback_enabled": True,
                 "native_success": success, "new_LLM_calls": 4, "control_steps": 327}
        (directory / "result.json").write_text(json.dumps(value))

    def recover(self, now=300):
        return recover_cases(self.plan, self.output, self.previous, now, lambda path: json.loads(path.read_text()))

    def test_preserves_successes_and_failures_without_reexecution(self):
        for success in (False, True):
            with self.subTest(success=success):
                if (self.output / "seed-514001/result.json").exists():
                    (self.output / "seed-514001/result.json").unlink()
                    (self.output / "seed-514001").rmdir()
                self.result(success)
                recovered = self.recover()
                self.assertEqual(recovered["maximum_queue_seconds"], 800)
                self.assertEqual(recovered["cases"][0]["status"], "completed")
                self.assertIs(recovered["cases"][0]["native_success"], success)
                self.assertEqual(recovered["cases"][1]["status"], "pending")
                self.assertEqual(self.plan["cases"][0]["status"], "pending")

    def test_rejects_attempts_without_complete_results(self):
        (self.output / "seed-514001.log").touch()
        with self.assertRaisesRegex(ValueError, "cannot be replayed"):
            self.recover()

    def test_rejects_changed_assignment(self):
        self.previous["rows"][0]["reference_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "assignment changed"):
            self.recover()

    def test_does_not_reset_expired_deadline(self):
        with self.assertRaisesRegex(ValueError, "deadline"):
            self.recover(now=1100)

    def test_rejects_changed_recorded_result(self):
        self.result(False)
        self.previous["rows"][0].update(status="completed", native_success=False, sha256="changed")
        with self.assertRaisesRegex(ValueError, "recorded result changed"):
            self.recover()
