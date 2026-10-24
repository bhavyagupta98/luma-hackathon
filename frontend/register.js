import { VoiceRecorder } from "./recorder.js";
import { STT_MODELS, WhisperTranscriber } from "./speech-models.js";
import { EMBEDDING_MODEL, toWire, VoiceEmbedder } from "./voice-embedding.js";

const PASSPHRASE = "my voice is my badge authorize datacenter access";
const people = ["AB", "BG"];
const recorder = new VoiceRecorder();
const embedder = new VoiceEmbedder();
const transcriber = new WhisperTranscriber({ model: STT_MODELS.base });
const button = document.getElementById("record");
const personLabel = document.getElementById("person");
const status = document.getElementById("status");
let index = 0;
let ready = false;
let recording = false;
let loading = false;

function normalizedWords(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
}

async function prepare() {
  if (ready || loading) return;
  loading = true;
  button.disabled = true;
  const progress = { voice: 0, transcription: 0 };
  const report = (name) => (percent) => {
    progress[name] = Math.round(percent);
    status.textContent = `Loading models: voice ${progress.voice}%, transcription ${progress.transcription}%`;
  };
  try {
    await recorder.open();
    await Promise.all([
      embedder.load(report("voice")),
      transcriber.load(report("transcription")),
    ]);
    ready = true;
    status.textContent = `Ready for ${people[index]}. Press and hold while speaking.`;
  } finally {
    loading = false;
    button.disabled = false;
  }
}

async function start(event) {
  event.preventDefault();
  try {
    if (!ready) {
      await prepare();
      return;
    }
    if (recording || index >= people.length) return;
    recording = true;
    recorder.start();
    status.textContent = `Listening to ${people[index]}…`;
  } catch (error) {
    status.textContent = `Could not start: ${error.message}`;
    button.disabled = false;
  }
}

async function stop(event) {
  event.preventDefault();
  if (!recording) return;
  recording = false;
  button.disabled = true;
  status.textContent = "Checking the passphrase and voice…";
  try {
    const clip = await recorder.stop();
    if (clip.error) throw new Error("The recording was too short or silent. Please try again.");
    const [transcript, embedding] = await Promise.all([
      transcriber.transcribe(clip.samples), embedder.embed(clip.samples),
    ]);
    if (normalizedWords(transcript) !== PASSPHRASE) {
      throw new Error(`Heard “${transcript || "nothing"}”. Please say the exact passphrase.`);
    }
    const response = await fetch("/api/local-register-voice", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        person: people[index], transcript, embedding: toWire(embedding),
        embedding_model: EMBEDDING_MODEL,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Registration failed. Please try again.");
    index += 1;
    if (index === people.length) {
      personLabel.textContent = "complete";
      button.textContent = "Both voices registered";
      status.textContent = "AB and BG are registered as organization administrators.";
      return;
    }
    personLabel.textContent = people[index];
    button.textContent = `Hold to record ${people[index]}`;
    status.textContent = `${result.spoken_message} Ready for ${people[index]}.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    if (index < people.length) button.disabled = false;
  }
}

button.addEventListener("pointerdown", start);
window.addEventListener("pointerup", stop);
window.addEventListener("pointercancel", stop);
