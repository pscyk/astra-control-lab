import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
MODES = ("zero", "astra_RL", "random_search")


def load():
    data = json.loads((DATA / "study.json").read_text())
    expected = {(seed, mode) for seed in range(514001, 514201) for mode in MODES}
    actual = [(row["seed"], row["mode"]) for row in data["outcomes"]]
    if data["schema_version"] != 1 or len(actual) != 600 or set(actual) != expected:
        raise ValueError("Incomplete or duplicate registered assignments")
    for row in data["outcomes"]:
        if type(row["known"]) is not bool or type(row["native_execution"]) is not bool:
            raise ValueError("Outcome flags must be Boolean")
        if row["known"] and type(row["native_success"]) is not bool:
            raise ValueError("A known outcome needs a Boolean success value")
        if not row["known"] and (row["native_success"] is not None or row["native_execution"]):
            raise ValueError("Unknown physical outcomes cannot be relabelled")
    return data


def wilson(successes, trials):
    if type(successes) is not int or type(trials) is not int or trials < 1 or not 0 <= successes <= trials:
        raise ValueError("Invalid success counts")
    critical = NormalDist().inv_cdf(0.975)
    rate = successes / trials
    divisor = 1 + critical ** 2 / trials
    center = (rate + critical ** 2 / (2 * trials)) / divisor
    radius = critical * math.sqrt(rate * (1 - rate) / trials + critical ** 2 / (4 * trials ** 2)) / divisor
    return [max(0, center - radius), min(1, center + radius)]


def summarize(data):
    rows = []
    for mode in MODES:
        selected = [row for row in data["outcomes"] if row["mode"] == mode]
        successes = sum(row["native_success"] is True for row in selected)
        unknown = sum(not row["known"] for row in selected)
        rows.append({"mode": mode, "successes": successes, "planned": len(selected),
                     "budgeted_rate": successes / len(selected), "wilson95": wilson(successes, len(selected)),
                     "physical_outcomes_unknown": unknown,
                     "physical_success_bounds": [successes / len(selected), (successes + unknown) / len(selected)]})
    return rows


def paired(data, baseline="zero"):
    if baseline not in ("zero", "random_search"):
        raise ValueError("Choose a registered comparison")
    records = {(row["seed"], row["mode"]): row for row in data["outcomes"]}
    complete = wins = losses = 0
    for seed in range(514001, 514201):
        before, after = records[(seed, baseline)], records[(seed, "astra_RL")]
        if before["known"] and after["known"]:
            complete += 1
            wins += after["native_success"] and not before["native_success"]
            losses += before["native_success"] and not after["native_success"]
    return {"known_pairs": complete, "RL_wins": wins, "RL_losses": losses, "budgeted_delta_pp": (wins - losses) / 2}


def verify():
    root = ROOT / "docs"
    manifest = json.loads((DATA / "manifest.json").read_text())
    seen = set()
    for row in manifest["files"]:
        if Path(row["path"]).is_absolute():
            raise ValueError("Evidence paths must be relative")
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or path in seen:
            raise ValueError("Unsafe or duplicate evidence path")
        seen.add(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Evidence changed: {row['path']}")
    if not seen:
        raise ValueError("Empty manifest")
    expected = {path.resolve() for path in root.glob("data/*.json") if path.name != "manifest.json"}
    expected.update(path.resolve() for path in root.glob("media/*.mp4"))
    if seen != expected:
        raise ValueError("Manifest does not cover the exported evidence")
    return len(seen)
