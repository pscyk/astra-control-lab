"""Training-only OpenDrawer keyframes; the simulator supplies all transitions.

Construct after a fresh development reset of a native TaskEnvironment. Execute
each next_action() through the existing planner, then call observe(). Never use
this privileged controller for learned-policy inference or official evaluation.
"""

import inspect

import numpy as np


def _array(value, shape, name):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"Invalid {name}: expected finite {shape}")
    return result.copy()


class OpenDrawerKeyframeExpert:
    """Propose absolute world xyz, xyzw quaternion, gripper and optional flag.

    A proposal consumes one of at most 25 keyframe attempts, including errors
    and optional cleanup. No method steps, resets or writes the simulator.
    Native terminal feedback stops next_action(); cleanup_action() is a separate
    optional release, excluded from episode data and official scoring.
    """

    def __init__(self, task_env, *, purpose, max_actions=25):
        if purpose != "development_training":
            raise ValueError("Privileged expert is restricted to development_training")
        if type(max_actions) is not int or not 1 <= max_actions <= 25:
            raise ValueError("max_actions must be an integer in [1, 25]")
        if getattr(task_env, "eval", False) or not getattr(task_env, "_reset_called", False):
            raise ValueError("Pass a freshly reset native training TaskEnvironment")
        self.env = task_env
        self.task = task_env._task
        self.scene = task_env._scene
        if self.task.get_name() != "open_drawer" or tuple(self.task._options) != ("bottom", "middle", "top"):
            raise ValueError("Expected native OpenDrawer geometry")
        self.variation = task_env._variation_number
        if self.variation not in range(min(3, self.task.variation_count())):
            raise ValueError("Unsupported native drawer variation")
        self.joint = self.task._joints[self.variation]
        if self.joint.get_joint_type().name != "PRISMATIC":
            raise ValueError("Drawer must have a prismatic joint")
        conditions = self.task._success_conditions
        if len(conditions) != 1 or type(conditions[0]).__name__ != "JointCondition":
            raise ValueError("Unsupported native success conditions")
        self.condition = conditions[0]
        if self.condition._joint.get_handle() != self.joint.get_handle() or self.condition._pos != 0.15:
            raise ValueError("Success condition does not match selected drawer and native 0.15m threshold")
        self.start_joint = float(self.joint.get_joint_position())
        if not np.isfinite(self.start_joint) or abs(self.start_joint - self.condition._original_pos) > 0.001:
            raise ValueError("Initialize the expert immediately after a fresh reset")
        mode = task_env._action_mode
        arm = mode.arm_action_mode
        if type(mode).__name__ != "MoveArmThenGripper" or type(mode.gripper_action_mode).__name__ != "Discrete":
            raise ValueError("Expected MoveArmThenGripper with Discrete gripper")
        if type(arm).__name__ not in ("EndEffectorPoseViaPlanning", "EndEffectorPoseViaPlanning2"):
            raise ValueError("Expected the existing RLBench/TGM pose planner")
        frame = getattr(arm._frame, "name", arm._frame)
        if not arm._absolute_mode or str(frame).lower() != "world":
            raise ValueError("Expected absolute world-frame pose planning")
        self.with_collision_flag = "ignore_collisions" in inspect.signature(arm.action).parameters
        if not self.with_collision_flag and arm._collision_checking:
            raise ValueError("8D planner must permit handle contact using its existing configuration")
        self.anchor = _array(self.task._anchors[self.variation].get_position(), (3,), "handle anchor")
        self.quaternion = _array(self.task._waypoint1.get_quaternion(), (4,), "native grasp quaternion")
        if not np.isclose(np.linalg.norm(self.quaternion), 1, atol=1e-3):
            raise ValueError("Native grasp quaternion is not unit length")
        self.quaternion /= np.linalg.norm(self.quaternion)
        self.joint_axis = _array(self.joint.get_matrix(), (4, 4), "joint transform")[:3, 2]
        if not np.isclose(np.linalg.norm(self.joint_axis), 1, atol=1e-3):
            raise ValueError("Unsupported scaled or degenerate joint axis")
        self.joint_axis /= np.linalg.norm(self.joint_axis)
        objects = {obj.get_name(): obj for obj in self.task.get_base().get_objects_in_tree()}
        if "waypoint2" not in objects:
            raise ValueError("Missing native pull-direction waypoint2")
        pull_hint = _array(objects["waypoint2"].get_position(), (3,), "native pull waypoint") - self.anchor
        axial_hint = float(pull_hint @ self.joint_axis)
        if abs(axial_hint) < 0.02:
            raise ValueError("Native pull waypoint does not identify an unambiguous drawer direction")
        self.sign = float(np.sign(axial_hint))
        self.pull_axis = self.sign * self.joint_axis
        cyclic, interval = self.joint.get_joint_interval()
        lower, extent = _array(interval, (2,), "joint interval")
        self.travel = (lower + extent - self.start_joint) if self.sign > 0 else (self.start_joint - lower)
        if cyclic or self.travel <= 0.156:
            raise ValueError("Joint limits leave insufficient travel for native success")
        self.target_progress = min(0.17, self.travel - 0.002)
        self.lower = np.array([getattr(self.scene, f"_workspace_min{axis}") for axis in ("x", "y", "z")]) + 1e-6
        self.upper = np.array([getattr(self.scene, f"_workspace_max{axis}") for axis in ("x", "y", "z")]) - 1e-6
        if not np.isfinite([self.lower, self.upper]).all() or np.any(self.lower >= self.upper):
            raise ValueError("Invalid planner workspace bounds")
        self.max_actions = max_actions
        self.actions_issued = 0
        self.phase = "approach"
        self.pending = None
        self.reason = None
        self.native_success = False
        self.native_terminal = False
        self.progress = 0.0
        self.last_progress = 0.0
        self.stalled = 0
        self.regrasps = 0
        self.phase_attempts = 0
        self.pull_attempts = 0
        self.grasp_offset = np.zeros(3)
        self.cleanup_issued = False

    def _read(self):
        if self.env._variation_number != self.variation or self.task._success_conditions[0] is not self.condition:
            raise RuntimeError("Environment reset or variation changed; construct a new expert")
        joint_position = float(self.joint.get_joint_position())
        tip = _array(self.env._robot.arm.get_tip().get_pose(), (7,), "TCP pose")
        aperture = np.asarray(self.env._robot.gripper.get_open_amount(), dtype=float)
        if not np.isfinite(joint_position) or aperture.shape != (2,) or not np.isfinite(aperture).all():
            raise ValueError("Invalid drawer or two-finger gripper feedback")
        self.progress = self.sign * (joint_position - self.start_joint)
        handle = self.anchor + self.joint_axis * (joint_position - self.start_joint)
        success, terminal = self.task.success()
        self.native_success, self.native_terminal = bool(success), bool(terminal)
        return tip, handle, aperture

    def _fail(self, reason):
        self.phase, self.reason = "failed", reason

    def _issue(self, pose, gripper, ignore_collisions):
        if self.actions_issued >= self.max_actions:
            self._fail("keyframe_cap")
            return None
        pose = _array(pose, (7,), "target pose")
        if np.any(pose[:3] < self.lower) or np.any(pose[:3] > self.upper):
            self._fail("target_outside_workspace")
            return None
        if not np.isclose(np.linalg.norm(pose[3:]), 1, atol=1e-3):
            raise ValueError("Target quaternion must be unit length")
        values = [*pose, float(gripper)]
        if self.with_collision_flag:
            values.append(float(ignore_collisions))
        self.actions_issued += 1
        self.phase_attempts += 1
        self.pending = self.phase
        return np.asarray(values, dtype=np.float32)

    def next_action(self):
        """Return an 8D/9D keyframe, or None on terminal, failure or budget end."""
        if self.pending is not None:
            raise RuntimeError("Execute the pending action and call observe() first")
        if self.phase in ("done", "failed", "released"):
            return None
        tip, handle, _ = self._read()
        if self.native_terminal or self.native_success:
            self.phase = "done" if self.native_success else "failed"
            self.reason = "native_success" if self.native_success else "native_terminal"
            return None
        if self.progress < -0.003 or self.progress > self.travel + 0.003:
            self._fail("drawer_moved_outside_expected_travel")
            return None
        pose = np.r_[handle, self.quaternion]
        if self.phase == "approach":
            pose[:3] += 0.07 * self.pull_axis
            return self._issue(pose, 1, False)
        if self.phase == "contact":
            return self._issue(pose, 1, True)
        if self.phase == "close":
            return self._issue(pose, 0, True)
        if self.phase == "reopen":
            return self._issue(tip, 1, True)
        if self.phase == "pull":
            increment = min(0.015 if self.pull_attempts == 0 else 0.04, self.target_progress - self.progress)
            if increment <= 0:
                self._fail("target_travel_reached_without_native_success")
                return None
            pose[:3] += self.grasp_offset + increment * self.pull_axis
            self.pull_attempts += 1
            return self._issue(pose, 0, True)
        raise RuntimeError(f"Unexpected expert phase: {self.phase}")

    def _regrasp(self):
        if self.regrasps >= 2:
            self._fail("no_drawer_progress_after_regrasps")
        else:
            self.regrasps += 1
            self.phase = "reopen"

    def observe(self, *, terminal, execution_error=None):
        """Consume real post-action feedback, including partial failed execution.

        Forward the actual terminal value from the existing environment. Keep
        the actual observation/reward/error in the caller's transition record.
        """
        if self.pending is None:
            raise RuntimeError("No issued action to observe")
        previous_phase, self.pending = self.pending, None
        tip, handle, aperture = self._read()
        if execution_error is not None:
            self._fail(f"execution_error: {execution_error}")
        elif previous_phase == "release":
            if np.min(aperture) > 0.9:
                self.phase, self.reason = "released", "cleanup_only"
            else:
                self._fail("cleanup_release_did_not_open")
        elif terminal or self.native_terminal or self.native_success:
            self.phase = "done" if self.native_success else "failed"
            self.reason = "native_success" if self.native_success else "native_terminal"
        elif previous_phase in ("approach", "contact"):
            target = handle + (0.07 * self.pull_axis if previous_phase == "approach" else 0)
            aligned = abs(float(tip[3:] @ self.quaternion)) > np.cos(0.12 / 2)
            if np.linalg.norm(tip[:3] - target) < 0.012 and aligned and np.min(aperture) > 0.9:
                self.phase = "contact" if previous_phase == "approach" else "close"
            elif self.phase_attempts >= 3:
                self._fail(f"{previous_phase}_not_reached")
        elif previous_phase == "close":
            if np.linalg.norm(tip[:3] - handle) > 0.025 or np.min(aperture) > 0.9:
                self._regrasp()
            else:
                self.grasp_offset = tip[:3] - handle
                self.last_progress = self.progress
                self.stalled, self.pull_attempts = 0, 0
                self.phase = "pull"
        elif previous_phase == "pull":
            gain = self.progress - self.last_progress
            self.stalled = self.stalled + 1 if gain < 0.001 else 0
            self.last_progress = self.progress
            if gain < -0.003:
                self._fail("drawer_moved_against_pull_direction")
            elif self.stalled >= 2 or np.linalg.norm(tip[:3] - handle - self.grasp_offset) > 0.045:
                self._regrasp()
        elif previous_phase == "reopen":
            if np.min(aperture) > 0.9:
                self.phase = "approach"
            else:
                self._fail("regrasp_release_did_not_open")
        if self.phase != previous_phase:
            self.phase_attempts = 0
        if self.actions_issued >= self.max_actions and self.phase not in ("done", "failed", "released"):
            self._fail("keyframe_cap")
        return self.status

    def cleanup_action(self):
        """Optional terminal release; caller must exclude it from episode data.

        The ordinary rollout must already have stopped. This action still uses
        the original planner and consumes the shared 25-attempt cap. It cannot
        turn failure into an accepted demonstration or extend benchmark steps.
        """
        if self.pending is not None or self.phase != "done" or self.cleanup_issued:
            raise RuntimeError("Cleanup requires completed native success and no pending action")
        tip, _, _ = self._read()
        if not self.native_success or self.actions_issued >= self.max_actions:
            return None
        self.cleanup_issued = True
        self.phase, self.phase_attempts = "release", 0
        return self._issue(tip, 1, True)

    @property
    def status(self):
        return {
            "phase": self.phase, "actions_issued": self.actions_issued,
            "max_actions": self.max_actions, "variation": self.variation,
            "native_success": self.native_success, "native_terminal": self.native_terminal,
            "drawer_progress_m": self.progress, "regrasps": self.regrasps,
            "reason": self.reason, "cleanup_issued": self.cleanup_issued,
        }
