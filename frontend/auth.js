// Voice sign-in: record a phrase, turn it into a speaker embedding in the browser,
// and send only the embedding to the backend for verification (docs/CONTRACT.md,
// "Voice authentication"). On success, hands off to the text-command earpiece.
//
// URL params:
//   ?device=DC-D-100            trusted device id (the backend derives the operator from it)
//   &enroll=1&operator=OP-100   record 3 phrases and export an enrollment file
//   &mock=1                     verify locally against this browser's enrollment (no backend)
//   &threshold=0.86             mock-mode match threshold
//   &debug=1                    show scores, timings and clip downloads

import { encodeWav, VoiceRecorder } from "./recorder.js";
import { TextToSpeech } from "./tts.js";
import {
  averageEmbeddings,
  cosineSimilarity,
  DEFAULT_MATCH_THRESHOLD,
  EMBEDDING_DIMENSIONS,
  EMBEDDING_DTYPE,
  EMBEDDING_MODEL,
  toWire,
  VoiceEmbedder,
} from "./voice-embedding.js";

const params = new URLSearchParams(location.search);
const deviceId = params.get("device") || "DC-D-100";
const operatorId = params.get("operator") || "OP-100";
const enrolling = params.has("enroll");
const mock = params.has("mock");
const debug = params.has("debug");
const threshold = Number(params.get("threshold") || DEFAULT_MATCH_THRESHOLD);

const SIGN_IN_PHRASE = "My voice is my badge. Verify me.";
const ENROLL_PHRASES = [
  "My voice is my badge. Verify me.",
  "Server room access for the night shift.",
  "The quick brown fox jumps over the lazy dog.",
];
const CLIP_ERRORS = {
  silence: "I didn't hear anything. Hold the button while you speak.",
  "too-short": "That was too short. Hold the button and say the whole phrase.",
  empty: "The recording was empty. Please try again.",
};

const dot = document.getElementById("dot");
const statusLine = document.getElementById("status");
const overlay = document.getElementById("overlay");
const logView = document.getElementById("log");
logView.hidden = !debug;
overlay.textContent = enrolling ? "Tap to start voice enrollment" : "Tap to start voice sign-in";

const recorder = new VoiceRecorder();
const embedder = new VoiceEmbedder();
const waiting = new Map();
const tts = new TextToSpeech({
  onSpoken: (item) => {
    waiting.get(item.id)?.();
    waiting.delete(item.id);
  },
});

let state = "idle"; // idle | loading | ready | recording | processing | verified | refused
let audioContext = null;
let spokenCount = 0;
const enrollmentEmbeddings = [];

// ---- Feedback ----

function setState(next, text) {
  state = next;
  dot.dataset.state = next;
  if (text) statusLine.textContent = text;
}

function log(line, link) {
  if (!debug) return;
  const row = document.createElement("div");
  row.textContent = `${new Date().toLocaleTimeString()} ${line} `;
  if (link) row.append(link);
  logView.prepend(row);
}

function speak(text, priority = "task") {
  spokenCount += 1;
  const id = `local-${spokenCount}`;
  const done = new Promise((resolve) => waiting.set(id, resolve));
  tts.speak({ id, text, priority, lang: "en-US" });
  return done;
}

function cue(kind) {
  if (!audioContext) return;
  const tones = {
    listening: [[880, 0.12]],
    error: [[140, 0.25]],
    verified: [[523, 0.12], [784, 0.2]],
  }[kind];
  let at = audioContext.currentTime;
  for (const [frequency, length] of tones) {
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = kind === "error" ? "square" : "sine";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.2, at + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start(at);
    oscillator.stop(at + length + 0.02);
    at += length;
  }
}

function prompt() {
  return enrolling
    ? `Phrase ${enrollmentEmbeddings.length + 1} of ${ENROLL_PHRASES.length}. Hold the button and say: ${
        ENROLL_PHRASES[enrollmentEmbeddings.length]
      }`
    : `Hold the button and say: ${SIGN_IN_PHRASE}`;
}

