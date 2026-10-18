from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_lab import evidence
from astra_lab.feedback import feedback_reason, phase_length
from astra_lab.residual import parameters, policy_update, refine


class EvidenceTests(unittest.TestCase):
    def test_all_assignments_and_missingness(self):
        data = evidence.load()
        self.assertEqual(len(data["outcomes"]), 600)
        summary = evidence.summarize(data)
        self.assertEqual([row["successes"] for row in summary], [21, 70, 58])
        self.assertEqual([row["physical_outcomes_unknown"] for row in summary], [34, 34, 34])
        self.assertEqual(sum(row["native_execution"] for row in data["outcomes"]), 495)

    def test_paired_wins_and_regressions(self):
        self.assertEqual(evidence.paired(evidence.load()), {
            "known_pairs": 166, "RL_wins": 53, "RL_losses": 4, "budgeted_delta_pp": 24.5})
        self.assertEqual(evidence.paired(evidence.load(), "random_search")["RL_wins"], 16)
        with self.assertRaises(ValueError):
            evidence.paired(evidence.load(), "unregistered")

    def test_wilson_interval_and_edges(self):
        lower, upper = evidence.wilson(70, 200)
        self.assertAlmostEqual(lower, .28728824127358077)
        self.assertAlmostEqual(upper, .4183653566395992)
        self.assertAlmostEqual(evidence.wilson(0, 200)[0], 0)
        self.assertAlmostEqual(evidence.wilson(200, 200)[1], 1)
        for successes, trials in [(1, 0), (3, 2), (-1, 5), (True, 5)]:
            with self.assertRaises(ValueError):
                evidence.wilson(successes, trials)

    def test_manifest(self):
        self.assertEqual(evidence.verify(), 20)

    def test_recordings_grouped_by_task(self):
        gallery = json.loads((evidence.DATA / "cases.json").read_text())
        self.assertEqual(gallery["tasks"], [
            {"id": "PlaceDishInRack-v1", "label": "Dish placement"},
            {"id": "OpenDrawer", "label": "Open drawer"}])
        expected = {"PlaceDishInRack-v1": ["overview", "514006", "514024", "514019"],
                    "OpenDrawer": ["drawer", "authored"]}
        self.assertEqual({case["task"] for case in gallery["cases"]}, set(expected))
        for task, case_ids in expected.items():
            self.assertEqual([case["id"] for case in gallery["cases"] if case["task"] == task], case_ids)
            self.assertTrue(all(task in case["study"] for case in gallery["cases"] if case["task"] == task))

    def test_four_method_overview(self):
        gallery = json.loads((evidence.DATA / "cases.json").read_text())
        self.assertEqual(len(gallery["cases"]), 6)
        overview = gallery["cases"][0]
        self.assertEqual(overview["id"], "overview")
        self.assertEqual(len(overview["tracks"]), 4)
        self.assertNotIn("scope_notice", overview)
        self.assertEqual(overview["seed"], 514006)
        self.assertEqual({track["seed"] for track in overview["tracks"]}, {514006})
        self.assertEqual({track["task"] for track in overview["tracks"]}, {"PlaceDishInRack-v1"})
        self.assertEqual(len({track["reference_sha256"] for track in overview["tracks"]}), 1)
        self.assertTrue(all(track["initial_state_verified"] and not track["privileged_state"] for track in overview["tracks"]))
        self.assertEqual([track["mode"] for track in overview["tracks"]], ["zero", "action_observe", "random_search", "astra_RL"])
        self.assertEqual([track["feedback_calls"] for track in overview["tracks"]], [0, 4, 0, 0])
        loop = json.loads((evidence.DATA / "dish_loop.json").read_text())
        loop_row = next(row for row in loop["outcomes"] if row["seed"] == 514006)
        self.assertEqual(overview["tracks"][1]["result_sha256"], loop_row["sha256"])
        for track in overview["tracks"]:
            row = loop_row if track["mode"] == "action_observe" else next(
                row for row in evidence.load()["outcomes"] if row["seed"] == 514006 and row["mode"] == track["mode"])
            self.assertEqual(track["success"], row["native_success"])
            self.assertEqual(track["result_sha256"], row.get("source_sha256", row.get("sha256")))
        self.assertEqual(overview["tracks"][0]["video"], gallery["cases"][1]["tracks"][0]["video"])
        self.assertEqual(overview["tracks"][3]["video"], gallery["cases"][1]["tracks"][1]["video"])
        authored = gallery["cases"][-1]
        self.assertEqual(authored["id"], "authored")
        self.assertEqual(len(authored["tracks"]), 1)
        self.assertTrue(authored["tracks"][0]["privileged_state"])
        self.assertAlmostEqual(authored["tracks"][0]["playback_end_seconds"], 113 / 30)
        self.assertAlmostEqual(gallery["cases"][4]["tracks"][1]["playback_end_seconds"], 180 / 30)
        for case in gallery["cases"]:
            for track in case["tracks"]:
                video = evidence.ROOT / "docs" / track["video"]
                self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(), track["source_sha256"])
                self.assertTrue((evidence.ROOT / "docs" / track["poster"]).is_file())

    def test_authored_controller_records(self):
        teacher = json.loads((evidence.DATA / "teacher.json").read_text())
        self.assertTrue(teacher["privileged_state"])
        self.assertEqual(teacher["runtime_LLM_calls"], 0)
        self.assertEqual(len(teacher["cases"]), 15)
        self.assertEqual({(row["seed"], row["variation"]) for row in teacher["cases"]},
                         {(seed, variation) for seed in range(9400, 9405) for variation in range(3)})
        self.assertTrue(all(row["native_success"] for row in teacher["cases"]))
        self.assertEqual(sum(row["commands"] for row in teacher["cases"]), 120)
        controller = evidence.ROOT / "reference/authored_drawer.py"
        self.assertEqual(hashlib.sha256(controller.read_bytes()).hexdigest(), teacher["controller_sha256"])

    def test_bad_study_rejected(self):
        data = evidence.load()
        duplicate = deepcopy(data)
        duplicate["outcomes"][-1] = duplicate["outcomes"][0]
        wrong_unknown = deepcopy(data)
        next(row for row in wrong_unknown["outcomes"] if not row["known"])["native_success"] = False
        for invalid in [duplicate, wrong_unknown]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "study.json").write_text(json.dumps(invalid))
                with patch.object(evidence, "DATA", path), self.assertRaises(ValueError):
                    evidence.load()

    def test_manifest_rejects_escape_and_tamper(self):
        for filename, digest in [("../outside.json", "0" * 64), ("/outside.json", "0" * 64), ("data/item.json", "0" * 64)]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data = root / "docs/data"
                data.mkdir(parents=True)
                (data / "item.json").write_text("{}")
                (data / "manifest.json").write_text(json.dumps({"files": [{"path": filename, "sha256": digest}]}))
                with patch.object(evidence, "ROOT", root), patch.object(evidence, "DATA", data), self.assertRaises(ValueError):
                    evidence.verify()


