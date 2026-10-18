from copy import deepcopy
import math
from statistics import mean, pstdev


def vector(values, size):
    if len(values) != size or not all(type(value) in (int, float) and math.isfinite(value) for value in values):
        raise ValueError(f"Expected {size} finite numbers")
    return list(values)


def parameters(latent):
    return [limit * math.tanh(value) for limit, value in zip((0.7, 0.08, 0.08), vector(latent, 3))]


def refine(commands, latent):
    roll, offset_y, offset_z = parameters(latent)
    corrected = deepcopy(commands)
    previous, rotated, active = None, False, False
    modified = []
    for index, command in enumerate(corrected):
        if len(command["targets"]) != 1:
            raise ValueError("This residual supports one arm only")
        target = vector(command["targets"][0], 7)
        quaternion = target[3:]
        norm = math.sqrt(sum(value * value for value in quaternion))
        if not math.isclose(norm, 1, abs_tol=1e-5):
            raise ValueError("Quaternion must have unit length")
        if len(command["grippers_open"]) != 1 or type(command["grippers_open"][0]) is not bool:
            raise ValueError("Expected one Boolean gripper command")
        if type(command["control_steps"]) is not int or command["control_steps"] <= 0:
            raise ValueError("Expected a positive step budget")
        original = deepcopy(command)
        if previous is not None and previous["grippers_open"] == command["grippers_open"] == [False]:
            before = previous["targets"][0]
            before_norm = math.sqrt(sum(value * value for value in before[3:]))
            dot = sum(first * second for first, second in zip(before[3:], quaternion)) / (before_norm * norm)
            angle = 2 * math.acos(min(1, abs(dot)))
            if rotated and math.hypot(target[0] - before[0], target[1] - before[1]) >= 0.02:
                active = True
            rotated = rotated or angle >= 0.5
        if active:
            modified.append(index)
            if roll != 0:
                quat_x, quat_y, quat_z, quat_w = [value / norm for value in quaternion]
                sine, cosine = math.sin(roll / 2), math.cos(roll / 2)
                command["targets"][0][3:] = [cosine * quat_x + sine * quat_w,
                    cosine * quat_y - sine * quat_z, cosine * quat_z + sine * quat_y,
                    cosine * quat_w - sine * quat_x]
            command["targets"][0][1] += offset_y
            command["targets"][0][2] += offset_z
        previous = original
    return corrected, {"modified_command_indices": modified, "world_roll_rad": roll,
                       "world_y_offset_m": offset_y, "world_z_offset_m": offset_z}


def policy_update(center, samples, rewards, sigma=0.7, step_size=0.3):
    center = vector(center, 3)
    samples = [vector(sample, 3) for sample in samples]
    rewards = vector(rewards, len(samples))
    if len(samples) < 2 or not all(0 <= reward <= 1 for reward in rewards):
        raise ValueError("Expected at least two returns in [0, 1]")
    if not 0 < sigma <= 1 or not 0 < step_size <= 0.3:
        raise ValueError("Invalid update scale")
    average, scale = mean(rewards), max(pstdev(rewards), 0.01)
    advantages = [(reward - average) / scale for reward in rewards]
    gradient = [mean(advantage * (sample[axis] - center[axis]) / sigma ** 2
                     for advantage, sample in zip(advantages, samples)) for axis in range(3)]
    divisor = max(math.sqrt(sum(value * value for value in gradient)), 1)
    return [min(2, max(-2, value + step_size * direction / divisor)) for value, direction in zip(center, gradient)]
