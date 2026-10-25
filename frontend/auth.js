// Voice sign-in, hands-free: the page speaks a prompt, plays a soft tone, listens until the person
// has finished speaking, and sends the recording to the gateway, which verifies the speaker against
// the enrolled voice profile and returns the worker's role and permissions. On success the worker
// hears "<name> is authenticated." and the page hands over to the voice-command earpiece (ear.html)
// with a 60-second session. Nothing needs to be pressed after the first tap that starts the page.
//
// URL params: ?device=DC-D-100  (trusted device; the backend derives the operator from it)
//             &enroll=1   say your name, then 3 phrases, and save them as this device's voice
//                         profile (demo only: the gateway must run with LUMA_ALLOW_BROWSER_ENROLL=1)
//             &manual=1   hold Space / press and hold the button to talk instead of auto-listening
//             &tts=model   speak with the on-device voice model instead of the browser voice
//                          (default is the browser voice: the model runs on the page's main
//                          thread and freezes the page while it generates speech)
//             &debug=1

import { parseName } from "./name.js";
import { blobToBase64, encodeWav, VoiceRecorder } from "./recorder.js";
import { SpeechToText } from "./stt.js";
import { BrowserVoice, ModelVoice, TextToSpeech } from "./tts.js";

const params = new URLSearchParams(location.search);
const deviceId = params.get("device") || "DC-D-100";
const debug = params.has("debug");
const enrolling = params.has("enroll");
const manual = params.has("manual");
const useModelTts = params.get("tts") === "model";

export const SESSION_KEY = "luma.voiceSession";

