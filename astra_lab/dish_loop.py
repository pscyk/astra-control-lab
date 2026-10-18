from copy import deepcopy
import math


def call_allowance(initial_wait, feedback_wait, calls):
    for seconds in (initial_wait, feedback_wait):
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Model wait must be a finite nonnegative number")
    if type(calls) is not int or calls < 0:
        raise ValueError("Call count must be a nonnegative integer")
    return 0 if calls >= 4 else max(0, min(180, math.floor(720 - initial_wait - feedback_wait)))


def phase_steps(command, executed, feedback_enabled=True):
    if type(executed) is not int or not 0 <= executed < 327:
        raise ValueError("Invalid native step count")
    duration = command["control_steps"]
    if type(duration) is not int or duration <= 0:
        raise ValueError("Invalid command duration")
    return min(duration, 327 - executed, 64 - executed % 64 if feedback_enabled else 327)


def remaining_command(command, executed):
    if type(executed) is not int or not 0 < executed <= command["control_steps"]:
        raise ValueError("Invalid executed command duration")
    remaining = deepcopy(command)
    remaining["control_steps"] -= executed
    return remaining if remaining["control_steps"] else None


def summarize(rows, phase):
    if len(rows) != 200 or {row["seed"] for row in rows} != set(range(514001, 514201)):
        raise ValueError("Expected all 200 unique planned scenes")
    accounted = sum(row["status"] in ("completed", "shared_model_deadline", "shared_proposal_rejection") for row in rows)
    executed = sum(row["status"] == "completed" for row in rows)
    successes = sum(row["native_success"] is True for row in rows)
    if any(row["native_success"] is not None for row in rows if row["status"] in ("pending", "infrastructure_error", "shared_model_deadline")):
        raise ValueError("Unknown outcomes must stay unknown")
    if phase == "complete" and accounted != 200:
        raise ValueError("Cannot report a complete score with unfinished assignments")
    return {"planned": 200, "accounted": accounted, "native_completed": executed,
            "successes": successes, "budgeted_rate": successes / 200 if phase == "complete" else None}
