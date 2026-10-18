from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from resume_dish_loop import capacity_failure, recover_cases
from retry_dish_loop import recovery_metadata
from run_dish_loop import digest


class CapacityRetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.case = {"seed": 514156, "reference": "reference", "reference_sha256": "hash", "status": "pending", "native_success": None}
        self.directory = self.output / "seed-514156"
        call = self.directory / "call-02"
        call.mkdir(parents=True)
        self.wait = call / "wait.json"
        self.wait.write_text(json.dumps({"returncode": 1, "deadline_expired": False}))
        self.events = call / "events.jsonl"
        self.events.write_text(json.dumps({"type": "turn.failed", "error": {"message": "Selected model is at capacity. Please try a different model."}}))
        self.result = {"seed": 514156, "reference_sha256": "hash", "complete": False, "native_success": None,
                       "initial_state_exact": True, "parameter_updates": 0, "new_LLM_calls": 2, "native_steps": [],
                       "error": "RuntimeError: Astra transport failed: 1; no retry"}
        self.path = self.directory / "result.json"

    def save(self):
        self.result["artifacts"] = {str(path.relative_to(self.directory)): digest(path) for path in (self.wait, self.events)}
        self.path.write_text(json.dumps(self.result))

    def test_capacity_error_is_retryable(self):
        self.save()
        self.assertIsNone(capacity_failure(self.path, self.case)["native_success"])

    def test_completed_task_failure_is_never_retryable(self):
        self.result.update(complete=True, native_success=False)
        self.save()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            capacity_failure(self.path, self.case)

    def test_other_transport_error_is_not_retryable(self):
        self.events.write_text(json.dumps({"type": "turn.failed", "error": {"message": "Authentication failed"}}))
        self.save()
        with self.assertRaisesRegex(ValueError, "approved capacity"):
            capacity_failure(self.path, self.case)

    def test_altered_artifacts_are_rejected(self):
        self.save()
        self.events.write_text("changed")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            capacity_failure(self.path, self.case)

    def test_recovery_requires_explicit_retry_flag(self):
        self.save()
        cases = [dict(self.case, seed=seed, status="shared_model_deadline") for seed in range(514001, 514201)]
        cases[155] = deepcopy(self.case)
        previous = {"phase": "stopped", "started_unix": 100, "rows": deepcopy(cases)}
        previous["rows"][155]["status"] = "infrastructure_error"
        plan = {"maximum_queue_seconds": 1000, "cases": cases}
        with self.assertRaisesRegex(ValueError, "separate investigation"):
            recover_cases(plan, self.output, previous, 200)
        recovered = recover_cases(plan, self.output, previous, 200, allow_capacity_retries=True)
        self.assertEqual(recovered["cases"][155]["status"], "pending")
        self.assertTrue(self.path.exists())

    def test_metadata_separates_retry_successes_and_cost(self):
        receipts = [{"seed": 514156, "control_steps": 128, "new_LLM_calls": 2}]
        status = {"rows": [{"seed": 514001, "native_success": True}, {"seed": 514156, "native_success": True}]}
        metadata = recovery_metadata({"authorized_unix": 123}, receipts, status)
        self.assertEqual(metadata["successes_without_retried_scenes"], 1)
        self.assertEqual(metadata["maximum_retries_per_scene"], 3)
        self.assertEqual(metadata["failed_attempts"], receipts)
