const element = id => document.getElementById(id);
let videos = [];
let playing = false;
let animation = null;
let playbackStart = 0;
let selectionVersion = 0;

function playLabel() {
  return `${playing ? "Pause" : "Play"} ${videos.length === 4 ? "all four" : "both"}`;
}

function pause() {
  playing = false;
  cancelAnimationFrame(animation);
  videos.forEach(video => video.pause());
  element("play").textContent = playLabel();
}

function endTime(video) {
  return Number.isFinite(video.duration) ? Math.min(Number(video.dataset.playbackEnd) || video.duration, video.duration) : 0;
}

function maximumTime() {
  return Math.max(...videos.map(endTime));
}

function seek(seconds) {
  videos.forEach(video => {
    if (Number.isFinite(video.duration)) video.currentTime = Math.min(seconds, Math.max(0, endTime(video) - 0.001));
  });
  element("timeline").value = seconds;
  element("clock").textContent = `${seconds.toFixed(1)} s`;
}

function tick() {
  if (!playing) return;
  const seconds = Math.min((performance.now() - playbackStart) / 1000, maximumTime());
  element("timeline").value = seconds;
  element("clock").textContent = `${seconds.toFixed(1)} s`;
  videos.forEach(video => {
    if (seconds >= endTime(video)) {
      video.pause();
      const lastFrame = Math.max(0, endTime(video) - 0.001);
      if (Math.abs(video.currentTime - lastFrame) > 0.002) video.currentTime = lastFrame;
    }
    else if (Math.abs(video.currentTime - seconds) > 0.3) video.currentTime = seconds;
  });
  if (seconds >= maximumTime()) pause();
  else animation = requestAnimationFrame(tick);
}

function ready() {
  const loaded = videos.length > 0 && videos.every(video => video.readyState >= 2 && Number.isFinite(video.duration));
  ["play", "reset", "timeline"].forEach(id => element(id).disabled = !loaded);
  if (loaded) element("timeline").max = maximumTime();
}