// ---- Local profile (mock mode only; the real profile lives on the backend) ----

function profileKey() {
  return `luma.voiceProfile.${deviceId}`;
}

function loadProfile() {
  try {
    return JSON.parse(localStorage.getItem(profileKey()));
  } catch {
    return null;
  }
}

function saveProfile(profile) {
  try {
    localStorage.setItem(profileKey(), JSON.stringify(profile));
  } catch {
    log("! could not save the profile in this browser");
  }
}

function download(name, blob) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.textContent = name;
  return link;
}

// ---- Backend ----

function verifyLocally(embedding) {
  const profile = loadProfile();
  if (!profile || profile.embedding_model !== EMBEDDING_MODEL) {
    return {
      type: "auth_result",
      authenticated: false,
      code: "VOICE_NOT_ENROLLED",
      spoken_message: "No voice profile is enrolled on this device. Enroll first.",
    };
  }
  const score = cosineSimilarity(profile.centroid, embedding);
  const authenticated = score >= threshold;
  return {
    type: "auth_result",
    authenticated,
    code: authenticated ? "VOICE_AUTHENTICATED" : "VOICE_NOT_MATCHED",
    spoken_message: authenticated
      ? `Voice verified. Welcome, ${profile.name || profile.operator_id}.`
      : "I couldn't verify your voice. Please try again.",
    similarity_score: Math.round(score * 1e4) / 1e4,
    operator: { id: profile.operator_id, name: profile.name || profile.operator_id },
    authentication_token: authenticated ? `mock-${crypto.randomUUID()}` : null,
    expires_at: authenticated ? Math.floor(Date.now() / 1000) + 60 : null,
  };
}

