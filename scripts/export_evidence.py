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


def scene_end(video):
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(video)]))["streams"][0]
    frames = int(probe["nb_frames"])
    if probe["r_frame_rate"] != "30/1" or frames <= 10:
        raise ValueError("Unexpected drawer recording format")
    tail = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select=gte(n\\,{frames - 11})",
        "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    frame_bytes = probe["width"] * probe["height"] * 3
    if len(tail) != 11 * frame_bytes:
        raise ValueError("Incomplete drawer tail decode")
    def green(frame):
        return all(value <= 10 if index % 3 != 1 else value >= 245 for index, value in enumerate(frame))
    if green(tail[:frame_bytes]) or not green(tail[frame_bytes:]):
        raise ValueError("Expected exactly ten trailing green status frames")
    return (frames - 10) / 30


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
        (514006, "Residual repair", "The base trajectory fails on this scene; the learned correction changes the carry and release and satisfies native success."),
        (514024, "Residual regression", "The base trajectory succeeds, but the residual moves the dish outside the target region."),
        (514019, "Missed grasp", "Neither method acquires the dish, so a later placement correction cannot complete the task."),
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
    drawer = {"id": "drawer", "title": "Action–observe loop", "seed": 42300,
        "study": "RLBench / OpenDrawer / fresh development scene",
        "description": "The feedback run opens the drawer after eight extra Astra calls. Both runs reuse the initial proposal; neither updates model weights.",
        "scope_notice": "This pair shares the initial proposal, but the first returned drawer observation was not bitwise identical. The feedback run also changes the prompt and depth feedback.",
        "timing": "Recorded frames only; model wait is omitted. Shared controls hold the last scene frame instead of the recorder's green status card. Original MP4s remain unchanged. Playback is not physical-time evidence.", "tracks": []}
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
        if mode == "feedback":
            drawer["tracks"][-1]["playback_end_seconds"] = scene_end(destination)
    cases.append(drawer)
    teacher_root = archive / "outputs/professor-meeting-2026-10-08/controller-evaluation-01"
    teacher_summary = source(teacher_root / "open_drawer-summary.json",
        "27d43f6a317208544a07f03b4a66a21e706aebab2788aae7dc8ab69a347458ab")
    teacher_cases = []
    for case in teacher_summary["cases"]:
        path = teacher_root / f"open_drawer/seed-{case['seed']}-variant-{case['variation']}/result.json"
        result = source(path)
        returned = [row for row in result["actions"] if row["transition_returned"]]
        native_success = any(row["reward"] > 0 for row in returned)
        commands = sum(row["execution_started"] for row in result["actions"])
        if native_success != result["native_success"] or native_success != case["success"] or commands != case["native_actions"]:
            raise ValueError("Authored-controller outcome disagrees with native transitions")
        teacher_cases.append(select(result, ["seed", "variation", "native_success"])
                             | {"commands": commands, "source_sha256": digest(path)})
    controller_hash = "2959118be4711195042e173e63c9ab450986f5bf3798c345a045fb35573f06b6"
    if digest(ROOT / "reference/authored_drawer.py") != controller_hash:
        raise ValueError("Archived controller differs from the recorded controller")
    if controller_hash not in teacher_summary["input_bindings"].values():
        raise ValueError("Controller source is not bound to the archived study")
    teacher_video = teacher_root / "open_drawer/seed-9400-variant-0/rollout.mp4"
    if digest(teacher_video) != "877015f6777b0a15591b5ca4d132ef706c4e5bcef0c57ffe99675d7d99cae385":
        raise ValueError("Authored-controller video changed")
    destination = media / "drawer-authored.mp4"
    shutil.copyfile(teacher_video, destination)
    sources.append({"source": teacher_video.relative_to(archive).as_posix(), "sha256": digest(teacher_video)})
    write("teacher.json", {"status": "preliminary", "task": "RLBench / OpenDrawer",
        "scope": teacher_summary["scope"], "controller_sha256": controller_hash,
        "privileged_state": True, "runtime_LLM_calls": 0, "cases": teacher_cases})
    overview = {"id": "overview", "title": "All four methods", "study": "Recordings from separate experiments",
        "scope_notice": "Not a matched four-way comparison. These clips use different tasks and seeds. The authored controller reads privileged simulator state; the other methods do not receive those object-state inputs.",
        "description": "The overview shows what each method executes. Use the paired views to inspect a residual repair, a regression, or the extra calls in the action–observe loop.",
        "timing": "Model wait is omitted; playback clocks cannot compare physical speed or latency. Shared controls hold the last scene frame, skipping the drawer recorder's green status cards. Original MP4s remain unchanged.",
        "tracks": [
            cases[0]["tracks"][0] | {"label": "Zero-shot Astra", "context": "COLOSSEUM V2 · dish placement · seed 514006"},
            {"label": "Authored controller", "video": "media/drawer-authored.mp4", "poster": poster(destination),
             "success": teacher_cases[0]["native_success"], "commands": teacher_cases[0]["commands"],
             "calls": 0, "privileged_state": True, "source_sha256": digest(teacher_video),
             "playback_end_seconds": scene_end(destination),
             "context": "RLBench · OpenDrawer · seed 9400 · variation 0"},
            cases[0]["tracks"][1] | {"label": "Astra + residual RL", "context": "COLOSSEUM V2 · dish placement · seed 514006"},
            drawer["tracks"][1] | {"label": "Action–observe loop", "context": "RLBench · OpenDrawer · seed 42300"},
        ]}
    cases.insert(0, overview)
    write("cases.json", {"cases": cases,
        "selection": "Post-hoc illustrations, not a representative sample. Dish cases use the first seed with each displayed pattern in the prior 103-scene four-method overlap. The loop uses the first fresh drawer scene. The authored controller uses the first archived seed and variation (9400, 0); the overview mixes studies and is not protocol-matched."})
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
