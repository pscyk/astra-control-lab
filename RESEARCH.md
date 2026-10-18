# What we learned

Snapshot: 18 October 2026. Author: C Y K Sagar.

## 1. The strongest local evidence

**Preliminary:** a frozen three-parameter residual raises budgeted completion from 21/200 to 70/200 on one clean dish task. A matched random-search residual reaches 58/200. The paired comparisons are 53 wins / 4 losses against the base and 16 wins / 4 losses against search.

This supports a narrow finding: a small learned trajectory correction can help a fixed Astra proposal on this scene distribution. It does not show a general VLA improvement. It does not show that RL is necessary for most of the gain. Random search already supplies much of it.

The audit accounts for every planned scene. Of 200 initial model requests, 166 complete. One completed proposal is invalid. The other 165 scenes execute all three methods. The 34 model deadlines are budget noncompletions, not observed physical failures.

The success test is the simulator's native predicate. It checks rack-region proximity, dish orientation, release, static state, and height. It does not certify safe contact or supported insertion into a particular rack slot.

## 2. What the rollout inspection shows

| Case | Observed outcome | Supported lesson | Claim limit |
|---|---|---|---|
| Dish, seed 514006 | Base fails; residual succeeds | A changed carry/release can satisfy native success | One selected example, not proof of a universal mechanism |
| Dish, seed 514024 | Base succeeds; residual fails | A constant correction can spoil a good action | Does not prove that a learned gate will fix it |
| Dish, seed 514019 | Neither arm grasps the dish | A suffix correction does not fix the initial grasp | Object acquisition needs a separate diagnostic |
| Drawer, seed 42300 | One-shot fails; feedback succeeds | New observations can support recovery | More calls, changed prompt/depth feedback, and a first-step observation mismatch |

The prior failure audit found 41 scenes where all three executed Astra variants never grasped the dish. Among 144 executed base failures, 137 ended with the dish nonvertical. A grasp was recorded at some point in 103 of these failures. These counts overlap; do not sum them.

The displayed dish cases were selected after results were available. They use the first seed for each outcome pattern within an earlier 103-scene four-method overlap. That selection is not random. Do not estimate rates from the videos.

## 3. The loop helps once, but costs more

**Preliminary:** fresh scenes move from 1/3 one-shot successes to 2/3 feedback successes. Previously diagnosed failures remain at 0/3 with feedback. The small fresh comparison has a two-sided exact McNemar p-value of 1.0.

The loop reuses the exact initial proposal. After the first action, it uses new RGB/depth observations, robot state, and execution feedback. Open-gripper phases have at most three waypoints. Closed-gripper phases have one. A gripper transition ends the phase. Native success has priority over a tracking warning.

The study caps execution at 25 commands and 12 additional feedback calls. No policy parameters change. This is feedback control, not RL.

Across nine new rollouts, there are 132 native commands and 71 new model calls. Six initial calls are reused. The new calls consume 1,722,158 input tokens and 30,790 output tokens. Median call wait is 18.60 seconds. The videos omit that wait.

The initial observation fields and first issued action match for the fresh drawer pair. The first returned observation is not bitwise identical. Treat the success as a useful development case, not a clean causal estimate.

## 4. Why the authored controller is separate

The reference drawer controller reads task joints, handle anchors, native waypoints, and native success conditions. It is a privileged demonstration teacher. Astra wrote its code before execution. It does not make runtime model calls.

The code rejects use outside `development_training`. Keep this restriction. Do not pool its scores with observation-only Astra. Do not present it as a vision-only zero-shot policy.

## 5. Reproduction status

| Item | Status | Check |
|---|---|---|
| Completion and paired counts | **Reproduced** from saved records | All 600 assignments; unknowns kept |
| Four Gaussian updates | **Reproduced** from saved samples | Matches saved means within `1e-12` |
| Standard-library residual transform | **Reproduced** against original code | 165 trajectories × 3 settings; maximum error `2.22e-16` |
| New model and simulator execution | **Not reproduced here** | Requires original harness, assets, and model access |
| Generalization beyond one clean task | **Hypothesis only** | No result supplied |
| Combined feedback + residual policy | **Hypothesis only** | The two components were studied separately |

One training seed is not three. Scene intervals cannot replace training-seed dispersion. Earlier task and prompt development also limits the strength of a broad “zero-shot” claim. No hidden final test is released or newly tuned in this packaging task.

## 6. Highest-value next experiments

These are **hypotheses only**, not promised gains. Lock inputs, scenes, budgets, and success rules before execution. Keep the original policy as a separate arm. Do not tune on a final test split.

1. **Check object acquisition before placement.** On a development split, compare observation-only co-motion checks with native labels used only for scoring. Measure misses and false alarms before adding a recovery action. Stop if the check cannot distinguish an empty grasp.
2. **Gate the existing residual.** Compare no correction, constant correction, and a simple observation-only gate. Freeze the gate on a separate split. Measure rescues and regressions, not only total success. Stop if gains disappear at matched budgets.
3. **Match the feedback budget.** Compare short-phase control with and without new image feedback. Hold the prompt, action budget, and call count fixed where possible. Measure wall time and timeout rate. Stop if apparent gains require an unacceptable latency increase.

Start with a small development diagnostic. Expand to at least three independent training seeds only if the mechanism survives that test. Use an untouched task or distribution shift for the final check. Do not use the displayed cases for architecture selection and then call them a final test.

## 7. What is still missing

No full-suite score, external-model ranking, bimanual claim, real-robot validation, matched asynchronous test, or broad robustness result is supported here. Collision, jerk, drop, and path-length metrics have not been reconstructed in this release. Do not infer them from a successful native predicate.

The immediate research target is selective correction with reliable acquisition feedback. A larger model or training sweep is not yet justified by these results.
