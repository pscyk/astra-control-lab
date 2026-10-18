import unittest

from astra_lab.dish_loop import call_allowance, phase_steps, remaining_command, summarize


class DishLoopTests(unittest.TestCase):
    def test_calls_charge_initial_wait_and_respect_both_caps(self):
        self.assertEqual(call_allowance(45, 0, 0), 180)
        self.assertEqual(call_allowance(45, 600, 3), 75)
        self.assertEqual(call_allowance(45, 676, 3), 0)
        self.assertEqual(call_allowance(0, 0, 4), 0)
        self.assertEqual(call_allowance(719.5, 0, 0), 0)
        for values in [(float("nan"), 0, 0), (-1, 0, 0), (0, 0, True)]:
            with self.assertRaises(ValueError):
                call_allowance(*values)

    def test_review_boundaries_preserve_command_remainder(self):
        command = {"control_steps": 40, "grippers_open": [False], "targets": [[1, 2, 3]]}
        self.assertEqual(phase_steps(command, 50), 14)
        self.assertEqual(phase_steps(command, 50, False), 40)
        self.assertEqual(phase_steps(command, 320, False), 7)
        remainder = remaining_command(command, 14)
        self.assertEqual(remainder["control_steps"], 26)
        self.assertEqual(remainder["grippers_open"], [False])
        self.assertEqual(command["control_steps"], 40)
        self.assertIsNone(remaining_command(command, 40))

    def test_incomplete_run_cannot_report_percentage(self):
        rows = [{"seed": seed, "status": "pending", "native_success": None} for seed in range(514001, 514201)]
        rows[0].update(status="completed", native_success=True)
        self.assertIsNone(summarize(rows, "running")["budgeted_rate"])
        with self.assertRaises(ValueError):
            summarize(rows, "complete")
        rows[1].update(status="shared_model_deadline", native_success=False)
        with self.assertRaises(ValueError):
            summarize(rows, "running")

    def test_complete_denominator_retains_shared_deadlines(self):
        rows = [{"seed": seed, "status": "completed", "native_success": True} for seed in range(514001, 514201)]
        rows[0].update(status="shared_model_deadline", native_success=None)
        rows[1].update(status="shared_proposal_rejection", native_success=False)
        self.assertEqual(summarize(rows, "complete")["budgeted_rate"], 198 / 200)
        with self.assertRaises(ValueError):
            summarize(rows + rows[:1], "complete")


if __name__ == "__main__":
    unittest.main()
