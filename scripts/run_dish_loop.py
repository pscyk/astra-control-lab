import argparse
from copy import deepcopy
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from astra_lab.dish_loop import call_allowance, phase_steps, remaining_command, summarize


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    from durable_results import write_json
    write_json(path, value, replace=Path(path).exists())


def prepare(harness, output):
    from molmo_pilot_05 import require_idle
    require_idle()
    output.mkdir(parents=True, exist_ok=False)
    source = harness / "placement327-confirmation-01/status.json"
    archived = json.loads(source.read_text())
    assert archived["protocol_finished"]
    cases = []
    for seed in range(514001, 514201):
        job = next(row for row in archived["jobs"] if row["seed"] == seed and row["kind"] == "proposal")
        reference = Path(job["result"])
        assert digest(reference) == job["sha256"]
        proposal = json.loads(reference.read_text())
        if not job["complete"]:
            assert job["unknown_reason"] == "model_timeout"
            status = "shared_model_deadline"
        else:
            status = "pending" if proposal["eligible"] else "shared_proposal_rejection"
        cases.append({"seed": seed, "reference": str(reference), "reference_sha256": digest(reference),
                      "status": status, "native_success": False if status == "shared_proposal_rejection" else None})
    plan = {"schema_version": 1, "registered_unix": time.time(), "task": "PlaceDishInRack-v1",
            "condition": "NONE", "max_control_steps": 327, "control_hz": 20,
            "model_alias": "gpt-6-astra", "maximum_feedback_calls": 4, "review_interval_steps": 64,
            "total_model_wait_budget_seconds": 720, "feedback_call_timeout_seconds": 180,
            "maximum_queue_seconds": 36 * 3600, "child_wall_seconds": 1200,
            "minimum_free_bytes": 1024 ** 3, "baseline_status_sha256": digest(source),
            "sources": {str(path): digest(path) for path in sorted(harness.glob("*.py"))},
            "implementation": {str(path): digest(path) for path in [Path(__file__), ROOT / "astra_lab/dish_loop.py"]},
            "cases": cases, "phase": "post_hoc_frozen_followup_not_untouched_test",
            "protocol": "Reuse every archived initial proposal and exact reset. Review RGB/calibration/robot state at steps 64,128,192,256; no privileged task state enters requests. Same native action caps and horizon; charge initial recorded model wait plus new feedback wait against 720 seconds. Keep pending actions after a model deadline or invalid response. Stop on native terminal success or failure. No training, scene replacement, outcome-based selection or retry.",
            "limits": "Follow-up after viewing the original study; not an untouched final test. Extra model calls use the remaining shared time budget. Immutable Astra backend identity is not attested across dates. Paused simulation during calls; not asynchronous or real-time control."}
    write(output / "protocol.json", plan)
    print(json.dumps({"plan_sha256": digest(output / "protocol.json"), "native_cases": sum(row["status"] == "pending" for row in cases)}), flush=True)


def verify(plan):
    for path, expected in (plan["sources"] | plan["implementation"]).items():
        if digest(path) != expected:
            raise ValueError(f"Registered source changed: {path}")