class ResidualTests(unittest.TestCase):
    def setUp(self):
        self.commands = json.loads((evidence.DATA / "trajectory.json").read_text())["commands"]
        self.training = json.loads((evidence.DATA / "training.json").read_text())

    def test_recorded_updates(self):
        center = [0., 0., 0.]
        for batch in self.training["updates"]:
            for actual, expected in zip(center, batch["mean_before"]):
                self.assertAlmostEqual(actual, expected, places=12)
            center = policy_update(center, batch["samples"], batch["returns"], batch["sigma"], batch["step_size"])
            for actual, expected in zip(center, batch["mean_after"]):
                self.assertAlmostEqual(actual, expected, places=12)
        for actual, expected in zip(center, self.training["mean"]):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_zero_residual_preserves_base(self):
        corrected, details = refine(self.commands, [0, 0, 0])
        self.assertEqual(corrected, self.commands)
        self.assertTrue(details["modified_command_indices"])

    def test_bounded_pure_transform(self):
        before = deepcopy(self.commands)
        corrected, details = refine(self.commands, self.training["mean"])
        self.assertEqual(before, self.commands)
        self.assertTrue(details["modified_command_indices"])
        for index, (original, changed) in enumerate(zip(self.commands, corrected)):
            self.assertEqual(original["control_steps"], changed["control_steps"])
            self.assertEqual(original["grippers_open"], changed["grippers_open"])
            self.assertEqual(original["targets"][0][0], changed["targets"][0][0])
            self.assertAlmostEqual(sum(value * value for value in changed["targets"][0][3:]), 1)
            if index not in details["modified_command_indices"]:
                self.assertEqual(original, changed)
            else:
                self.assertAlmostEqual(changed["targets"][0][1] - original["targets"][0][1], details["world_y_offset_m"])
                self.assertAlmostEqual(changed["targets"][0][2] - original["targets"][0][2], details["world_z_offset_m"])
        for value, limit in zip(parameters([1000, -1000, 1000]), [.7, .08, .08]):
            self.assertLessEqual(abs(value), limit)

    def test_malformed_commands(self):
        for key, value in [("targets", [[0] * 7]), ("grippers_open", [1]), ("control_steps", True)]:
            commands = deepcopy(self.commands)
            commands[0][key] = value
            with self.assertRaises(ValueError):
                refine(commands, [0, 0, 0])
        for latent in [[0, 0], [0, math.nan, 0], [True, 0, 0]]:
            with self.assertRaises(ValueError):
                parameters(latent)

    def test_invalid_training_batch(self):
        for rewards in [[0], [0, 2], [0, float("nan")]]:
            with self.assertRaises(ValueError):
                policy_update([0, 0, 0], [[0, 0, 0], [1, 1, 1]], rewards)
        self.assertEqual(policy_update([0, 0, 0], [[0, 0, 0], [1, 1, 1]], [1, 1]), [0, 0, 0])


class FeedbackTests(unittest.TestCase):
    def test_phase_caps_and_transitions(self):
        opened = [{"gripper_open": True}] * 5
        closed = [{"gripper_open": False}] * 5
        self.assertEqual(phase_length(opened, True), 3)
        self.assertEqual(phase_length(closed, False), 1)
        self.assertEqual(phase_length(opened[:1] + closed, True), 2)
        self.assertEqual(phase_length([], True), 0)
        with self.assertRaises(ValueError):
            phase_length([{"gripper_open": 1}], True)

    def test_native_success_precedes_warning(self):
        self.assertEqual(feedback_reason(True, True, "tracking"), "native_success")
        self.assertEqual(feedback_reason(False, True, "tracking"), "native_terminal_failure")
        self.assertEqual(feedback_reason(False, False, "tracking"), "tracking")

    def test_feedback_result_counts(self):
        feedback = json.loads((evidence.DATA / "feedback.json").read_text())
        self.assertEqual(feedback["parameter_updates"], 0)
        self.assertEqual(feedback["new_LLM_calls"], 71)
        for mode, expected in [("oneshot", 1), ("feedback", 2)]:
            rows = [row for row in feedback["rows"] if row["cohort"] == "fresh_development" and row["mode"] == mode]
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(row["success"] for row in rows), expected)


if __name__ == "__main__":
    unittest.main()
