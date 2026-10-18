import argparse
from collections import Counter
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

import run_dish_loop as runner
from resume_dish_loop import capacity_failure, recover_cases, require_dead

BACKOFF_SECONDS = (60, 180, 300)


def push_results(phase):
    allowed = {"docs/data/dish_loop.json", "docs/data/manifest.json"}
    command = ["git", "-C", str(runner.ROOT)]
    changed = subprocess.check_output(command + ["diff", "--name-only"], text=True).splitlines()
    if not set(changed) <= allowed or subprocess.check_output(command + ["diff", "--cached", "--name-only"], text=True).strip():
        raise RuntimeError("Other repository edits present; publication needs review")
    subprocess.run(command + ["add", *sorted(allowed)], check=True)
    subprocess.run(command + ["commit", "-m", f"Record capacity-amended dish run: {phase}"], check=True)
    subprocess.run(command + ["push", "origin", "main"], check=True)


def recovery_metadata(amendment, receipts, status):
    retried = {item["seed"] for item in receipts}
    return {"amendment": "user_authorized_capacity_only_retries_2026_10_19",
            "authorized_unix": amendment["authorized_unix"],
            "maximum_retries_per_scene": len(BACKOFF_SECONDS),
            "backoff_seconds": list(BACKOFF_SECONDS), "failed_attempts": receipts,
            "interrupted_scenes": len(retried),
            "successes_without_retried_scenes": sum(row["native_success"] is True and row["seed"] not in retried for row in status["rows"]),
            "attempt_limits_unchanged": True, "extra_attempt_cost_excluded_from_original_attempt_budget": True}


def main():
    parser = argparse.ArgumentParser(description="User-authorized bounded retries for Astra capacity failures only.")
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--publish-on-finish", action="store_true")
    args = parser.parse_args()
    args.harness, args.output = args.harness.resolve(), args.output.resolve()
    sys.path.insert(0, str(args.harness))
    from molmo_pilot_05 import require_idle
    from run_coverage_pilots import interrupted

    signal.signal(signal.SIGTERM, interrupted)
    with (args.harness / ".native-pilot.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_idle()
        if runner.digest(args.output / "protocol.json") != args.registration:
            raise ValueError("Protocol hash mismatch")
        plan = json.loads((args.output / "protocol.json").read_text())
        runner.verify(plan)
        previous = json.loads((args.output / "status.json").read_text())
        if previous.get("active_pid"):
            require_dead(previous["active_pid"])
        deadline = json.loads((args.output / "recovery.json").read_text())["original_deadline_unix"]
        directory = args.output / "capacity-recovery"
        directory.mkdir(exist_ok=False)
        amendment = {"authorized_unix": time.time(), "authorization": "User: bruh, retry and continue",
            "protocol_sha256": args.registration, "original_deadline_unix": deadline,
            "source_hashes": {str(path): runner.digest(path) for path in (Path(__file__), Path(__file__).with_name("resume_dish_loop.py"))},
            "maximum_retries_per_scene": len(BACKOFF_SECONDS), "backoff_seconds": list(BACKOFF_SECONDS),
            "policy": "Retry only incomplete episodes ending in the exact Astra capacity error. Retain every failed attempt and original status. Never retry a completed task failure or success. Accept the first completed retry irrespective of outcome. Keep all 200 assignments, original initial proposals, policy code, and per-attempt limits. Extra attempts add cost and break the original no-retry protocol."}
        runner.write(directory / "amendment.json", amendment)
        receipts = []
        original_publish = runner.publish

        def publish(output, status, push=False):
            original_publish(output, status, push=False)
            destination = runner.ROOT / "docs/data/dish_loop.json"
            public = json.loads(destination.read_text())
            public["capacity_recovery"] = recovery_metadata(amendment, receipts, status)
            public["limits"] += " User-authorized capacity-only episode retries add attempts and cost; this is not the original no-retry comparison. Interrupted attempts are retained in capacity_recovery."
            runner.write(destination, public)
            manifest_path = runner.ROOT / "docs/data/manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for item in manifest["files"]:
                if item["path"] == "data/dish_loop.json":
                    item["sha256"] = runner.digest(destination)
            runner.write(manifest_path, manifest)
            if push:
                push_results(status["phase"])

        runner.publish = publish
        try:
            while previous["phase"] != "complete":
                for path, expected in amendment["source_hashes"].items():
                    if runner.digest(path) != expected:
                        raise ValueError("Recovery implementation changed during execution")
                interrupted_rows = [row for row in previous["rows"] if row["status"] == "infrastructure_error"]
                if len(interrupted_rows) != 1:
                    raise ValueError("Expected one capacity-interrupted episode")
                case = interrupted_rows[0]
                retries = Counter(item["seed"] for item in receipts)[case["seed"]]
                if retries >= len(BACKOFF_SECONDS):
                    raise RuntimeError("Capacity retry limit reached; no completed outcome discarded")
                previous_for_audit = deepcopy(previous)
                previous_for_audit["started_unix"] = deadline - plan["maximum_queue_seconds"]
                recovered = recover_cases(plan, args.output, previous_for_audit, time.time(), allow_capacity_retries=True)
                result_path = args.output / f"seed-{case['seed']}/result.json"
                failed = capacity_failure(result_path, case)
                receipt = {"seed": case["seed"], "attempt": retries + 1, "sha256": runner.digest(result_path),
                    "native_success": None, "reason": "model_capacity", "control_steps": failed["control_steps"],
                    "new_LLM_calls": failed["new_LLM_calls"], "feedback_wait_seconds": failed["feedback_wait_seconds"],
                    "attempt_wall_seconds": failed["completed_unix"] - failed["started_unix"],
                    "original_status_sha256": runner.digest(args.output / "status.json")}
                archive = directory / f"seed-{case['seed']}-attempt-{retries + 1:02d}"
                archive.mkdir(exist_ok=False)
                runner.write(archive / "receipt.json", receipt)
                result_path.parent.rename(archive / "episode")
                (args.output / f"seed-{case['seed']}.log").rename(archive / "worker.log")
                (args.output / "status.json").rename(archive / "status.json")
                receipts.append(receipt)
                runner.write(directory / "attempts.json", receipts)
                waiting = {"phase": "running", "started_unix": time.time(), "rows": recovered["cases"],
                           "active_seed": None, "active_pid": None, "capacity_backoff_seconds": BACKOFF_SECONDS[retries]}
                runner.write(args.output / "status.json", waiting)
                publish(args.output, waiting)
                print(json.dumps({"capacity_retry": case["seed"], "retry": retries + 1, "wait_seconds": BACKOFF_SECONDS[retries]}), flush=True)
                time.sleep(BACKOFF_SECONDS[retries])
                recovered["maximum_queue_seconds"] = deadline - time.time() - 1
                if recovered["maximum_queue_seconds"] <= 0:
                    raise TimeoutError("Original queue deadline expired")
                (args.output / "status.json").rename(archive / "backoff-status.json")
                runner.run(recovered, args.output, push=False)
                previous = json.loads((args.output / "status.json").read_text())
        except BaseException as error:
            if (args.output / "status.json").exists():
                previous = json.loads((args.output / "status.json").read_text())
            previous.update(phase="stopped", error=f"{type(error).__name__}: {error}", active_seed=None, active_pid=None, completed_unix=time.time())
            runner.write(args.output / "status.json", previous)
        finally:
            publish(args.output, previous, push=args.publish_on_finish)
        return 0 if previous["phase"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