def episode(plan, case, output, feedback=True):
    import imageio.v2 as imageio
    import jsonschema
    import numpy as np
    from PIL import Image, ImageDraw
    import torch
    from astra_controller import validate
    from astra_trial_repair_02 import query
    from audit_molmo_coverage import compare_states
    from constrained_action_filter import capped_action
    from controller_runtime_02 import diagnostic_value
    from interface import array, single_arm_delta_action
    from interface_02 import observation_packet
    from molmo_pilot import native_outcome
    from native_runtime import make_env
    from official_horizon_control import decode_proposal
    from official_horizon_pilot_02 import verify_runtime
    from pilot import instruction

    output.mkdir(parents=True, exist_ok=False)
    result = {"seed": case["seed"], "task": plan["task"], "complete": False, "native_success": None,
              "feedback_enabled": feedback, "new_LLM_calls": 0, "feedback_wait_seconds": 0.0,
              "reference_sha256": case["reference_sha256"], "initial_state_exact": False,
              "native_steps": [], "history": [], "reviews": [], "parameter_updates": 0,
              "started_unix": time.time(), "privileged_state_in_policy": False}
    env = writer = diagnostics = None
    try:
        reference = Path(case["reference"])
        assert digest(reference) == case["reference_sha256"]
        source = json.loads(reference.read_text())
        assert source["complete"] and source["eligible"] and source["seed"] == case["seed"]
        initial_wait = json.loads((reference.parent / "call-00/wait.json").read_text())["seconds"]
        result["initial_model_wait_seconds"] = initial_wait
        env = make_env(plan["task"], num_envs=1, obs_mode="rgb", control_mode="pd_ee_delta_pose",
                       sim_backend="gpu", render_backend="gpu", perturbation_set="NONE",
                       render_mode="rgb_array", max_episode_steps=327)
        verify_runtime(env, 327)
        observation, info = env.reset(seed=case["seed"])
        packet = observation_packet(observation, bimanual=False)
        reset = {"robot": packet["robot"], "calibration": packet["calibration"]}
        assert json.loads(reference.with_name("reset.json").read_text()) == reset
        write(output / "reset.json", reset)
        for name, pixels in packet["images"].items():
            np.testing.assert_array_equal(pixels, np.asarray(Image.open(reference.with_name(name + ".png"))))
            Image.fromarray(pixels).save(output / (name + ".png"))
        with reference.with_name("offline-privileged.jsonl").open() as stream:
            original_state = json.loads(stream.readline())["state"]
        assert compare_states(original_state, diagnostic_value(env.unwrapped.get_state_dict()))["exact_match"]
        result["initial_state_exact"] = True
        diagnostics = gzip.open(output / "offline-privileged.jsonl.gz", "wt")

        def diagnostic(current_info):
            diagnostics.write(json.dumps({"control_step": len(result["native_steps"]), "policy_input": False,
                "info": diagnostic_value(current_info), "state": diagnostic_value(env.unwrapped.get_state_dict())}, allow_nan=False) + "\n")

        diagnostic(info)
        writer = imageio.get_writer(output / "execution.mp4", fps=20, macro_block_size=1)

        def frame(current):
            canvas = Image.new("RGB", (448, 264), "white")
            for index, name in enumerate(("external1_camera", "external2_camera")):
                canvas.paste(Image.fromarray(current["images"][name]), (224 * index, 0))
            drawing = ImageDraw.Draw(canvas)
            drawing.text((3, 226), f"seed {case['seed']} | action-observe | step {len(result['native_steps'])}/327", fill="black")
            drawing.text((3, 244), "20 Hz simulation; model wait omitted", fill="black")
            writer.append_data(np.asarray(canvas))

        frame(packet)
        pending, before = deepcopy(source["commands"]), packet
        assessment = json.loads((reference.parent / "call-00/response.json").read_text()).get("assessment", "")[:1600]
        success = done = False
        while pending and len(result["native_steps"]) < 327:
            if time.time() - result["started_unix"] > plan["child_wall_seconds"] - 30:
                raise TimeoutError("Native episode wall budget exceeded")
            command = pending.pop(0)
            robot_before = packet["robot"]
            duration = phase_steps(command, len(result["native_steps"]), feedback and result["new_LLM_calls"] < 4)
            count = 0
            for _ in range(duration):
                robot = packet["robot"]
                proposed = single_arm_delta_action(robot["tcp_poses_world_xyz_xyzw"][0], command["targets"][0],
                    robot["root_pose_world_xyz_xyzw"], gripper_open=command["grippers_open"][0])
                action = capped_action(proposed)
                observation, _, terminated, truncated, info = env.step(torch.tensor(action, device=env.unwrapped.device)[None])
                target = array(env.unwrapped.agent.controller.controllers["arm"]._target_qpos)[0]
                success, done = native_outcome(info, terminated, truncated)
                packet = observation_packet(observation, bimanual=False)
                result["native_steps"].append({"action": action.tolist(), "proposed_action": proposed.tolist(),
                    "actual_native_joint_target": target.tolist(), "robot_after": packet["robot"],
                    "native_success": success, "terminated_or_truncated": done})
                diagnostic(info)
                frame(packet)
                count += 1
                if success or done:
                    break
            result["history"].append({"command": command, "robot_before": robot_before,
                                      "robot_after": packet["robot"], "native_steps": count})
            if success or done:
                break
            leftover = remaining_command(command, count)
            if leftover:
                pending.insert(0, leftover)
            elapsed = len(result["native_steps"])
            allowance = call_allowance(initial_wait, result["feedback_wait_seconds"], result["new_LLM_calls"])
            stopped = False
            if feedback and elapsed < 327 and elapsed % 64 == 0 and allowance:
                result["new_LLM_calls"] += 1
                directory = output / f"call-{result['new_LLM_calls']:02d}"
                context = {"instruction": instruction(plan["task"]), "pending": pending,
                    "history": result["history"][-6:], "remaining_control_steps": 327 - elapsed,
                    "remaining_waypoint_commands": 25, "previous_assessment": assessment,
                    "last_error": "Scheduled action-observe review. Inspect current RGB and robot state; keep or revise the remaining actions within the remaining native step budget."}
                review = {"control_step": elapsed, "timeout_seconds": allowance, "status": "pending"}
                try:
                    response = query(before, packet, context, directory, timeout_seconds=allowance)
                    try:
                        validate(response, packet)
                        if response["decision"] != "keep":
                            replacement, rejection = decode_proposal(response, packet, 327 - elapsed)
                            pending = replacement
                            stopped = rejection == "model_abstained"
                        assessment = str(response.get("assessment", ""))[:1600]
                        review.update(status="completed", decision=response["decision"])
                    except (ValueError, jsonschema.ValidationError) as error:
                        review.update(status="invalid_response_keep_pending", error=str(error))
                except subprocess.TimeoutExpired:
                    review["status"] = "model_deadline_keep_pending"
                finally:
                    wait = json.loads((directory / "wait.json").read_text())
                    result["feedback_wait_seconds"] += wait["seconds"]
                    review["wait_seconds"] = wait["seconds"]
                    result["reviews"].append(review)
                before = packet
            if stopped:
                break
            if not pending and elapsed < 327:
                held = deepcopy(command)
                held["control_steps"] = min(40, 327 - elapsed)
                pending.append(held)
        result.update(complete=True, native_success=bool(success))
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if diagnostics is not None:
            diagnostics.close()
        if writer is not None:
            writer.close()
        if env is not None:
            env.close()
        result.update(control_steps=len(result["native_steps"]), completed_unix=time.time())
        result["artifacts"] = {str(path.relative_to(output)): digest(path) for path in output.rglob("*") if path.is_file()}
        write(output / "result.json", result)
    return result


