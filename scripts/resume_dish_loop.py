import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time

from run_dish_loop import audit_episode, digest, run, summarize, verify, write


def capacity_failure(path, case):
    result = json.loads(path.read_text())
    if (result["complete"] or result["native_success"] is not None
            or result["seed"] != case["seed"] or result["reference_sha256"] != case["reference_sha256"]
            or not result["initial_state_exact"] or result["parameter_updates"] != 0
            or result.get("error") != "RuntimeError: Astra transport failed: 1; no retry"
            or any(step["native_success"] or step["terminated_or_truncated"] for step in result["native_steps"])):
        raise ValueError("Only an incomplete capacity-error episode can be retried")
    for name, expected in result["artifacts"].items():
        if digest(path.parent / name) != expected:
            raise ValueError("Interrupted episode artifact changed")
    directory = path.parent / f"call-{result['new_LLM_calls']:02d}"
    wait = json.loads((directory / "wait.json").read_text())
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    message = "Selected model is at capacity. Please try a different model."
    if (wait["returncode"] != 1 or wait["deadline_expired"]
            or not any(event.get("type") == "turn.failed" and event.get("error", {}).get("message") == message for event in events)
            or any(event.get("type") not in ("thread.started", "turn.started", "error", "turn.failed") for event in events)
            or any(event.get("message") != message for event in events if event.get("type") == "error")):
        raise ValueError("Transport error is not the approved capacity failure")
    return result


def recover_cases(plan, output, previous, now, auditor=audit_episode, allow_capacity_retries=False):
    summarize(previous["rows"], previous["phase"])
    if previous["phase"] == "complete":
        raise ValueError("A completed queue cannot resume")
    recovered = deepcopy(plan)
    recovered["maximum_queue_seconds"] -= now - previous["started_unix"]
    if not 0 < recovered["maximum_queue_seconds"] <= plan["maximum_queue_seconds"]:
        raise ValueError("The original queue deadline has expired or the clock moved backwards")
    old_rows = {row["seed"]: row for row in previous["rows"]}
    for row in recovered["cases"]:
        old = old_rows[row["seed"]]
        for key in ("seed", "reference", "reference_sha256"):
            if row[key] != old[key]:
                raise ValueError(f"Archived assignment changed: {row['seed']}")
        directory = output / f"seed-{row['seed']}"
        result_path = directory / "result.json"
        if row["status"] != "pending":
            if old != row or directory.exists():
                raise ValueError("An inherited deadline or rejection was changed")
            continue
        if allow_capacity_retries and old["status"] == "infrastructure_error":
            capacity_failure(result_path, row)
            continue
        if old["status"] not in ("pending", "completed"):
            raise ValueError("A failed assignment needs a separate investigation, not a retry")
        if not result_path.exists():
            if directory.exists() or (output / f"seed-{row['seed']}.log").exists() or old["status"] != "pending":
                raise ValueError(f"Incomplete attempted episode cannot be replayed: {row['seed']}")
            continue
        result = auditor(result_path)
        if (result["seed"] != row["seed"] or result["reference_sha256"] != row["reference_sha256"]
                or result["feedback_enabled"] is not True or type(result["native_success"]) is not bool):
            raise ValueError("Audited result does not match its registered assignment")
        checksum = digest(result_path)
        if old["status"] == "completed" and old["sha256"] != checksum:
            raise ValueError("A previously recorded result changed")
        row.update(status="completed", native_success=result["native_success"], sha256=checksum,
                   new_LLM_calls=result["new_LLM_calls"], control_steps=result["control_steps"])
    return recovered


def require_dead(process_id):
    try:
        os.kill(int(process_id), 0)
    except ProcessLookupError:
        return
    raise RuntimeError(f"Recorded process {process_id} still exists; refusing concurrent recovery")


def main():
    parser = argparse.ArgumentParser(description="Continue only unattempted scenes after auditing a stopped supervisor.")
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
        if digest(args.output / "protocol.json") != args.registration:
            raise ValueError("Protocol hash mismatch")
        plan = json.loads((args.output / "protocol.json").read_text())
        verify(plan)
        for mode in ("base", "feedback"):
            audit = json.loads((args.output / f"smoke-{mode}-audit.json").read_text())
            if not audit["complete"] or digest(args.output / f"smoke-{mode}/result.json") != audit["result_sha256"]:
                raise ValueError("Smoke audit changed")
        status_path = args.output / "status.json"
        previous = json.loads(status_path.read_text())
        supervisor_path = args.output / "supervisor.pid"
        old_supervisor = int(supervisor_path.read_text()) if supervisor_path.exists() else None
        for process_id in (old_supervisor, previous.get("active_pid")):
            if process_id:
                require_dead(process_id)
        now = time.time()
        recovered = recover_cases(plan, args.output, previous, now)
        receipt_path = args.output / "recovery.json"
        archived_status = args.output / "interrupted-status.json"
        if receipt_path.exists() or archived_status.exists():
            raise FileExistsError("Recovery already attempted; inspect it rather than replaying")
        write(receipt_path, {"recovered_unix": now, "original_started_unix": previous["started_unix"],
            "original_deadline_unix": previous["started_unix"] + plan["maximum_queue_seconds"],
            "remaining_queue_seconds": recovered["maximum_queue_seconds"],
            "original_status_sha256": digest(status_path), "registered_protocol_sha256": args.registration,
            "recovery_script_sha256": digest(__file__), "previous_supervisor_pid": old_supervisor,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "preserved_results": [{"seed": row["seed"], "sha256": row["sha256"]}
                                  for row in recovered["cases"] if row["status"] == "completed"],
            "reason": "Supervisor disappeared after a completed worker. Cause unconfirmed. Audit existing results, preserve all outcomes, and execute only unattempted assignments. Policy and original queue deadline unchanged."})
        status_path.rename(archived_status)
        print(json.dumps({"recovery_receipt": str(receipt_path), "summary": summarize(recovered["cases"], "running")}), flush=True)
        return 0 if run(recovered, args.output, args.publish_on_finish) else 1


if __name__ == "__main__":
    raise SystemExit(main())
