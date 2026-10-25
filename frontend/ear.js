// Earpiece client, hands-free: it listens for a spoken command, converts it to text, sends it to the
// gateway, speaks the reply, and listens again. Nothing needs to be pressed after the first tap.
// URL params:
//   ?device=DC-D-100   &lang=en-US
//   &manual=1  hold Space / press and hold the button to talk instead of auto-listening
//   &stt=model    use on-device Whisper (default: the browser's speech recognition)   &stt_model=base|tiny
//   &tts=model    use the on-device voice model (default: the browser's voice)
//   &mock=1 (no server)   &debug=1 (show log)
// The model engines download once (about 115 MB) and are cached. Until they finish loading,
// and if loading fails, the browser's built-in speech engines are used. They are opt-in because
// they run on the page's main thread and are slower than the browser's own engines.
// Needs a voice session from auth.html (valid for 60 s); without one it returns to sign-in.

import { ModelSpeechToText, SpeechToText } from "./stt.js";
import { BrowserVoice, ModelVoice, TextToSpeech } from "./tts.js";
import { STT_MODELS } from "./speech-models.js";

const params = new URLSearchParams(location.search);
const deviceId = params.get("device") || "DC-D-100";
const lang = params.get("lang") || "en-US";
const mock = params.has("mock");
const debug = params.has("debug");
const manual = params.has("manual");
const english = lang.startsWith("en");
const useModelStt = params.get("stt") === "model" && english; // Whisper .en models are English-only
const useModelTts = params.get("tts") === "model";
const sttModel = STT_MODELS[params.get("stt_model")] ?? STT_MODELS.base;
const READY_HINT = manual
  ? "Press and hold the button, or hold Space, to talk"
  : "Just speak after the tone. Nothing to press.";

const SESSION_KEY = "luma.voiceSession";
const session = loadSession();
const redirecting = !session && !mock;
if (redirecting) {
  location.replace(signInUrl());
}

function loadSession() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    if (stored && stored.device_id === deviceId && stored.expires_at > Date.now()) return stored;
  } catch {
    // no usable session
  }
  return null;
}

function signInUrl() {
  const next = new URLSearchParams({ device: deviceId });
  for (const key of ["debug", "stt", "tts", "manual"]) {
    if (params.has(key)) next.set(key, params.get(key));
  }
  return `auth.html?${next}`;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const dot = document.getElementById("dot");
const nameLabel = document.getElementById("name");
const hint = document.getElementById("hint");
const overlay = document.getElementById("overlay");
const logView = document.getElementById("log");
logView.hidden = !debug;
if (manual) document.body.classList.add("manual");
hint.textContent = READY_HINT;

let socket = null;
let connected = false;
let reconnectDelay = 500;
let listening = false;
let pendingReply = false; // a command was sent and its spoken reply has not arrived yet
let audioContext = null;
let sessionEnded = false;
let started = false;

let stt = new SpeechToText({ lang });
let nextStt = null; // the model engine, swapped in between utterances once it has loaded
const tts = new TextToSpeech({
  voice: useModelTts ? new ModelVoice() : new BrowserVoice(),
  onSpoken: (item) => {
    if (item.id) send({ type: "ack", id: item.id });
    setState();
    if (sessionEnded) location.replace(signInUrl()); // the "session expired" notice was just spoken
  },
});

// The gateway clears the session after 60 s and tells us; this timer covers a lost connection.
function endSession(reason) {
  if (sessionEnded) return;
  sessionEnded = true;
  log(`session ended: ${reason}`);
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // nothing to clear
  }
  setTimeout(() => location.replace(signInUrl()), 8000); // fallback if the notice can't be spoken
}
if (session && !mock) {
  setTimeout(() => {
    if (!sessionEnded) {
      endSession("time limit");
      speak({ text: "Your session has expired. Please authenticate again.", priority: "warning", lang });
    }
  }, Math.max(0, session.expires_at - Date.now()) + 2000);
}

function log(line) {
  if (!debug) return;
  logView.textContent = `${new Date().toLocaleTimeString()} ${line}\n${logView.textContent}`
    .split("\n")
    .slice(0, 40)
    .join("\n");
}

function setState() {
  if (listening) dot.dataset.state = "listening";
  else if (tts.speaking) dot.dataset.state = "speaking";
  else dot.dataset.state = connected || mock ? "idle" : "offline";
}

