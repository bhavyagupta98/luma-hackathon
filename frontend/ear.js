// Earpiece client: push-to-talk speech -> text -> gateway, gateway text -> speech.
// URL params:
//   ?device=DC-D-100   &lang=en-US
//   &stt=model|browser (default model: on-device Whisper)   &stt_model=base|tiny
//   &tts=model|browser (default model: on-device MMS-TTS)
//   &mock=1 (no server)   &debug=1 (show log)
// Model engines download once (about 115 MB) and are cached. Until they finish loading,
// and if loading fails, the browser's built-in speech engines are used.

import { ModelSpeechToText, SpeechToText } from "./stt.js";
import { BrowserVoice, ModelVoice, TextToSpeech } from "./tts.js";
import { STT_MODELS } from "./speech-models.js";

const params = new URLSearchParams(location.search);
const deviceId = params.get("device") || "DC-D-100";
const lang = params.get("lang") || "en-US";
const mock = params.has("mock");
const debug = params.has("debug");
const english = lang.startsWith("en");
const useModelStt = params.get("stt") !== "browser" && english; // Whisper .en models are English-only
const useModelTts = params.get("tts") !== "browser";
const sttModel = STT_MODELS[params.get("stt_model")] ?? STT_MODELS.base;
let voiceSession = null;
try {
  voiceSession = JSON.parse(sessionStorage.getItem("luma.voiceSession"));
} catch {
  voiceSession = null;
}

const dot = document.getElementById("dot");
const nameLabel = document.getElementById("name");
const hint = document.getElementById("hint");
const overlay = document.getElementById("overlay");
const logView = document.getElementById("log");
logView.hidden = !debug;

let socket = null;
let connected = false;
let reconnectDelay = 500;
let talking = false;
let transcribing = false;
let audioContext = null;

let stt = new SpeechToText({ lang, onInterim: (text) => text && log(`… ${text}`) });
let nextStt = null; // the model engine, swapped in between utterances once it has loaded
const tts = new TextToSpeech({
  voice: useModelTts ? new ModelVoice() : new BrowserVoice(),
  onSpoken: (item) => {
    if (item.id) send({ type: "ack", id: item.id });
    setState();
  },
});

function log(line) {
  if (!debug) return;
  logView.textContent = `${new Date().toLocaleTimeString()} ${line}\n${logView.textContent}`
    .split("\n")
    .slice(0, 40)
    .join("\n");
}

function setState() {
  if (talking) dot.dataset.state = "listening";
  else if (tts.speaking) dot.dataset.state = "speaking";
  else dot.dataset.state = connected || mock ? "idle" : "offline";
}

// Minimal audio cues until earcons.js lands: high blip = listening, low buzz = not heard.
function cue(kind) {
  if (!audioContext) return;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  const now = audioContext.currentTime;
  oscillator.type = kind === "listening" ? "sine" : "square";
  oscillator.frequency.value = kind === "listening" ? 880 : 140;
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.2, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.18);
  oscillator.connect(gain).connect(audioContext.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.2);
}

function speak(message) {
  log(`< [${tts.voice.engine}] ${message.text}`);
  tts.speak(message);
  setState();
}

// ---- Speech models ----

async function loadModels() {
  const progress = {};
  const report = (name) => (percent) => {
    progress[name] = Math.round(percent);
    hint.textContent = `Loading speech models: ${Object.entries(progress)
      .map(([model, value]) => `${model} ${value}%`)
      .join(", ")}`;
  };
  const jobs = [];
  if (useModelStt) {
    const modelStt = new ModelSpeechToText({ model: sttModel });
    jobs.push(
      modelStt.prepare(report("speech to text")).then(() => {
        nextStt = modelStt;
        log(`speech to text: ${sttModel} ready`);
      }),
    );
  }
  if (useModelTts) {
    jobs.push(tts.voice.prepare(report("text to speech")).then(() => log("text to speech: model ready")));
  }
  const results = await Promise.allSettled(jobs);
  results
    .filter((result) => result.status === "rejected")
    .forEach((result) => {
      console.error(result.reason);
      log(`! model failed, staying on the browser engine: ${result.reason?.message ?? result.reason}`);
    });
  hint.textContent = "Hold Space or touch and hold to talk";
}