const SAY = manual ? "Hold the button and say:" : "Please say:";
const SIGN_IN_PROMPT = `${SAY} this is my voice, please let me in.`;
const ENROLL_PHRASES = [
  "My voice is my badge, please verify me.",
  "I am here to work on the servers tonight.",
  "The quick brown fox jumps over the lazy dog.",
];
const CLIP_ERRORS = {
  silence: "I didn't hear anything.",
  "too-short": "That was too short.",
  empty: "The recording was empty.",
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const dot = document.getElementById("dot");
const statusLine = document.getElementById("status");
const hint = document.getElementById("hint");
const overlay = document.getElementById("overlay");
const logView = document.getElementById("log");
logView.hidden = !debug;
if (manual) document.body.classList.add("manual");
hint.textContent = manual
  ? "Press and hold the button, or hold Space, to speak"
  : "Just speak after the tone. Nothing to press.";

const recorder = new VoiceRecorder();
const waiting = new Map();
const tts = new TextToSpeech({
  voice: useModelTts ? new ModelVoice() : new BrowserVoice(),
  onSpoken: (item) => {
    waiting.get(item.id)?.();
    waiting.delete(item.id);
  },
});

let state = "idle"; // idle | loading | ready | recording | processing | verified | refused
let audioContext = null;
let spokenCount = 0;
let finished = false; // set once the page is about to hand over, so the loop stops
const enrollmentClips = [];

// Enrollment starts by asking for the worker's name. The browser's speech recognition turns it
// into text (the name audio is not used as a voice sample); without it, the name is left as is.
const nameRecognizer = new SpeechToText({ lang: "en-US" });
const asksForName = enrolling && SpeechToText.isSupported();
let enrollmentName = null;

function collectingName() {
  return asksForName && enrollmentName === null;
}

function prompt() {
  if (collectingName()) return `First, tell me your name. ${SAY} My name is, and then your name.`;
  if (!enrolling) return SIGN_IN_PROMPT;
  return `Phrase ${enrollmentClips.length + 1} of ${ENROLL_PHRASES.length}. ${SAY} ${
    ENROLL_PHRASES[enrollmentClips.length]
  }`;
}

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

// ---- Gateway ----

// Opens a short-lived socket, sends one message, and resolves with the gateway's reply of
// type `replyType` (ignoring the initial hello).
function request(message, replyType, timeoutMs = 60_000) {
  return new Promise((resolve, reject) => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/ws/${encodeURIComponent(deviceId)}`);
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error("The server didn't answer."));
    }, timeoutMs);
    socket.onopen = () => socket.send(JSON.stringify(message));
    socket.onmessage = (event) => {
      const reply = JSON.parse(event.data);
      if (reply.type !== replyType) return;
      clearTimeout(timer);
      socket.close();
      resolve(reply);
    };
    socket.onerror = () => {
      clearTimeout(timer);
      reject(new Error("I couldn't reach the server."));
    };
  });
}

function storeSession(result) {
  const session = {
    session_id: result.session_id,
    device_id: deviceId,
    operator: result.operator,
    role: result.role,
    permissions: result.permissions,
    expires_at: Date.now() + result.expires_in * 1000,
  };
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    log("! could not store the session in this browser");
  }
}

function nextPageUrl(page) {
  const next = new URLSearchParams({ device: deviceId });
  for (const key of ["debug", "tts", "stt", "manual"]) {
    if (params.has(key)) next.set(key, params.get(key));
  }
  return `${page}?${next}`;
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

// ---- One round: speak the prompt, listen, handle what was heard ----

// Resolves with {clip} (audio) or {heard} (the name step, already transcribed).
async function listen() {
  tts.hold(true); // nothing else is spoken while we listen
  try {
    if (!collectingName() && manual) {
      const letGo = released();
      await pressed();
      recorder.start();
      cue("listening");
      setState("recording", "Listening…");
      await letGo;
      return { clip: await recorder.stop() };
    }
    cue("listening");
    await sleep(300); // let the tone finish so it is not recorded as speech
    setState("recording", "Listening…");
    if (collectingName()) {
      try {
        return { heard: await nameRecognizer.listenOnce() };
      } catch (error) {
        log(`! name recognition failed: ${error.message}`);
        return { heard: "" };
      }
    }
    return { clip: await recorder.listen() };
  } finally {
    tts.hold(false);
  }
}

async function conversation() {
  await speak(
    enrolling
      ? "Welcome. Let's get you registered."
      : "Welcome. Please verify your voice to go inside.",
  );
  while (!finished) {
    setState("ready", prompt());
    await speak(prompt());
    await sleep(350); // the speaker's tail must not be heard as the answer
    if (finished) return;
    const heard = await listen();
    setState("processing", "Checking…");
    try {
      if (heard.heard !== undefined) await handleName(heard.heard);
      else await handleClip(heard.clip);
    } catch (error) {
      console.error(error);
      cue("error");
      await speak("Something went wrong. Please try again.");
    }
  }
}

async function handleName(heard) {
  const name = parseName(heard);
  log(`name heard: "${heard}" -> "${name}"`);
  if (!name) {
    cue("error");
    await speak("I didn't catch your name.");
    return;
  }
  enrollmentName = name;
  cue("verified");
  await speak(`Nice to meet you, ${name}.`);
}

async function handleClip(clip) {
  if (clip.error) {
    cue("error");
    log(`! clip rejected: ${clip.error}`);
    await speak(CLIP_ERRORS[clip.error] ?? "Please try again.");
    return;
  }
  log(`clip ${clip.durationSeconds.toFixed(2)} s, rms ${clip.rms.toFixed(3)}`);
  const audio = await blobToBase64(encodeWav(clip.samples));
  if (enrolling) await handleEnrollmentClip(audio);
  else await handleSignIn(audio);
}

async function handleEnrollmentClip(audio) {
  enrollmentClips.push(audio);
  if (enrollmentClips.length < ENROLL_PHRASES.length) {
    cue("verified");
    await speak("Got it.");
    return;
  }
  setState("processing", "Saving your voice…");
  let result;
  try {
    result = await request(
      { type: "voice_enroll", name: enrollmentName ?? undefined, clips: enrollmentClips },
      "enroll_result",
    );
  } catch (error) {
    result = {
      enrolled: false,
      code: "NO_SERVER",
      spoken_message: `${error.message} Please try again.`,
    };
  }
  log(`enroll: ${result.code}`);
  if (!result.enrolled) {
    // Start over so a bad clip cannot poison the next attempt.
    enrollmentClips.length = 0;
    if (result.code === "INVALID_NAME") enrollmentName = null;
    cue("error");
    setState("refused", "Not enrolled");
    await speak(result.spoken_message);
    return;
  }
  finished = true;
  cue("verified");
  setState("verified", "Voice enrolled");
  await speak(result.spoken_message); // "<name>, you are enrolled."
  location.href = nextPageUrl("auth.html"); // straight on to signing in
}

async function handleSignIn(audio) {
  let result;
  try {
    result = await request({ type: "voice_auth", audio_wav_base64: audio }, "auth_result");
  } catch (error) {
    cue("error");
    await speak(`${error.message} Please try again.`);
    return;
  }
  log(`${result.code} score=${result.similarity_score ?? "n/a"}`);

  if (!result.authenticated) {
    cue("error");
    setState("refused", "Not verified");
    await speak(result.spoken_message || "You are not registered.");
    return;
  }

  finished = true;
  cue("verified");
  setState("verified", result.operator?.name ?? "Verified");
  hint.textContent = `${result.role} · ${result.permissions.servers.join(", ") || "no servers"}`;
  storeSession(result);
  await speak(result.spoken_message); // "<name> is authenticated."
  location.href = nextPageUrl("ear.html");
}

// ---- Start ----

let started = false;

// Browsers only allow sound and the microphone after a tap or key press on the page, so the
// first visit needs one. Later pages that the browser lets start by themselves skip it.
async function begin() {
  if (started) return;
  started = true;
  overlay.hidden = true;
  audioContext ??= new AudioContext();
  await audioContext.resume().catch(() => {});
  setState("loading", "Starting the microphone…");
  try {
    await recorder.open();
  } catch (error) {
    console.error(error);
    setState("refused", "Microphone unavailable");
    await speak("I couldn't start the microphone. Check microphone permission and reload.");
    return;
  }
  // The speech model loads in the background; the browser voice speaks until it is ready.
  if (useModelTts) tts.voice.prepare().catch((error) => log(`! speech model: ${error.message}`));
  conversation();
}

overlay.addEventListener("click", begin);
window.addEventListener("keydown", () => {
  if (!overlay.hidden) begin();
});

audioContext = new AudioContext();
if (audioContext.state === "running") begin(); // the browser let us start without a tap
