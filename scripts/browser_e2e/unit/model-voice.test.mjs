// The on-device voice must never leave the worker in silence: if the browser keeps its audio
// output suspended, it hands over to the browser voice; if playback stalls, it stops waiting.
let contextState = "suspended";
const spoken = [];
globalThis.AudioContext = class {
  get state() { return contextState; }
  async resume() {}
  createBuffer(_c, length, rate) { return { duration: length / rate, copyToChannel() {} }; }
  createBufferSource() {
    return { connect() {}, start() { spoken.push("played by the model"); }, stop() {}, set buffer(b) {} };
  }
  get destination() { return {}; }
};

const { ModelVoice } = await import("../../../frontend/tts.js");
const fallback = { say: async (text) => { spoken.push(`browser voice said: ${text}`); }, cancel() {} };
const makeVoice = () => {
  const voice = new ModelVoice({ fallback });
  voice._synthesizer = { ready: true, synthesize: async () => ({ audio: new Float32Array(1600), samplingRate: 16000 }) };
  return voice;
};

let failures = 0;
const check = (name, ok) => { if (!ok) failures += 1; console.log(ok ? "ok  " : "FAIL", name); };

// 1) suspended audio output -> the browser voice speaks instead of nothing
contextState = "suspended"; spoken.length = 0;
await makeVoice().say("Alert. Server B is overheating.");
check("suspended audio -> falls back to the browser voice", spoken.join("|") === "browser voice said: Alert. Server B is overheating.");

// 2) running audio output -> the model plays it, and the call finishes even if 'ended' never fires
contextState = "running"; spoken.length = 0;
const started = performance.now();
await makeVoice().say("Hello");
const took = performance.now() - started;
check("running audio -> played by the model", spoken.join("|") === "played by the model");
check(`a stalled playback stops waiting (${Math.round(took)} ms, ~2.1 s)`, took > 1900 && took < 3500);

console.log(failures ? `${failures} FAILED` : "all passed");
process.exit(failures ? 1 : 0);
