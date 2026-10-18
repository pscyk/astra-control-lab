import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "docs"
EXPECTED = {
    "placement327-confirmation-terminal-audit-01.json": "66d556e04141738a870246af1c8bdd738597d79807a4d838688649f696187609",
    "placement327-confirmation-plan-01.json": "83156d7186e75dc966bd37b17baac1c61d8b00f292f4f5eeddc5b2008544f880",
    "placement327-01/policy-final.json": "1008640f543e066247a1533dbf887799aa74d21cf85f152b1aadb3266f0ba1fe",
    "placement327-confirmation-case-breakdown-01.json": "d171e8246a0a4f5d5218e39b92168648b2c31cb037893b4404b09902db0ccf9c",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, data):
    path = DESTINATION / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, allow_nan=False) + "\n"
    if any(marker in text for marker in ("/home/", "/Users/", "agent_id", "api_key", "access_token")):
        raise ValueError(f"Private content in {name}")
    path.write_text(text)


def select(data, keys):
    return {key: data[key] for key in keys}


def main():
    parser = argparse.ArgumentParser(description="Export allowlisted fields from the original local research archive.")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    audit_root = archive / "work/benchmark-audit"
    base = audit_root / "colosseum-v2-evaluation-01-2026-10-09"
    feedback_root = audit_root / "astra-feedback-01-2026-10-09"
    sources = []

    def source(path, expected=None):
        actual = digest(path)
        if expected and actual != expected:
            raise ValueError(f"Source hash changed: {path.name}")
        sources.append({"source": path.relative_to(archive).as_posix(), "sha256": actual})
        return json.loads(path.read_text())

    for name, expected in EXPECTED.items():
        source(base / name, expected)
    audit = json.loads((base / "placement327-confirmation-terminal-audit-01.json").read_text())
    study = {
        "schema_version": 1, "status": "preliminary", "task": "PlaceDishInRack-v1",
        "condition": "NONE", "seeds": [514001, 514200], "control_hz": 20,
        "native_step_limit": 327, "model_deadline_seconds": 720,
        "model_alias_requested": "gpt-6-astra", "immutable_model_identity_attested": False,
        "shared_proposal_per_scene": True, "training_seeds": [508201],
        "counts": select(audit, ["model_attempts", "model_calls_completed", "verified_model_deadlines",
                                 "native_rollouts_completed", "native_steps", "parameter_updates"]),
        "outcomes": [select(row, ["seed", "mode", "known", "native_success", "native_execution", "reason"])
                     | {"source_sha256": row.get("sha256")} for row in audit["paired_outcomes"]],
        "scope": "One clean task. No full-suite score, three-training-seed claim, or external-model ranking.",
        "missingness": "34 shared model deadlines count as budget noncompletion. Their physical outcomes remain unknown.",
        "rejection": "One shared proposal was rejected before execution. No native success was observed.",
    }
    write("study.json", study)
    policy = json.loads((base / "placement327-01/policy-final.json").read_text())
    training = select(policy, ["mean", "deployment", "training_seed", "shared_first_batch",
                              "exploration_evaluations_per_method", "shared_zero_baseline",
                              "all_in_training_attempts_per_method", "training_reward"])
    training["updates"] = [source(base / f"placement327-01/update-{index:02}.json") for index in range(4)]
    training["random_search"] = select(policy["random_search"], ["index", "latent", "mean_return"])
    write("training.json", training)
    feedback = source(feedback_root / "verification.json")
    write("feedback.json", select(feedback, ["complete", "scope", "summary", "rows", "native_actions",
        "new_LLM_calls", "reused_initial_calls", "new_call_input_tokens", "new_call_output_tokens", "parameter_updates"])
        | {"status": "preliminary", "median_call_wait_seconds": 18.60,
           "confounds": ["Different prompt and depth feedback as well as extra calls.",
                         "First returned drawer observation was not bitwise identical.",
                         "Only three fresh scenes. No generalization claim."]})
    preview = source(archive / "reports/astra-research-failures-2026-10-12/demo/preview_manifest.json")
    media = DESTINATION / "media"
    media.mkdir(parents=True, exist_ok=True)

    def poster(video):
        path = video.with_suffix(".png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0", "-i", str(video),
                        "-frames:v", "1", str(path)], check=True)
        return f"media/{path.name}"
    cases = []
    descriptions = [
        (514006, "The repair", "The frozen residual changes the carry and release. Native success changes from false to true."),
        (514024, "The regression", "The base trajectory succeeds. The same residual moves the dish outside the target region."),
        (514019, "The missed grasp", "Neither method acquires the dish. A later placement correction cannot fix an empty grasp."),
    ]
    for seed, title, description in descriptions:
        case = {"id": str(seed), "title": title, "description": description, "seed": seed,
                "study": "COLOSSEUM V2 / PlaceDishInRack-v1", "tracks": [],
                "timing": "20 Hz simulation video. Model wait is omitted. The shorter clip holds its last frame."}
        for mode, label in [("zero", "Astra · zero-shot"), ("astra_RL", "Astra + residual")]:
            record = next(row for row in preview["source_media"] if row["seed"] == seed and row["mode"] == mode)
            original = Path(record["path"])
            if digest(original) != record["sha256"]:
                raise ValueError("Video source changed")
            result = source(Path(record["result"]["path"]), record["result"]["sha256"])
            destination = media / f"{seed}-{mode}.mp4"
            shutil.copyfile(original, destination)
            sources.append({"source": original.relative_to(archive).as_posix(), "sha256": digest(original)})
            case["tracks"].append({"label": label, "video": f"media/{destination.name}",
                "success": result["native_success"], "steps": record["steps"], "poster": poster(destination),
                "duration": float(record["stream"]["duration"]), "source_sha256": record["sha256"]})
            if seed == 514006 and mode == "zero":
                write("trajectory.json", {"seed": seed, "frame": "world", "quaternion_order": "xyzw",
                    "commands": result["proposal_commands"], "source_sha256": record["result"]["sha256"]})
        cases.append(case)
    drawer = {"id": "drawer", "title": "Observe. Try again.", "seed": 42300,
        "study": "RLBench / OpenDrawer / fresh development scene",
        "description": "The feedback run opens the drawer. It uses eight more Astra calls after the shared first proposal. This is not RL.",
        "timing": "Recorded frames only. Model wait is omitted. Playback is not wall-clock or physical-time evidence.", "tracks": []}
    for mode, label in [("oneshot", "Astra · one-shot"), ("feedback", "Astra · action–observe")]:
        directory = feedback_root / f"rollouts/fresh-open_drawer-{mode}"
        result = source(directory / "result.json", feedback["input_bindings"][str(directory / "result.json")])
        original = directory / "rollout.mp4"
        destination = media / f"drawer-{mode}.mp4"
        shutil.copyfile(original, destination)
        sources.append({"source": original.relative_to(archive).as_posix(), "sha256": digest(original)})
        drawer["tracks"].append({"label": label, "video": f"media/{destination.name}",
            "success": result["native_success"], "commands": len(result["actions"]),
            "calls": len(result["calls"]), "source_sha256": digest(original), "poster": poster(destination)})
    cases.append(drawer)
    write("cases.json", {"cases": cases,
        "selection": "Post-hoc illustrations, not a representative sample. Dish cases use the first seed with each displayed pattern in the prior 103-scene four-method overlap. Drawer uses the first fresh drawer scene."})
    contracts = {}
    for label, path in [("v2", base / "astra_controller.py"), ("v1_feedback", feedback_root / "controller.py")]:
        sources.append({"source": path.relative_to(archive).as_posix(), "sha256": digest(path)})
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "CONTRACT" for target in node.targets):
                contracts[label] = ast.literal_eval(node.value)
    write("contracts.json", contracts)
    write("provenance.json", {"export_version": 1, "sources": sources,
        "method": "Allowlisted JSON fields and byte-identical source MP4 files. No model reasoning, credentials or absolute source paths.",
        "limits": "Original private archive is not bundled. Hashes identify sources; they do not independently validate simulation outcomes."})
    paths = sorted(list((DESTINATION / "data").glob("*.json")) + list(media.glob("*.mp4")))
    write("manifest.json", {"algorithm": "sha256", "files": [
        {"path": path.relative_to(DESTINATION).as_posix(), "sha256": digest(path)}
        for path in paths if path.name != "manifest.json"]})
    print(f"Exported {len(study['outcomes'])} assignments and {len(cases)} cases.")


if __name__ == "__main__":
    main()