// Minimal audio cues: a high blip means "I'm listening now".
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
  pendingReply = false; // whatever we were waiting for has arrived
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
  hint.textContent = READY_HINT;
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
    nameLabel.textContent = session?.operator?.name ?? deviceId;
  } else if (message.type === "session_expired") {
    endSession("cleared by the gateway");
  } else if (message.type === "say") {
    // An alert must not wait for the current listen to time out.
    if (listening && (message.priority === "warning" || message.priority === "emergency")) {
      stt.abortListening?.();
    }
    speak(message);
  }
}

function send(message) {
  if (mock) return mockReply(message);
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function mockReply(message) {
  if (message.type !== "utterance") return;
  setTimeout(() => speak({ id: null, text: `You said: ${message.text}.`, priority: "task", lang }), 300);
}

// ---- Manual fallback (?manual=1): hold Space or the button instead of auto-listening ----

let onPress = null;
let onRelease = null;
const pressed = () => new Promise((resolve) => (onPress = resolve));
const released = () => new Promise((resolve) => (onRelease = resolve));

function press() {
  onPress?.();
  onPress = null;
}

function release() {
  onRelease?.();
  onRelease = null;
}

if (manual) {
  window.addEventListener("keydown", (event) => {
    if (event.code !== "Space" || event.repeat || !overlay.hidden) return;
    event.preventDefault();
    press();
  });
  window.addEventListener("keyup", (event) => {
    if (event.code !== "Space" || !overlay.hidden) return;
    event.preventDefault();
    release();
  });
  document.querySelector("main").addEventListener("pointerdown", press);
  window.addEventListener("pointerup", release);
  window.addEventListener("pointercancel", release);
}

// ---- Conversation: listen, send, wait for the spoken reply, listen again ----

// Resolves once nothing is being spoken and no reply is outstanding.
async function settled() {
  const giveUp = Date.now() + 15_000;
  while ((tts.speaking || pendingReply) && Date.now() < giveUp && !sessionEnded) await sleep(100);
  await sleep(350); // the speaker's tail must not be heard as the next command
}

// One utterance as text ("" when nobody spoke).
async function capture() {
  if (!manual) return stt.listenOnce();
  const letGo = released();
  await pressed();
  stt.start();
  cue("listening");
  listening = true;
  setState();
  await letGo;
  return stt.stop();
}

async function conversationLoop() {
  let announce = true; // play the tone only after something was said, not on every quiet restart
  let failures = 0;
  while (!sessionEnded) {
    await settled();
    if (sessionEnded) return;
    if (nextStt) {
      stt = nextStt;
      nextStt = null;
    }
    tts.hold(true); // nothing else is spoken while we listen
    if (announce && !manual) {
      cue("listening");
      await sleep(300); // let the tone finish so it is not heard as speech
    }
    listening = !manual;
    setState();
    let text = "";
    const began = performance.now();
    try {
      text = await capture();
      failures = 0;
    } catch (error) {
      log(`! ${error.message}`);
      failures += 1;
      if (failures === 3) {
        speak({
          text: "I can't hear you. Check the browser's microphone permission.",
          priority: "task",
          lang,
        });
      }
      await sleep(1000);
    }
    listening = false;
    tts.hold(false);
    setState();

    if (!text) {
      announce = false;
      continue;
    }
    announce = true;
    log(`> [${stt.engine}, ${Math.round(performance.now() - began)} ms] ${text}`);
    if (!connected && !mock && /^(repeat|say again)\b/i.test(text)) {
      tts.repeat();
    } else if (!connected && !mock) {
      speak({ text: "I'm not connected right now. Please try again in a moment.", priority: "task", lang });
    } else {
      pendingReply = true;
      send({ type: "utterance", text, lang, session_id: session?.session_id });
    }
  }
}

// ---- Start ----

// Browsers only allow sound after a tap or key press on the page. The sign-in page's tap usually
// carries over when it hands off to this page; if not, one tap here starts everything.
async function startEarpiece() {
  if (started || redirecting) return;
  started = true;
  overlay.hidden = true;
  audioContext ??= new AudioContext();
  await audioContext.resume().catch(() => {});
  if (!TextToSpeech.isSupported() || (!SpeechToText.isSupported() && !useModelStt)) {
    nameLabel.textContent = "This browser has no speech support. Use Chrome.";
    return;
  }
  speak({
    text: session
      ? "You are inside. Say a command, for example, fix server A."
      : "Earpiece ready.",
    priority: "info",
    lang,
  });
  if (!mock) connect();
  setState();
  loadModels();
  conversationLoop();
}

overlay.addEventListener("click", startEarpiece);
window.addEventListener("keydown", () => {
  if (!overlay.hidden) startEarpiece();
});

audioContext = new AudioContext();
if (audioContext.state === "running") startEarpiece(); // the browser let us start without a tap
