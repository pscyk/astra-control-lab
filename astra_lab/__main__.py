import argparse
import json
import math
import sys

from .evidence import DATA, load, paired, summarize, verify
from .residual import parameters, policy_update, refine


def main():
    parser = argparse.ArgumentParser(description="Astra Control Lab: inspect the experiment, without an API key or GPU.")
    parser.add_argument("command", choices=("report", "verify", "replay-training", "refine-example"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            print(f"PASS: {verify()} exported evidence files match SHA-256.")
            print("Hashes check file identity, not independent simulation truth.")
        elif args.command == "replay-training":
            training = json.loads((DATA / "training.json").read_text())
            center = [0., 0., 0.]
            for index, batch in enumerate(training["updates"]):
                if any(not math.isclose(value, expected, abs_tol=1e-12) for value, expected in zip(center, batch["mean_before"])):
                    raise ValueError("Broken update chain")
                center = policy_update(center, batch["samples"], batch["returns"], batch["sigma"], batch["step_size"])
                if any(not math.isclose(value, expected, abs_tol=1e-12) for value, expected in zip(center, batch["mean_after"])):
                    raise ValueError("Update differs from the recorded result")
                print(f"Update {index + 1}: PASS {center}")
            print("Frozen residual [roll rad, Y m, Z m]:", parameters(center))
            print("Recorded-sample replay only. No new simulator or model calls.")
        elif args.command == "refine-example":
            training = json.loads((DATA / "training.json").read_text())
            example = json.loads((DATA / "trajectory.json").read_text())
            commands, details = refine(example["commands"], training["mean"])
            print(json.dumps({"commands": commands, "refinement": details}, indent=2))
        else:
            data = load()
            result = {"methods": summarize(data), "RL_vs_Astra": paired(data), "RL_vs_search": paired(data, "random_search")}
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print("ASTRA CONTROL LAB / preliminary / one clean task / 200 planned scenes\n")
                for row in result["methods"]:
                    lower, upper = row["wilson95"]
                    print(f"{row['mode']:15} {row['successes']:3}/200  {row['budgeted_rate']:6.1%}  Wilson95 {lower:.1%}-{upper:.1%}")
                print("\nRL vs Astra:", result["RL_vs_Astra"])
                print("RL vs search:", result["RL_vs_search"])
                print("34 shared model deadlines count as budget noncompletion; their physical outcomes are unknown.")
                print("These are not full-suite scores. The residual has one training seed, not three.")
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
