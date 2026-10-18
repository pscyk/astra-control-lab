# Dish action–observe follow-up

Registered on 18 October 2026. Completed on 19 October 2026 at 04:12 IST. Status: preliminary, capacity-recovered.

The original dish comparison tested zero-shot Astra, random-search corrections, and an RL residual. This follow-up adds action–observe control without replacing any original result or retraining a policy.

## Completed result

The loop succeeds in **32/200 planned scenes (16.0%)**, with a 95% Wilson interval of **11.6–21.7%**. All 165 eligible native episodes passed audit. The denominator retains 34 shared initial model deadlines and one rejected proposal; the deadlines remain unknown physical outcomes.

Compared with the zero-shot base, the loop repairs 13 failures and loses two successes across 166 known pairs. The base scores 10.5%, random-search corrections score 29.0%, and the RL residual scores 35.0%. These are results for one clean dish task, not the full benchmark.

One capacity-error episode was retried and succeeded. The preceding interrupted attempt used 128 native steps, two new model calls, and 73.23 seconds of feedback wait; its wall time was 81.67 seconds. Those costs are additional to the completed retry. Excluding that scene's recovered success leaves 31 successes, or 15.5% of all planned assignments, with the original interrupted physical outcome still unknown.

The final audit checks all episode hashes, native outcomes, action transforms, model-call records, and input bindings. All 133 episodes completed before capacity recovery retain their original hashes. [Machine-readable results](docs/data/dish_loop.json) include the retry record and source hashes.

## Original protocol

| Setting | Value |
|---|---|
| Task and condition | `PlaceDishInRack-v1`, `NONE` |
| Scene schedule | Seeds 514001–514200 in order |
| Initial proposal | Reuse each recorded Astra proposal; verify exact native reset, camera pixels, robot state, and calibration |
| Control | Original `pd_ee_delta_pose`, native 20 Hz, unchanged action caps |
| Episode cap | 327 native steps |
| Feedback schedule | Review at steps 64, 128, 192, and 256, unless the episode has ended |
| Feedback input | Before/current RGB, calibration, robot state, action history, and pending commands |
| Model | Historical alias `gpt-6-astra`, medium reasoning, tools disabled |
| Model budget | 720 seconds total, charging the archived initial wait and new feedback waits; each new call has a cap of 180 seconds |
| Fallback | Keep pending actions after an invalid response or model deadline |
| Stopping | Native success/termination, model-requested stop, or step cap |
| Queue limits | 36 hours; stop before a new episode if free disk falls below 1 GiB |
| Training | None |

There are 165 eligible native episodes. The other assignments retain 34 shared initial model deadlines and one shared proposal rejection. No scene receives a replacement initial call. The denominator remains 200, and deadline cases retain unknown physical outcomes.

Infrastructure errors stop the queue rather than becoming task failures. The runner keeps the incomplete assignments and suppresses the completion percentage until the audit accounts for all 200 scenes.

## Checks before the queue

The development scene is seed 508201, outside the evaluation schedule. The transport probe verifies an exact archived reset and a genuine Astra response. With feedback disabled, the new executor must reproduce the archived baseline action and robot-state sequence across all 327 steps. With feedback enabled, it must match the first 64 steps before making a new call.

Each completed episode receives an audit of native success flags, diagnostic records, action transforms, call limits, tool-free model events, and file hashes. Native simulator state enters the audit files, not model requests. Unit tests check call accounting, interrupted command durations, and incomplete-denominator handling.

## Run

This command needs the original native harness, simulator checkout, assets, and authenticated Astra transport. The public replay package alone does not supply them. Use the same pinned runtime as the original comparison.

```bash
export PYTHONPATH="$SIMULATOR:$HARNESS"
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json

"$PYTHON" scripts/run_dish_loop.py --harness "$HARNESS" --output "$RUN" --prepare
REGISTRATION=$(sha256sum "$RUN/protocol.json" | cut -d' ' -f1)
"$PYTHON" scripts/run_dish_loop.py --harness "$HARNESS" --output "$RUN" --registration "$REGISTRATION" --smoke base
"$PYTHON" scripts/run_dish_loop.py --harness "$HARNESS" --output "$RUN" --registration "$REGISTRATION" --smoke feedback
"$PYTHON" scripts/run_dish_loop.py --harness "$HARNESS" --output "$RUN" --registration "$REGISTRATION"
```

The registration hashes the implementation and harness sources before execution. A started queue refuses an automatic restart. Results stay in a new directory, leaving original records untouched. `--publish-on-finish` additionally commits and pushes the two public result files after completion or a stopped run; it refuses publication when unrelated repository edits are present.

## Supervisor recovery

The first evaluation episode completed, but its supervisor exited before recording the result in the queue status. The cause is unconfirmed. The result passed an independent audit and remains in the comparison, including its failure outcome. It was not rerun.

`scripts/resume_dish_loop.py` verifies that the recorded processes are absent, acquires the native-run lock, and audits existing results before continuing unattempted assignments. It refuses to replay an incomplete attempt. The recovery receipt preserves the original status hash, result hashes, registration hash, and elapsed queue time. The registered policy code and scene schedule are unchanged.

The continuation runs under the user service `astra-dish-loop-20261018.service`, with automatic restart disabled. A crash needs investigation, not an automatic scene retry. Private logs and recovery records remain beside the registered protocol.

```bash
systemctl --user status astra-dish-loop-20261018.service
tail -f "$RUN/queue.log"
```

## Capacity recovery amendment

On 19 October 2026, Astra returned “Selected model is at capacity” during scene 514156, after 128 native steps. The queue stopped with 133 completed episodes and 24 successes. The user then authorized retries and continuation.

`scripts/retry_dish_loop.py` adds at most three retries per scene for this exact capacity error, with waits of 60, 180, and 300 seconds. It does not change the registered executor, model, prompt, action limits, scene schedule, or initial proposals. It accepts the first completed attempt, whether successful or unsuccessful. Completed task failures, other transport errors, and shared initial proposal deadlines are not retried.

Before retrying, the supervisor verifies and archives the interrupted attempt, its video, call records, and queue status. It audits the completed episodes without executing them again. The original queue deadline and disk reserve still apply. Each retry starts from the same scene reset; it is not a continuation from the interrupted simulator state.

This amendment changes the original no-retry protocol. The recovered result uses the same 200-scene denominator, but retries add native steps and model calls beyond the first attempt's budget. `capacity_recovery` in the public result records the interrupted attempts, hashes, call counts, native steps, and time costs. It also reports successes excluding retried scenes. A capacity-recovered score must not be presented as an unchanged, strict no-retry comparison.

```bash
"$PYTHON" scripts/retry_dish_loop.py --harness "$HARNESS" --output "$RUN" \
  --registration "$REGISTRATION" --publish-on-finish
systemctl --user status astra-dish-loop-capacity-20261019.service
tail -f "$RUN/capacity-queue.log"
```

## Interpretation

This is a post-hoc follow-up after inspection of the original study, not an untouched final test. Tasks, scenes, initial proposals, and native execution limits match. The loop makes more model calls within the remaining wait budget; the logs do not attest an immutable Astra checkpoint across dates. Simulation pauses during calls, so this is not a real-time or asynchronous-control result.

The separate RLBench feedback study remains available on the page. Its 2/3 fresh-scene result is not a dish-placement score.
