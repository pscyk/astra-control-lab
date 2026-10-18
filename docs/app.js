const element = id => document.getElementById(id);
const videos = [element("left"), element("right")];
let playing = false;
let animation = null;
let playbackStart = 0;
let selectionVersion = 0;

function pause() {
  playing = false;
  cancelAnimationFrame(animation);
  videos.forEach(video => video.pause());
  element("play").textContent = "Play both";
}

function maximumTime() {
  return Math.max(...videos.map(video => Number.isFinite(video.duration) ? video.duration : 0));
}

function seek(seconds) {
  videos.forEach(video => {
    if (Number.isFinite(video.duration)) video.currentTime = Math.min(seconds, Math.max(0, video.duration - 0.001));
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
    if (seconds >= video.duration) video.pause();
    else if (Math.abs(video.currentTime - seconds) > 0.3) video.currentTime = seconds;
  });
  if (seconds >= maximumTime()) pause();
  else animation = requestAnimationFrame(tick);
}

function ready() {
  const loaded = videos.every(video => video.readyState >= 2 && Number.isFinite(video.duration));
  ["play", "reset", "timeline"].forEach(id => element(id).disabled = !loaded);
  if (loaded) element("timeline").max = maximumTime();
}

function showCase(record) {
  pause();
  selectionVersion += 1;
  element("load-status").textContent = "";
  element("case-title").textContent = record.title;
  element("case-meta").textContent = `${record.study} / seed ${record.seed}`;
  element("case-description").textContent = record.description;
  element("timing").textContent = record.timing;
  document.querySelectorAll(".case-buttons button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.case === record.id)));
  ["play", "reset", "timeline"].forEach(id => element(id).disabled = true);
  record.tracks.forEach((track, index) => {
    const side = index === 0 ? "left" : "right";
    element(`label-${side}`).textContent = track.label;
    element(`result-${side}`).textContent = track.success ? "NATIVE SUCCESS" : "NO SUCCESS";
    element(`result-${side}`).className = `outcome${track.success ? " success" : ""}`;
    element(`detail-${side}`).textContent = track.steps
      ? `${track.steps} native steps · model wait omitted`
      : `${track.commands} commands · ${track.calls} total Astra calls (initial call shared)`;
    videos[index].src = track.video;
    videos[index].poster = track.poster;
    videos[index].load();
  });
  element("timeline").value = 0;
  element("clock").textContent = "0.0 s";
}

element("play").addEventListener("click", async () => {
  if (playing) return pause();
  if (Number(element("timeline").value) >= maximumTime() - 0.05) seek(0);
  const version = selectionVersion;
  playbackStart = performance.now() - Number(element("timeline").value) * 1000;
  playing = true;
  element("play").textContent = "Pause both";
  try {
    await Promise.all(videos.filter(video => Number(element("timeline").value) < video.duration).map(video => video.play()));
    if (version === selectionVersion && playing) tick();
  } catch (error) {
    if (version !== selectionVersion) return;
    pause();
    element("load-status").textContent = `Playback stopped. Use the native video controls. ${error.name}`;
  }
});
element("reset").addEventListener("click", () => { pause(); seek(0); });
element("timeline").addEventListener("input", event => { pause(); seek(Number(event.target.value)); });
videos.forEach(video => {
  video.addEventListener("loadeddata", ready);
  video.addEventListener("canplay", ready);
  video.addEventListener("error", () => {
    pause();
    element("load-status").textContent = "A recording could not load. Reload the page or open the MP4 from the repository.";
  });
});

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

async function initialize() {
  try {
    const [gallery, study] = await Promise.all(["cases", "study"].map(async name => {
      const response = await fetch(`data/${name}.json`);
      if (!response.ok) throw new Error(`Cannot load ${name}`);
      return response.json();
    }));
    scores(study);
    gallery.cases.forEach((record, index) => {
      const button = document.createElement("button");
      button.textContent = `${String(index + 1).padStart(2, "0")} / ${record.title}`;
      button.dataset.case = record.id;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => showCase(record));
      element("case-buttons").append(button);
    });
    showCase(gallery.cases[0]);
  } catch (error) {
    element("load-status").textContent = `Evidence did not load: ${error.message}. Serve this folder over HTTP, not file://.`;
  }
}

initialize();