function verifyWithBackend(request, timeoutMs = 15_000) {
  return new Promise((resolve, reject) => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/ws/${encodeURIComponent(deviceId)}`);
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error("The server didn't answer."));
    }, timeoutMs);
    socket.onopen = () => socket.send(JSON.stringify(request));
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type !== "auth_result") return; // e.g. the initial hello
      clearTimeout(timer);
      socket.close();
      resolve(message);
    };
    socket.onerror = () => {
      clearTimeout(timer);
      reject(new Error("I couldn't reach the server."));
    };
  });
}

// ---- Flow ----

async function handleClip() {
  setState("processing", "Checking…");
  const clip = await recorder.stop();
  if (clip.error) {
    cue("error");
    log(`! clip rejected: ${clip.error}`);
    setState("ready", prompt());
    await speak(CLIP_ERRORS[clip.error] ?? "Please try again.");
    return;
  }

  const started = performance.now();
  const embedding = await embedder.embed(clip.samples);
  const embedMs = Math.round(performance.now() - started);
  log(
    `clip ${clip.durationSeconds.toFixed(2)} s, rms ${clip.rms.toFixed(3)}, embedded in ${embedMs} ms`,
    download(`clip-${Date.now()}.wav`, encodeWav(clip.samples)),
  );

  if (enrolling) await handleEnrollmentClip(embedding);
  else await handleSignInClip(embedding, clip);
}

async function handleEnrollmentClip(embedding) {
  if (enrollmentEmbeddings.length > 0) {
    const score = cosineSimilarity(enrollmentEmbeddings[0], embedding);
    log(`similarity to phrase 1: ${score.toFixed(4)}`);
  }
  enrollmentEmbeddings.push(embedding);
  if (enrollmentEmbeddings.length < ENROLL_PHRASES.length) {
    setState("ready", prompt());
    await speak(`Got it. ${prompt()}`);
    return;
  }

  const profile = {
    operator_id: operatorId,
    name: params.get("name") || "",
    device_id: deviceId,
    embedding_model: EMBEDDING_MODEL,
    embedding_dtype: EMBEDDING_DTYPE,
    dimensions: EMBEDDING_DIMENSIONS,
    created_at: new Date().toISOString(),
    embeddings: enrollmentEmbeddings.map(toWire),
    centroid: toWire(averageEmbeddings(enrollmentEmbeddings)),
  };
  saveProfile(profile);
  const file = download(
    `voice-enrollment-${operatorId}.json`,
    new Blob([JSON.stringify(profile)], { type: "application/json" }),
  );
  file.click(); // hands the embeddings to the backend team's local enrollment step
  log("enrollment saved", file);
  setState("verified", "Enrollment complete");
  cue("verified");
  await speak("Enrollment complete. Your voice profile has been saved.");
}

async function handleSignInClip(embedding, clip) {
  const request = {
    type: "voice_auth",
    device_id: deviceId,
    embedding: toWire(embedding),
    embedding_model: EMBEDDING_MODEL,
    embedding_dtype: EMBEDDING_DTYPE,
    dimensions: EMBEDDING_DIMENSIONS,
    normalized: true,
    duration_s: Math.round(clip.durationSeconds * 100) / 100,
    sample_rate: 16_000,
  };

  let result;
  try {
    result = mock ? verifyLocally(embedding) : await verifyWithBackend(request);
  } catch (error) {
    cue("error");
    setState("ready", prompt());
    await speak(`${error.message} Please try again.`);
    return;
  }
  log(`${result.code} score=${result.similarity_score ?? "n/a"}`);

  if (!result.authenticated) {
    cue("error");
    setState("refused", "Not verified");
    await speak(result.spoken_message || "I couldn't verify your voice. Please try again.");
    setState("ready", prompt());
    return;
  }

  cue("verified");
  setState("verified", `Verified${result.operator?.name ? `: ${result.operator.name}` : ""}`);
  try {
    sessionStorage.setItem(
      "luma.voiceSession",
      JSON.stringify({
        device_id: deviceId,
        operator: result.operator ?? null,
        authentication_token: result.authentication_token ?? null,
        expires_at: result.expires_at ?? null,
      }),
    );
  } catch {
    log("! could not store the session in this browser");
  }
  await speak(result.spoken_message || "Voice verified.");
  const next = new URLSearchParams({ device: deviceId });
  if (mock) next.set("mock", "1");
  if (debug) next.set("debug", "1");
  location.href = `ear.html?${next}`;
}

// ---- Push to talk ----

function pressTalk() {
  if (state !== "ready") return;
  tts.hold(true);
  recorder.start();
  cue("listening");
  setState("recording", "Listening…");
}

async function releaseTalk() {
  if (state !== "recording") return;
  tts.hold(false);
  try {
    await handleClip();
  } catch (error) {
    console.error(error);
    cue("error");
    setState("ready", prompt());
    await speak("Something went wrong. Please try again.");
  }
}

window.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.repeat || !overlay.hidden) return;
  event.preventDefault();
  pressTalk();
});
window.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || !overlay.hidden) return;
  event.preventDefault();
  releaseTalk();
});
document.querySelector("main").addEventListener("pointerdown", pressTalk);
window.addEventListener("pointerup", releaseTalk);
window.addEventListener("pointercancel", releaseTalk);

async function begin() {
  if (!overlay.hidden) overlay.hidden = true;
  else return;
  audioContext = new AudioContext();
  setState("loading", "Loading the voice model…");
  const loading = speak("Loading the voice model. The first time takes a minute.", "info");
  try {
    await recorder.open();
    await embedder.load((percent) => setState("loading", `Loading the voice model… ${Math.round(percent)}%`));
  } catch (error) {
    console.error(error);
    setState("refused", "Microphone or voice model unavailable");
    await speak("I couldn't start the microphone or the voice model. Check microphone permission and reload.");
    return;
  }
  await loading;
  setState("ready", prompt());
  await speak(enrolling ? `Voice enrollment for ${operatorId}. ${prompt()}` : prompt());
}

overlay.addEventListener("click", begin);
overlay.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") begin();
});
