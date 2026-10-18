# Astra Control Lab

### Good plan. Wrong grasp.

**Astra proposes the motion. The simulator tests the claim.**

[Open the interactive demo](https://pscyk.github.io/astra-control-lab/) · [Read the findings](RESEARCH.md) · [Inspect the data](docs/data/study.json)

[![Astra Control Lab: recorded dish scene, zero-shot versus residual](docs/media/teaser.gif)](https://pscyk.github.io/astra-control-lab/)

*One selected repair. Model wait is omitted. [Open all four cases](https://pscyk.github.io/astra-control-lab/), including a regression.*

A small research workbench for LLM-driven robot control. Watch actual simulation recordings. Compare the same scene. Recompute the scores. Replay the four residual-policy updates without a GPU or an API key.

The demo keeps the failed runs in view. A good correction must repair a failure **without breaking a success**.

## Four methods. Clear boundaries.

| Method | What Astra does | What changes during execution | What this repo includes |
|---|---|---|---|
| **Zero-shot trajectory** | Reads observations and returns an action sequence | No learned weights | Recorded actions, contracts, results, and videos |
| **Astra-authored controller** | Writes Python before execution | Controller state | Original drawer teacher; private simulator state required |
| **Astra + residual RL** | Supplies the fixed base trajectory | No weights at evaluation; three corrections are trained beforehand | Residual transform, policy update, all four training batches |
| **Astra action–observe loop** | Reads new observations and revises actions | The plan, not the model weights | Phase rules, feedback contract, results, and drawer videos |

```text
Instruction + observations
           │
           ▼
     Astra trajectory ──── optional frozen residual ──── execution
           ▲                                               │
           └──────── optional new observation ──────────────┘
```

The optional paths are **separate experiments** here. This diagram does not claim that their combined policy has been tested.

“Zero-shot” means no task demonstrations or task weight updates for the base model. It does not mean an untouched prompt or a new task. The prompts and adapters had development work. Inputs include calibration and robot state, not RGB alone.

The historical logs request the alias `gpt-6-astra`. They do not attest an immutable backend checkpoint. This repo does not promise access to that model.

## The result, with the denominator

**Preliminary.** One clean COLOSSEUM V2 task: `PlaceDishInRack-v1`. Each method receives the same initial proposal for each scene. The frozen comparison uses seeds `514001` through `514200`.

| Method | Completed / planned | Completion rate | 95% Wilson interval |
|---|---:|---:|---:|
| Astra, no correction | 21 / 200 | 10.5% | 7.0–15.5% |
| Astra + random-search residual | 58 / 200 | 29.0% | 23.2–35.6% |
| Astra + RL residual | 70 / 200 | **35.0%** | 28.7–41.8% |

- RL repairs **53** base failures and causes **4** regressions: a net **24.5 percentage points**.
- Against random search, RL wins **16** pairs and loses **4**: a net **6 points**.
- **34 shared model deadlines** count as noncompletion within the budget. Their physical outcomes remain unknown.
- There are **495 native rollouts**, plus one shared rejected proposal. No failed scene is removed from the 200-scene denominator.
- The model deadline is 720 seconds. The execution cap is 327 native steps at 20 Hz.

The intervals describe variation across these scenes. They do not measure variation across training seeds. The residual has **one training seed**. This is not a full COLOSSEUM score, a bimanual result, or a state-of-the-art claim.

## Yes, the action–observe loop exists

**Preliminary.** A separate RLBench study reuses each exact initial one-shot proposal. It then asks Astra for feedback after short action phases.

| Fresh development scene | One-shot | Action–observe |
|---|---|---|
| OpenDrawer | Failure | Success |
| InsertOntoSquarePeg | Success | Success |
| StackCups | Failure | Failure |
| **Total** | **1 / 3** | **2 / 3** |

The loop also failed on all three previously diagnosed failure scenes. Its drawer repair used eight extra calls. Across all nine new rollouts, the study made 71 new calls. Median model wait was 18.60 seconds per call. **This is not real-time control.**

The experiment changed the prompt and depth feedback as well as the call count. The drawer’s first returned observation was not bitwise identical. Three fresh scenes do not establish a general improvement. The loop uses no RL updates.

## Run in one minute

Use Python 3.10 or later. The main package has **no third-party dependencies**.

```bash
git clone https://github.com/pscyk/astra-control-lab.git
cd astra-control-lab
python3 -m astra_lab verify
python3 -m astra_lab report
python3 -m astra_lab replay-training
python3 -m astra_lab refine-example
python3 -m unittest discover -s tests -v
```

Open the local demo:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs
```

Visit `http://127.0.0.1:8000`. Select **The repair**, **The regression**, **The missed grasp**, or **Observe. Try again.** Play both recordings or use the shared time slider.

The recordings omit model wait. Dish videos retain their 20 Hz recording rate. Drawer playback is not evidence of physical speed. The shorter recording stops at its last frame. Native video controls can play each recording on its own.

## Three numbers, not another giant model

The residual modifies a trajectory suffix after a closed-gripper rotation and a later translation. It adds world-frame roll, Y, and Z corrections. It does not change the gripper commands or step budgets.

```text
latent → tanh → [roll × 0.7 rad, Y × 0.08 m, Z × 0.08 m]
```

The final policy adds about **0.209 rad**, **7.52 mm**, and **48.74 mm**. Four batch-standardized Gaussian policy-gradient updates produce this policy. Each update uses eight recorded returns. The random-search control has the same 32 exploration evaluations and shares the first eight samples. Both methods also use a shared zero-residual baseline.

Training rewards use simulator object state. Deployment does not receive those diagnostics. The model stays fixed. There is no behavior-cloned student and no online weight update during evaluation.

`replay-training` recomputes the recorded updates. It **does not run new training episodes**. A replay match is not an independent replication of the simulator experiment.

## Repository map

| Path | Purpose |
|---|---|
| `astra_lab/residual.py` | Standard-library residual transform and policy update |
| `astra_lab/feedback.py` | Extracted action-phase and terminal rules |
| `astra_lab/evidence.py` | Assignment checks, paired counts, intervals, and file hashes |
| `docs/` | Static interactive demo; no build step or external scripts |
| `docs/data/` | 600 assignments, training samples, contracts, and source hashes |
| `docs/media/` | Original simulation recordings and a demo preview |
| `reference/` | Historical controller and residual code; optional simulator dependencies |
| `tests/` | Core unit tests and optional browser smoke test |
| `scripts/export_evidence.py` | Allowlisted export from the original research archive |
| `RESEARCH.md` | Findings, failure cases, limits, and next tests |
| `VALIDATION.md` | Release checks and exact commands |

## What you can reproduce

**Reproduced from saved artifacts:** scores, paired counts, confidence intervals, four training updates, and the residual transform. The Python port matches the original NumPy/SciPy transform on 165 saved trajectories at three latent settings. Maximum target-coordinate difference: `2.22e-16`.

**Not independently reproduced by this package:** new Astra calls, new simulator rollouts, full benchmark training, or live robot execution. The complete native harness, simulator assets, and model access are not bundled. The export script needs the original archive. The public audit and demo do not.

The clips are post-hoc examples. The full outcome table supplies the denominator. File hashes detect byte changes; they do not prove that a simulator result is true.

## Design and credits

The README takes structural inspiration from [LeRobot](https://github.com/huggingface/lerobot), [OpenPI](https://github.com/Physical-Intelligence/openpi), and [OpenVLA](https://github.com/openvla/openvla): show the demo, state the setup, expose the limits. No branding or code was copied from these projects.

The research uses [COLOSSEUM V2](https://github.com/jstmn/ColosseumV2), [ManiSkill](https://github.com/haosulab/ManiSkill), and [RLBench](https://github.com/stepjam/RLBench). See [NOTICE](NOTICE) for scope and asset terms.

Documentation uses short, direct sentences in the style of ASD-STE100. It is not certified for full ASD-STE100 vocabulary compliance.

**Build small. Show the failures. Keep the denominator.**