function showCase(record) {
  pause();
  selectionVersion += 1;
  const version = selectionVersion;
  element("load-status").textContent = "";
  element("case-title").textContent = record.title;
  element("case-meta").textContent = record.study + (record.seed === undefined ? "" : ` / seed ${record.seed}`);
  element("case-description").textContent = record.description;
  element("timing").textContent = record.timing;
  element("comparison-scope").textContent = record.scope_notice || "";
  element("comparison-scope").hidden = !record.scope_notice;
  const url = new URL(window.location.href);
  url.searchParams.set("view", record.id);
  history.replaceState(null, "", url);
  url.hash = "replay";
  element("case-link").href = url;
  document.querySelectorAll(".case-buttons button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.case === record.id)));
  ["play", "reset", "timeline"].forEach(id => element(id).disabled = true);
  element("players").replaceChildren();
  element("players").classList.toggle("four-up", record.tracks.length === 4);
  videos = record.tracks.map(track => {
    const figure = element("track-template").content.firstElementChild.cloneNode(true);
    figure.querySelector(".track-label").textContent = track.label;
    const outcome = figure.querySelector(".outcome");
    outcome.textContent = track.success ? "NATIVE SUCCESS" : "NO SUCCESS";
    outcome.classList.toggle("success", track.success);
    figure.querySelector(".video-detail").textContent = track.steps
      ? `${track.steps} native steps · model wait omitted`
      : track.privileged_state
      ? `${track.commands} commands · no runtime LLM calls · privileged state`
      : `${track.commands} commands · ${track.calls} total Astra calls (initial call shared)`;
    const context = figure.querySelector(".track-context");
    context.textContent = track.context || "";
    context.hidden = !track.context;
    const video = figure.querySelector("video");
    video.setAttribute("aria-label", `${track.label} recording`);
    video.src = track.video;
    video.poster = track.poster;
    if (track.playback_end_seconds) video.dataset.playbackEnd = track.playback_end_seconds;
    video.addEventListener("loadeddata", ready);
    video.addEventListener("canplay", ready);
    video.addEventListener("error", () => {
      if (version !== selectionVersion) return;
      pause();
      element("load-status").textContent = "A recording could not load. Reload the page or open the MP4 from the repository.";
    });
    element("players").append(figure);
    return video;
  });
  videos.forEach(video => video.load());
  element("play").textContent = playLabel();
  element("timeline").value = 0;
  element("clock").textContent = "0.0 s";
}

element("play").addEventListener("click", async () => {
  if (playing) return pause();
  if (Number(element("timeline").value) >= maximumTime() - 0.05) seek(0);
  const version = selectionVersion;
  playbackStart = performance.now() - Number(element("timeline").value) * 1000;
  playing = true;
  element("play").textContent = playLabel();
  try {
    await Promise.all(videos.filter(video => Number(element("timeline").value) < endTime(video)).map(video => video.play()));
    if (version === selectionVersion && playing) tick();
  } catch (error) {
    if (version !== selectionVersion) return;
    pause();
    element("load-status").textContent = `Playback stopped. Use the native video controls. ${error.name}`;
  }
});
element("reset").addEventListener("click", () => { pause(); seek(0); });
element("timeline").addEventListener("input", event => { pause(); seek(Number(event.target.value)); });

function wilson(successes, total) {
  const critical = 1.959963984540054;
  const rate = successes / total;
  const divisor = 1 + critical ** 2 / total;
  const center = (rate + critical ** 2 / (2 * total)) / divisor;
  const radius = critical * Math.sqrt(rate * (1 - rate) / total + critical ** 2 / (4 * total ** 2)) / divisor;
  return [center - radius, center + radius];
}

function scores(study) {
  const expectedModes = ["zero", "random_search", "astra_RL"];
  const keys = new Set(study.outcomes.map(row => `${row.seed}/${row.mode}`));
  if (study.schema_version !== 1 || study.outcomes.length !== 600 || keys.size !== 600) throw new Error("Invalid evidence schema or duplicate assignments");
  for (let seed = 514001; seed <= 514200; seed += 1) {
    expectedModes.forEach(mode => { if (!keys.has(`${seed}/${mode}`)) throw new Error("Missing planned assignment"); });
  }
  const labels = {zero: "Astra · zero-shot", random_search: "Astra + random-search residual", astra_RL: "Astra + RL residual"};
  expectedModes.forEach(mode => {
    const rows = study.outcomes.filter(row => row.mode === mode);
    const successes = rows.filter(row => row.native_success === true).length;
    const percentage = successes / rows.length * 100;
    const interval = wilson(successes, rows.length).map(value => (100 * value).toFixed(1));
    const container = document.createElement("div");
    container.className = "score";
    container.innerHTML = `<div class="score-top"><span>${labels[mode]}</span><strong>${percentage.toFixed(1)}%</strong></div><div class="score-track"><div class="score-fill" style="width:${percentage}%"></div></div><div class="score-meta">${successes}/${rows.length} planned scenes · 95% CI ${interval[0]}–${interval[1]}%</div>`;
    element("scores").append(container);
    if (mode === "zero") container.after(element("dish-loop-result"));
  });
  const records = new Map(study.outcomes.map(row => [`${row.seed}/${row.mode}`, row]));
  let rescued = 0;
  let regressed = 0;
  for (let seed = 514001; seed <= 514200; seed += 1) {
    const before = records.get(`${seed}/zero`);
    const after = records.get(`${seed}/astra_RL`);
    if (before.known && after.known) {
      rescued += Number(after.native_success && !before.native_success);
      regressed += Number(before.native_success && !after.native_success);
    }
  }
  element("rescues").textContent = rescued;
  element("regressions").textContent = regressed;
}

function separateScores(teacher, feedback) {
  element("teacher-score").textContent = `${teacher.cases.filter(row => row.native_success).length}/${teacher.cases.length}`;
  for (const [id, cohort, mode] of [
    ["loop-score", "fresh_development", "feedback"],
    ["loop-base-score", "fresh_development", "oneshot"],
    ["known-loop-score", "known_failure_diagnostic", "feedback"],
  ]) {
    const rows = feedback.rows.filter(row => row.cohort === cohort && row.mode === mode);
    element(id).textContent = `${rows.filter(row => row.success).length}/${rows.length}`;
  }
  element("loop-summary").textContent = element("loop-score").textContent;
}

function dishLoopScore(followup) {
  const rows = followup.outcomes;
  const seeds = new Set(rows.map(row => row.seed));
  const phases = {preflight: "Checking runner", running: "Running", stopped: "Run stopped", complete: "Complete"};
  const statuses = ["pending", "completed", "shared_model_deadline", "shared_proposal_rejection", "infrastructure_error"];
  if (followup.schema_version !== 1 || followup.task !== "PlaceDishInRack-v1" || rows.length !== 200 || seeds.size !== 200 || !Object.hasOwn(phases, followup.phase)) throw new Error("Invalid dish follow-up schema");
  for (let seed = 514001; seed <= 514200; seed += 1) {
    if (!seeds.has(seed)) throw new Error("Missing follow-up scene");
  }
  rows.forEach(row => {
    if (!statuses.includes(row.status)) throw new Error("Unknown follow-up outcome status");
    if (["pending", "infrastructure_error", "shared_model_deadline"].includes(row.status) ? row.native_success !== null : typeof row.native_success !== "boolean") throw new Error("Invalid follow-up outcome");
  });
  const completed = rows.filter(row => row.status === "completed").length;
  const inherited = rows.filter(row => ["shared_model_deadline", "shared_proposal_rejection"].includes(row.status)).length;
  const complete = followup.phase === "complete";
  if (complete && completed + inherited !== 200) throw new Error("Follow-up is incomplete");
  element("dish-loop-result").classList.toggle("score-unmeasured", !complete);
  element("dish-loop-bar").replaceChildren();
  if (complete) {
    const successes = rows.filter(row => row.native_success === true).length;
    const percentage = successes / 2;
    const interval = wilson(successes, 200).map(value => (100 * value).toFixed(1));
    element("dish-loop-score").textContent = `${percentage.toFixed(1)}%`;
    element("dish-loop-bar").innerHTML = `<div class="score-track"><div class="score-fill" style="width:${percentage}%"></div></div>`;
    element("dish-loop-status").textContent = `${successes}/200 planned scenes · 95% CI ${interval[0]}–${interval[1]}% · post-hoc follow-up`;
  } else {
    element("dish-loop-score").textContent = phases[followup.phase];
    const updated = new Date(followup.updated_unix * 1000).toLocaleString();
    element("dish-loop-status").textContent = `${completed}/${200 - inherited} native episodes audited; ${inherited} shared proposal outcomes retained. Snapshot: ${updated}. The score updates after the full run and audit.`;
  }
}

async function initialize() {
  try {
    const [gallery, study, teacher, feedback, followup] = await Promise.all(["cases", "study", "teacher", "feedback", "dish_loop"].map(async name => {
      const response = await fetch(`data/${name}.json?v=3`);
      if (!response.ok) throw new Error(`Cannot load ${name}`);
      return response.json();
    }));
    scores(study);
    separateScores(teacher, feedback);
    dishLoopScore(followup);
    gallery.cases.forEach((record, index) => {
      const button = document.createElement("button");
      button.textContent = `${String(index + 1).padStart(2, "0")} / ${record.title}`;
      button.dataset.case = record.id;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => showCase(record));
      element("case-buttons").append(button);
    });
    const requested = new URLSearchParams(window.location.search).get("view");
    showCase(gallery.cases.find(record => record.id === requested) || gallery.cases[0]);
  } catch (error) {
    element("load-status").textContent = `Evidence did not load: ${error.message}. Serve this folder over HTTP, not file://.`;
  }
}

initialize();