def audit_episode(path):
    from interface import single_arm_delta_action
    from constrained_action_filter import capped_action
    import numpy as np
    result = json.loads(path.read_text())
    assert result["complete"] and result["initial_state_exact"] and result["parameter_updates"] == 0
    assert result["control_steps"] == len(result["native_steps"]) <= 327
    assert result["native_success"] == any(step["native_success"] for step in result["native_steps"])
    for name, expected in result["artifacts"].items():
        assert digest(path.parent / name) == expected
    with gzip.open(path.parent / "offline-privileged.jsonl.gz", "rt") as stream:
        diagnostics = [json.loads(line) for line in stream]
    assert len(diagnostics) == result["control_steps"] + 1
    robot = json.loads(path.with_name("reset.json").read_text())["robot"]
    cursor = 0
    for history in result["history"]:
        assert history["robot_before"] == robot
        for step in result["native_steps"][cursor:cursor + history["native_steps"]]:
            command = history["command"]
            proposed = single_arm_delta_action(robot["tcp_poses_world_xyz_xyzw"][0], command["targets"][0],
                robot["root_pose_world_xyz_xyzw"], gripper_open=command["grippers_open"][0])
            np.testing.assert_array_equal(proposed, step["proposed_action"])
            np.testing.assert_array_equal(capped_action(proposed), step["action"])
            cursor += 1
            assert bool(np.asarray(diagnostics[cursor]["info"]["success"]).item()) == step["native_success"]
            assert diagnostics[cursor]["policy_input"] is False
            robot = step["robot_after"]
        assert history["robot_after"] == robot
    assert cursor == result["control_steps"]
    used_wait = 0.0
    for index, review in enumerate(result["reviews"]):
        assert review["control_step"] == 64 * (index + 1)
        assert review["timeout_seconds"] == call_allowance(result["initial_model_wait_seconds"], used_wait, index)
        directory = path.parent / f"call-{index + 1:02d}"
        request = json.loads((directory / "request.json").read_text())
        assert request["requested_model"] == "gpt-6-astra"
        for name, expected in request["input_sha256"].items():
            assert digest(directory / name) == expected
        wait = json.loads((directory / "wait.json").read_text())
        if review["status"] == "model_deadline_keep_pending":
            assert wait["deadline_expired"]
        else:
            assert wait["returncode"] == 0 and not wait["deadline_expired"]
            events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
            assert sum(event["type"] == "turn.completed" for event in events) == 1
            assert all(event["item"]["type"] in ("agent_message", "reasoning") for event in events if "item" in event)
        used_wait += wait["seconds"]
    assert math.isclose(used_wait, result["feedback_wait_seconds"], abs_tol=1e-6)
    assert len(result["reviews"]) == result["new_LLM_calls"] <= 4
    return result


