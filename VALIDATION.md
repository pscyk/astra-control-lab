# Release checks

Date: 19 October 2026.

## Local checks

| Check | Result |
|---|---|
| Standard-library unit tests | 31 pass |
| Exported JSON and source-video hashes | 18 files pass |
| Four recorded policy updates | Match within `1e-12` |
| Original NumPy/SciPy residual versus port | 495 comparisons; maximum target error `2.22e-16` |
| Browser playback | Five views × two viewports pass; four panels share one row on desktop |
| View links | Selection, direct action–observe link, reload, and invalid-view fallback pass |
| Dish chart coverage | Action–observe row shows run status until its full audit completes; incomplete runs have no percentage bar |
| Drawer end frames | Shared controls hold the last scene frame, not the green status card |
| Authored-controller export | All 15 outcomes agree with returned native rewards; source controller hash matches |
| Browser runtime errors | None in the smoke test |
| Mobile horizontal overflow | None at 390 px |
| Follow-up display states | Synthetic completed, stopped, and falsely completed records pass; no partial score is displayed |
| Capacity retry guard | Accepts the recorded capacity error only; rejects completed task failures, other transport errors, and changed artifacts |
| Report styling | Uses cyks.in's color values, grid, and local font stacks; no downloaded fonts |
| Dish follow-up baseline smoke | All 327 native steps match the archived development baseline exactly |
| Completed dish follow-up | All 165 eligible episodes pass the final audit; 200 assignments retained; 32 successes |
| Capacity-recovery preservation | All 133 previously completed episode hashes unchanged; interrupted attempt retained and verified |
| New model calls or simulator rollouts | The new action–observe follow-up executes both; see `DISH_LOOP.md` |

The transform check uses 165 original saved proposals. Each proposal is checked at zero, the frozen RL mean, and `[-2, 2, -2]`. This is numerical parity, not new simulation evidence.

## Repeat the public checks

Run from the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m astra_lab verify
python3 -m astra_lab report --json
python3 -m astra_lab replay-training
python3 -m astra_lab refine-example
python3 -m compileall -q astra_lab reference scripts
```

The optional browser test needs Playwright and a compatible Chromium installation. It is not part of the dependency-free Python package.

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs
python3 tests/browser_smoke.py --url http://127.0.0.1:8000
```

Use `--chromium PATH` to select an existing browser. The test checks play, pause, seek, reset, case selection, study counts, direct links, and mobile width. It also checks the four-panel desktop layout and samples the held drawer frames to reject a green status card. It saves screenshots and a JSON report under the system temporary directory by default. The release check used Chromium 1228 and Playwright 1.64.0 on Linux.

## Export and media

The public demo does not need the original archive. To rebuild the exported evidence, the maintainer can run:

```bash
python3 scripts/export_evidence.py PATH_TO_ORIGINAL_RESEARCH_ARCHIVE
bash scripts/make_teaser.sh
```

Both commands need FFmpeg. The exporter checks fixed hashes for the primary records, copies nine original MP4 recordings without re-encoding, and extracts the first frame for each poster. It verifies the ten trailing green status frames in the successful drawer clips before assigning a scene-end time for shared playback. Native video controls still show the complete source recording. The GIF uses eight frames per second and holds the shorter clip's last frame; it remains a selected dish pair, not a four-way trial or a new rollout.

The manifest covers JSON evidence and original MP4 recordings. Display-only posters, the GIF, and the browser screenshot are derived previews, not primary evidence.

## Not checked

No real-robot run, Safari/Firefox test, formal accessibility audit, or certified ASD-STE100 vocabulary check was performed. Research limits are listed in `RESEARCH.md`.