// ---- Gateway connection ----

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws/${encodeURIComponent(deviceId)}`);
  socket.onopen = () => {
    connected = true;
    reconnectDelay = 500;
    setState();
  };
  socket.onmessage = (event) => handleServerMessage(JSON.parse(event.data));
  socket.onclose = () => {
    connected = false;
    setState();
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 5000);
  };
}

function handleServerMessage(message) {
  if (message.type === "hello") {
    nameLabel.textContent = message.operator?.name ?? deviceId;
  } else if (message.type === "say") {
    speak(message);
    if (message.reauthenticate) {
      sessionStorage.removeItem("luma.voiceSession");
      setTimeout(() => {
        location.href = `auth.html?device=${encodeURIComponent(deviceId)}`;
      }, 2500);
    }
  }
}

function send(message) {
  if (mock) return mockReply(message);
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function activeAuthenticationToken() {
  const expiresAt = Number(voiceSession?.expires_at || 0);
  if (!voiceSession?.authentication_token || Date.now() >= expiresAt * 1000) {
    voiceSession = null;
    sessionStorage.removeItem("luma.voiceSession");
    return null;
  }
  return voiceSession.authentication_token;
}

function mockReply(message) {
  if (message.type !== "utterance") return;
  setTimeout(() => speak({ id: null, text: `You said: ${message.text}.`, priority: "task", lang }), 300);
}

// ---- Push to talk ----

function startTalking() {
  if (talking || transcribing) return;
  if (nextStt) {
    stt = nextStt;
    nextStt = null;
  }
  talking = true;
  tts.hold(true);
  cue("listening");
  try {
    stt.start();
  } catch (error) {
    talking = false;
    tts.hold(false);
    log(`! ${error.message}`);
    speak({ text: "Speech recognition is not available in this browser.", priority: "task", lang });
  }
  setState();
}

async function stopTalking() {
  if (!talking) return;
  talking = false;
  transcribing = true;
  setState();
  let text = "";
  const started = performance.now();
  try {
    text = await stt.stop();
  } catch (error) {
    log(`! ${error.message}`);
  } finally {
    transcribing = false;
  }
  tts.hold(false);
  setState();

  if (!text) {
    cue("error");
    return;
  }
  log(`> [${stt.engine}, ${Math.round(performance.now() - started)} ms] ${text}`);
  if (!connected && !mock && /^(repeat|say again)\b/i.test(text)) {
    tts.repeat();
    return;
  }
  if (!connected && !mock) {
    speak({ text: "I'm not connected right now. Please try again in a moment.", priority: "task", lang });
    return;
  }
  const authenticationToken = activeAuthenticationToken();
  if (!mock && !authenticationToken) {
    speak({ text: "Your session expired. Please authenticate your voice again.", priority: "task", lang });
    setTimeout(() => {
      location.href = `auth.html?device=${encodeURIComponent(deviceId)}`;
    }, 2500);
    return;
  }
  send({ type: "utterance", text, lang, authentication_token: authenticationToken });
}

window.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.repeat || !overlay.hidden) return;
  event.preventDefault();
  startTalking();
});
window.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || !overlay.hidden) return;
  event.preventDefault();
  stopTalking();
});
document.querySelector("main").addEventListener("pointerdown", startTalking);
window.addEventListener("pointerup", stopTalking);
window.addEventListener("pointercancel", stopTalking);

// Browsers only allow audio after a user gesture, so the first tap unlocks it.
overlay.addEventListener("click", () => {
  overlay.hidden = true;
  audioContext = new AudioContext();
  if (!mock && !activeAuthenticationToken()) {
    speak({ text: "Please authenticate your voice first.", priority: "task", lang });
    setTimeout(() => {
      location.href = `auth.html?device=${encodeURIComponent(deviceId)}`;
    }, 1800);
    return;
  }
  if (!TextToSpeech.isSupported() || (!SpeechToText.isSupported() && !useModelStt)) {
    nameLabel.textContent = "This browser has no speech support. Use Chrome.";
    return;
  }
  speak({ text: "Earpiece ready.", priority: "info", lang });
  if (!mock) connect();
  setState();
  loadModels();
});