def publish(output, status, push=False):
    public = {"schema_version": 1, "status": "preliminary", "phase": status["phase"],
              "task": "PlaceDishInRack-v1", "updated_unix": time.time(), "started_unix": status["started_unix"],
              "protocol_sha256": digest(output / "protocol.json"), "review_interval_steps": 64,
              "maximum_feedback_calls": 4, "total_model_wait_budget_seconds": 720,
              "summary": summarize(status["rows"], status["phase"]),
              "outcomes": [{key: row.get(key) for key in ("seed", "status", "native_success", "sha256", "new_LLM_calls", "control_steps")} for row in status["rows"]],
              "limits": "Post-hoc follow-up on the same 200 scenes, not an untouched test. Shared initial model deadlines remain unknown physical outcomes. More calls within the remaining 720-second model wait budget; backend checkpoint identity across dates is not attested."}
    destination = ROOT / "docs/data/dish_loop.json"
    write(destination, public)
    manifest_path = ROOT / "docs/data/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = [row for row in manifest["files"] if row["path"] != "data/dish_loop.json"]
    manifest["files"].append({"path": "data/dish_loop.json", "sha256": digest(destination)})
    manifest["files"].sort(key=lambda row: row["path"])
    write(manifest_path, manifest)
    if push:
        changed = subprocess.check_output(["git", "-C", str(ROOT), "diff", "--name-only"], text=True).splitlines()
        allowed = {"docs/data/dish_loop.json", "docs/data/manifest.json"}
        if not set(changed) <= allowed or subprocess.check_output(["git", "-C", str(ROOT), "diff", "--cached", "--name-only"], text=True).strip():
            raise RuntimeError("Other repository edits present; result publication needs review")
        subprocess.run(["git", "-C", str(ROOT), "add", *sorted(allowed)], check=True)
        subprocess.run(["git", "-C", str(ROOT), "commit", "-m", f"Record dish action-observe run: {status['phase']}"], check=True)
        subprocess.run(["git", "-C", str(ROOT), "push", "origin", "main"], check=True)


