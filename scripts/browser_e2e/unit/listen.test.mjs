// Exercises VoiceRecorder.listen() with a scripted microphone level and fake browser audio classes.
let level = () => 0;            // RMS the fake microphone reports, as a function of ms since listen() began
let began = 0;
let contextState = "running";
const events = [];

globalThis.AudioContext = class {
  get state() { return contextState; }
  async resume() {}
  createAnalyser() {
    return { fftSize: 1024, getFloatTimeDomainData(buf) { buf.fill(level(performance.now() - began)); } };
  }
  createMediaStreamSource() { return { connect() {} }; }
};
globalThis.MediaRecorder = class {
  constructor() { this.mimeType = "audio/webm"; }
  start() { began = performance.now(); events.push("recorder started"); }
  stop() { events.push("recorder stopped"); setTimeout(() => this.onstop?.(), 0); }
};

const { VoiceRecorder } = await import("../../../frontend/recorder.js");

async function run(name, opts, fn, expect) {
  level = fn; events.length = 0; contextState = opts.state ?? "running";
  const r = new VoiceRecorder({ maxSeconds: opts.maxSeconds ?? 14 });
  r._stream = {};                       // pretend the microphone is open
  const t0 = performance.now();
  const result = await r.listen({ startTimeoutMs: opts.startTimeoutMs, endSilenceMs: opts.endSilenceMs });
  const took = Math.round(performance.now() - t0);
  const [lo, hi] = expect;
  const ok = took >= lo && took <= hi && events.includes("recorder stopped");
  console.log(ok ? "ok  " : "FAIL", name.padEnd(46), `${String(took).padStart(5)} ms (expected ${lo}-${hi})`, JSON.stringify(result));
  return ok;
}

const loud = 0.1;
const results = [];
results.push(await run("nobody speaks -> gives up at the start timeout", { startTimeoutMs: 800 }, () => 0, [780, 1000]));
results.push(await run("speech 0.3-1.1 s then quiet -> ends after silence", { startTimeoutMs: 3000, endSilenceMs: 600 },
  (t) => (t > 300 && t < 1100 ? loud : 0), [1650, 1950]));
results.push(await run("speech with a short pause keeps going", { startTimeoutMs: 3000, endSilenceMs: 700 },
  (t) => ((t > 200 && t < 700) || (t > 1100 && t < 1600) ? loud : 0), [2250, 2550]));
results.push(await run("a single loud blip is not speech", { startTimeoutMs: 900, endSilenceMs: 500 },
  (t) => (t > 200 && t < 260 ? loud : 0), [880, 1100]));
results.push(await run("quiet room noise below the threshold is ignored", { startTimeoutMs: 700 }, () => 0.01, [680, 900]));
results.push(await run("keeps listening past max length -> cut at max", { startTimeoutMs: 3000, maxSeconds: 1 }, () => loud, [980, 1200]));
results.push(await run("suspended audio -> fixed window instead of silence", { state: "suspended" }, () => 0, [5950, 6200]));
console.log(results.every(Boolean) ? "ALL PASSED" : "SOME FAILED");
