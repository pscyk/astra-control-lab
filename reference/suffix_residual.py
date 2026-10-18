"""Trajectory-level Gaussian policy gradient with a bounded post-grasp residual."""

from copy import deepcopy

import numpy as np
from scipy.spatial.transform import Rotation


def refine(commands, latent):
    latent = np.asarray(latent, dtype=float)
    if latent.shape != (3,) or not np.isfinite(latent).all():
        raise ValueError("Expected three finite residual coordinates")
    offset = .08 * np.tanh(latent)
    corrected = deepcopy(commands)
    closed_before, modified = False, []
    for index, command in enumerate(corrected):
        targets = np.asarray(command["targets"], dtype=float)
        if (targets.shape != (1, 7) or not np.isfinite(targets).all()
                or not np.isclose(np.linalg.norm(targets[0, 3:]), 1, atol=1e-5)
                or len(command["grippers_open"]) != 1 or type(command["grippers_open"][0]) is not bool):
            raise ValueError("Expected one finite single-arm command")
        closed = not command["grippers_open"][0]
        if closed and closed_before:
            if np.any(offset):
                command["targets"][0][:3] = (targets[0, :3] + Rotation.from_quat(targets[0, 3:]).apply(offset)).tolist()
            modified.append(index)
        closed_before = closed
    return corrected, {"latent": latent.tolist(), "tool_frame_offset_m": offset.tolist(),
                       "eligible_command_indices": modified, "maximum_offset_per_axis_m": .08}


def training_return(native_success, final_info, executed_steps):
    if type(native_success) is not bool or type(executed_steps) is not int or executed_steps < 0:
        raise ValueError("Unknown outcomes cannot become training rewards")
    if native_success:
        return 1.
    if executed_steps == 0:
        return 0.
    distance = np.asarray(final_info["obj_to_goal_dist"], dtype=float)
    angle = np.asarray(final_info["obj_to_goal_angle"], dtype=float)
    if (distance.shape != (1,) or angle.shape != (1,) or not np.isfinite(distance).all()
            or not np.isfinite(angle).all() or distance[0] < 0 or angle[0] < 0):
        raise ValueError("Invalid training-only native goal diagnostic")
    return float(.5 * np.exp(-distance[0] / .05 - angle[0] / .2))


def update(mean, samples, rewards, *, sigma=.7, step_size=.3):
    mean, samples, rewards = np.asarray(mean, dtype=float), np.asarray(samples, dtype=float), np.asarray(rewards, dtype=float)
    if (mean.shape != (3,) or samples.ndim != 2 or samples.shape[1] != 3 or len(samples) < 2
            or rewards.shape != (len(samples),) or not np.isfinite(mean).all()
            or not np.isfinite(samples).all() or not np.isfinite(rewards).all()
            or np.any(rewards < 0) or np.any(rewards > 1) or not 0 < sigma <= 1 or not 0 < step_size <= .3):
        raise ValueError("Invalid Gaussian policy-gradient batch")
    advantages = (rewards - rewards.mean()) / max(float(rewards.std()), .01)
    gradient = np.mean(advantages[:, None] * (samples - mean) / sigma**2, axis=0)
    bounded = gradient / max(float(np.linalg.norm(gradient)), 1.)
    after = np.clip(mean + step_size * bounded, -2, 2)
    return {"mean_before": mean.tolist(), "mean_after": after.tolist(), "samples": samples.tolist(),
            "returns": rewards.tolist(), "advantages": advantages.tolist(), "gradient": gradient.tolist(),
            "sigma": sigma, "step_size": step_size,
            "estimator": "Batch-standardized Gaussian score-function surrogate; not an unbiased gradient claim"}


def choose_candidate(candidates):
    return min(candidates, key=lambda row: (-row["mean_return"], float(np.linalg.norm(row["latent"])), row["index"]))
