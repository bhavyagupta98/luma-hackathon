// Voice start menu: the page says its options aloud ("register voice" or "sign in"), listens, and
// sends the person to the matching page. Nothing needs to be pressed after the first tap.
//
// URL params: ?device=DC-D-100   &stt=browser|model, &tts=browser|model, &debug=1 and &manual=1 are
//             passed on to the next page.

import { parseChoice } from "./choice.js";
import { SpeechToText } from "./stt.js";
import { BrowserVoice, TextToSpeech } from "./tts.js";

const params = new URLSearchParams(location.search);
const deviceId = params.get("device") || "DC-D-100";
const debug = params.has("debug");

const dot = document.getElementById("dot");
const statusLine = document.getElementById("status");
const hint = document.getElementById("hint");
const overlay = document.getElementById("overlay");
const logView = document.getElementById("log");
logView.hidden = !debug;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const recognizer = new SpeechToText({ lang: "en-US" });
const waiting = new Map();
const tts = new TextToSpeech({
  voice: new BrowserVoice(),
  onSpoken: (item) => {
    waiting.get(item.id)?.();
    waiting.delete(item.id);
  },
});

let audioContext = null;
let spokenCount = 0;
let started = false;

const OPTIONS = "Say register voice, or say sign in.";
const PAGES = {
  register: { page: "auth.html", extra: { enroll: "1" }, line: "Okay, let's register you." },
  signin: { page: "auth.html", extra: {}, line: "Okay, let's sign you in." },
};

function setState(next, text) {
  dot.dataset.state = next;
  if (text) statusLine.textContent = text;
}

function log(line) {
  if (!debug) return;
  logView.textContent = `${new Date().toLocaleTimeString()} ${line}\n${logView.textContent}`
    .split("\n")
    .slice(0, 40)
    .join("\n");
}

function speak(text) {
  spokenCount += 1;
  const id = `local-${spokenCount}`;
  const done = new Promise((resolve) => waiting.set(id, resolve));
  tts.speak({ id, text, priority: "task", lang: "en-US" });
  return done;
}

function cue(kind) {
  if (!audioContext) return;
  const tones = { listening: [[880, 0.12]], error: [[140, 0.25]], ok: [[523, 0.12], [784, 0.2]] }[kind];
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

function pageUrl(choice) {
  const { page, extra } = PAGES[choice];
  const next = new URLSearchParams({ device: deviceId, ...extra });
  for (const key of ["debug", "stt", "tts", "manual"]) {
    if (params.has(key)) next.set(key, params.get(key));
  }
  return `${page}?${next}`;
}

async function menu() {
  await speak(`Welcome to Luma. ${OPTIONS}`);
  let misses = 0;
  let failures = 0;
  while (true) {
    await sleep(350); // the speaker's tail must not be heard as the answer
    cue("listening");
    await sleep(300); // let the tone finish so it is not heard as speech
    setState("recording", "Listening…");
    let heard = "";
    tts.hold(true);
    try {
      heard = await recognizer.listenOnce();
      failures = 0;
    } catch (error) {
      log(`! ${error.message}`);
      failures += 1;
    }
    tts.hold(false);

    const choice = parseChoice(heard);
    log(`heard: "${heard}" -> "${choice}"`);
    if (choice) {
      setState("verified", choice === "register" ? "Registering" : "Signing in");
      cue("ok");
      await speak(PAGES[choice].line);
      location.href = pageUrl(choice);
      return;
    }

    if (failures >= 3) {
      setState("refused", "Microphone problem");
      await speak("I can't hear you. Check the browser's microphone permission.");
      failures = 0;
    } else if (heard) {
      // Heard something, but not an option.
      cue("error");
      setState("refused", "Try again");
      misses += 1;
      await speak(misses === 1 ? `Sorry, I didn't get that. ${OPTIONS}` : OPTIONS);
    } else {
      // Silence: keep listening quietly, and repeat the options now and then.
      misses += 1;
      if (misses % 2 === 0) await speak(OPTIONS);
    }
    setState("ready", "Say what you want");
  }
}

// Browsers only allow sound and the microphone after a tap or key press on the page, so the
// first visit needs one. The demo launcher performs it automatically.
async function begin() {
  if (started) return;
  started = true;
  overlay.hidden = true;
  audioContext ??= new AudioContext();
  await audioContext.resume().catch(() => {});
  if (!SpeechToText.isSupported()) {
    setState("refused", "Please use Chrome");
    hint.textContent = "This browser has no speech recognition.";
    await speak("This browser can't hear you. Please open it in Chrome.");
    return;
  }
  setState("ready", "Say what you want");
  menu();
}

overlay.addEventListener("click", begin);
window.addEventListener("keydown", () => {
  if (!overlay.hidden) begin();
});

audioContext = new AudioContext();
if (audioContext.state === "running") begin(); // the browser let us start without a tap
