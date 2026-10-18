"""Phase selection from the recorded V1 action-observe controller."""


def phase_length(waypoints, previous_open):
    if type(previous_open) is not bool:
        raise ValueError("Previous gripper state must be Boolean")
    if any(type(waypoint.get("gripper_open")) is not bool for waypoint in waypoints):
        raise ValueError("Each waypoint needs a Boolean gripper command")
    limit = 3 if previous_open else 1
    for index, waypoint in enumerate(waypoints[:limit]):
        if waypoint["gripper_open"] != previous_open:
            return index + 1
    return min(limit, len(waypoints))


def feedback_reason(native_success, terminal, tracking_warning=None):
    if type(native_success) is not bool or type(terminal) is not bool:
        raise ValueError("Use native Boolean outcomes")
    if native_success:
        return "native_success"
    if terminal:
        return "native_terminal_failure"
    return tracking_warning