def run(plan, output, push):
    from molmo_pilot_05 import require_idle
    from run_coverage_pilots import terminate
    from durable_results import sync_episode
    require_idle()
    status = {"phase": "running", "started_unix": time.time(), "rows": deepcopy(plan["cases"]), "active_seed": None}
    if (output / "status.json").exists():
        raise FileExistsError("This queue already started; no automatic replay")
    process = None
    try:
        write(output / "status.json", status)
        publish(output, status)
        for row in status["rows"]:
            if row["status"] != "pending":
                continue
            verify(plan)
            if shutil.disk_usage(output).free < plan["minimum_free_bytes"]:
                raise RuntimeError("Disk reserve exhausted; remaining scenes stay pending")
            if time.time() - status["started_unix"] > plan["maximum_queue_seconds"]:
                raise TimeoutError("Registered queue wall budget exhausted")
            status["active_seed"] = row["seed"]
            write(output / "status.json", status)
            command = [sys.executable, "-u", "-B", str(Path(__file__)), "--harness", str(Path(next(iter(plan["sources"]))).parent),
                       "--output", str(output), "--worker", str(row["seed"]), "--registration", digest(output / "protocol.json")]
            with (output / f"seed-{row['seed']}.log").open("x") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
                status["active_pid"] = process.pid
                write(output / "status.json", status)
                try:
                    process.wait(timeout=plan["child_wall_seconds"])
                except subprocess.TimeoutExpired:
                    terminate(process)
            path = output / f"seed-{row['seed']}/result.json"
            sync_episode(path.parent)
            if process.returncode or not path.exists():
                row["status"] = "infrastructure_error"
                raise RuntimeError(f"Seed {row['seed']} failed; inspect its log before any new run")
            result = audit_episode(path)
            row.update(status="completed", native_success=result["native_success"], sha256=digest(path),
                       new_LLM_calls=result["new_LLM_calls"], control_steps=result["control_steps"])
            process = None
            write(output / "status.json", status)
            print(json.dumps({"seed": row["seed"], "success": row["native_success"], "summary": summarize(status["rows"], status["phase"])}), flush=True)
        status["phase"] = "complete"
    except BaseException as error:
        status.update(phase="stopped", error=f"{type(error).__name__}: {error}")
    finally:
        terminate(process)
        status.update(active_seed=None, active_pid=None, completed_unix=time.time())
        write(output / "status.json", status)
        publish(output, status, push=push)
    return status["phase"] == "complete"


def main():
    parser = argparse.ArgumentParser(description="Registered action-observe follow-up using the original native harness.")
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--smoke", choices=("base", "feedback"))
    parser.add_argument("--worker", type=int)
    parser.add_argument("--registration")
    parser.add_argument("--publish-on-finish", action="store_true")
    args = parser.parse_args()
    args.harness, args.output = args.harness.resolve(), args.output.resolve()
    sys.path.insert(0, str(args.harness))
    if args.prepare:
        prepare(args.harness, args.output)
        return 0
    assert digest(args.output / "protocol.json") == args.registration
    plan = json.loads((args.output / "protocol.json").read_text())
    verify(plan)
    if args.smoke:
        reference = args.harness / "official-horizon-02/episodes/003--seed508201--proposal/result.json"
        case = {"seed": 508201, "reference": str(reference), "reference_sha256": digest(reference)}
        path = args.output / f"smoke-{args.smoke}"
        result = episode(plan, case, path, feedback=args.smoke == "feedback")
        audit_episode(path / "result.json")
        baseline = json.loads((args.harness / "placement327-01/episodes/000--seed508201--zero/result.json").read_text())
        count = min(64 if args.smoke == "feedback" else 327, result["control_steps"], baseline["control_steps"])
        for actual, expected in zip(result["native_steps"][:count], baseline["native_steps"][:count]):
            for key in ("action", "robot_after", "native_success", "terminated_or_truncated"):
                assert actual[key] == expected[key], key
        write(args.output / f"smoke-{args.smoke}-audit.json", {"complete": True, "matched_prefix_steps": count,
            "result_sha256": digest(path / "result.json"), "new_LLM_calls": result["new_LLM_calls"]})
        print(json.dumps({"smoke": args.smoke, "matched_steps": count, "new_LLM_calls": result["new_LLM_calls"]}), flush=True)
        return 0
    if args.worker is not None:
        case = next(row for row in plan["cases"] if row["seed"] == args.worker)
        result = episode(plan, case, args.output / f"seed-{args.worker}")
        return 0 if result["complete"] else 1
    for mode in ("base", "feedback"):
        assert json.loads((args.output / f"smoke-{mode}-audit.json").read_text())["complete"]
    from run_coverage_pilots import interrupted
    signal.signal(signal.SIGTERM, interrupted)
    with (args.harness / ".native-pilot.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return 0 if run(plan, args.output, args.publish_on_finish) else 1


if __name__ == "__main__":
    raise SystemExit(main())
