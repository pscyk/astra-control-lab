"""Three bounded trajectory residuals, trained from terminal simulator reward."""

from copy import deepcopy

import numpy as np
from scipy.spatial.transform import Rotation

from suffix_residual import update as policy_update


LIMITS = np.array([.7, .08, .08])


def parameters(latent):
    latent = np.asarray(latent, dtype=float)
    if latent.shape != (3,) or not np.isfinite(latent).all():
        raise ValueError("Expected three finite residual coordinates")
    return LIMITS * np.tanh(latent)


def refine(commands, latent):
    roll, offset_y, offset_z = parameters(latent)
    corrected = deepcopy(commands)
    previous, rotated, active = None, False, False
    modified, first_active = [], None
    for index, command in enumerate(corrected):
        target = np.asarray(command["targets"], dtype=float)
        if (target.shape != (1, 7) or not np.isfinite(target).all()
                or not np.isclose(np.linalg.norm(target[0, 3:]), 1, atol=1e-5)
                or len(command["grippers_open"]) != 1 or type(command["grippers_open"][0]) is not bool
                or type(command["control_steps"]) is not int or command["control_steps"] <= 0):
            raise ValueError("Invalid single-arm trajectory command")
        original = deepcopy(command)
        if previous is not None and previous["grippers_open"] == command["grippers_open"] == [False]:
            before = np.asarray(previous["targets"][0])
            angle = (Rotation.from_quat(before[3:]).inv() * Rotation.from_quat(target[0, 3:])).magnitude()
            if rotated and np.linalg.norm(target[0, :2] - before[:2]) >= .02:
                active = True
            rotated = rotated or angle >= .5
        if active:
            if first_active is None:
                first_active = index
            modified.append(index)
            if roll != 0:
                command["targets"][0][3:] = (Rotation.from_rotvec([roll, 0., 0.]) * Rotation.from_quat(target[0, 3:])).as_quat().tolist()
            if offset_y != 0 or offset_z != 0:
                command["targets"][0][:3] = (target[0, :3] + [0., offset_y, offset_z]).tolist()
        previous = original
    return corrected, {"latent": list(latent), "world_roll_rad": float(roll),
        "world_y_offset_m": float(offset_y), "world_z_offset_m": float(offset_z),
        "first_active_command_index": first_active, "modified_command_indices": modified,
        "policy_inputs": "Authored public-observation Astra commands and frozen latent only"}


def training_return(result, final_diagnostic):
    if result["complete"] is not True or type(result["native_success"]) is not bool:
        raise ValueError("Unknown outcomes cannot become rewards")
    if result["native_success"]:
        return 1.
    info, actors = final_diagnostic["info"], final_diagnostic["state"]["actors"]
    plate, rack = np.asarray(actors["plate"][0], dtype=float), np.asarray(actors["dish_rack"][0], dtype=float)
    if len(plate) < 7 or len(rack) < 3 or not np.isfinite(np.r_[plate, rack]).all():
        raise ValueError("Invalid training-only native state")
    normal_z = abs(Rotation.from_quat([*plate[4:7], plate[3]]).as_matrix()[2, 2])
    distance = np.linalg.norm(plate[:2] - rack[:2])
    reward = .75 * np.exp(-distance / .15 - max(normal_z - .35, 0.) / .4)
    if info["is_grasped"][0]:
        reward *= .25
    if not info["is_static"][0]:
        reward *= .5
    if not info["above_table"][0]:
        reward = 0.
    assert 0 <= reward <= .75
    return float(reward)
