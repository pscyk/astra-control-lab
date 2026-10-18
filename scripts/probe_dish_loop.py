import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Check the archived simulator and Astra transport on a development scene.")
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.harness.resolve()))
    import numpy as np
    from PIL import Image
    from astra_controller import digest, save
    from astra_trial_repair_02 import query
    from audit_molmo_coverage import compare_states
    from controller_runtime_02 import diagnostic_value
    from interface_02 import observation_packet
    from molmo_pilot_05 import require_idle
    from native_runtime import make_env
    from official_horizon_control import decode_proposal, proposal_context
    from official_horizon_pilot_02 import verify_runtime
    from pilot import instruction

    args.output.mkdir(parents=True, exist_ok=False)
    result = {"purpose": "development_preflight_not_evaluation", "seed": 508201,
              "started_unix": time.time(), "complete": False, "model_call_started": False}
    env = None
    try:
        require_idle()
        reference = args.harness / "official-horizon-02/episodes/003--seed508201--proposal"
        result["reference_sha256"] = digest(reference / "result.json")
        env = make_env("PlaceDishInRack-v1", num_envs=1, obs_mode="rgb", control_mode="pd_ee_delta_pose",
                       sim_backend="gpu", render_backend="gpu", perturbation_set="NONE",
                       render_mode="rgb_array", max_episode_steps=327)
        verify_runtime(env, 327)
        observation, _ = env.reset(seed=508201)
        packet = observation_packet(observation, bimanual=False)
        assert json.loads((reference / "reset.json").read_text()) == {
            "robot": packet["robot"], "calibration": packet["calibration"]}
        for name, pixels in packet["images"].items():
            np.testing.assert_array_equal(pixels, np.asarray(Image.open(reference / (name + ".png"))))
        with (reference / "offline-privileged.jsonl").open() as stream:
            original = json.loads(stream.readline())["state"]
        result["initial_state"] = compare_states(original, diagnostic_value(env.unwrapped.get_state_dict()))
        assert result["initial_state"]["exact_match"]
        result["native_reset_matched"] = True
        result["model_call_started"] = True
        save(args.output / "status.json", result)
        response = query(packet, packet, proposal_context(instruction("PlaceDishInRack-v1"), 327),
                         args.output / "call-00", timeout_seconds=240)
        commands, rejection = decode_proposal(response, packet, 327)
        result.update(complete=True, proposed_commands=len(commands), policy_rejection=rejection)
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if env is not None:
            env.close()
        result["completed_unix"] = time.time()
        save(args.output / "result.json", result)
    print(json.dumps(result), flush=True)
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
