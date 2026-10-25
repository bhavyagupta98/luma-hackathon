// Text to speech: speaks gateway replies through a swappable voice:
//   ModelVoice   - on-device MMS-TTS model played through WebAudio (falls back to BrowserVoice
//                  until the model has loaded, for non-English text, and on errors).
//   BrowserVoice - the browser speechSynthesis API.
// TextToSpeech follows the priority rules in docs/CONTRACT.md: warnings and emergencies
// interrupt, everything else queues, and only emergencies play while push-to-talk is held.

import { VitsSynthesizer } from "./speech-models.js";

const RANK = { info: 0, task: 1, warning: 2, emergency: 3 };

function rankOf(item) {
  return RANK[item.priority] ?? RANK.task;
}

function splitSentences(text) {
  return text.match(/[^.!?]+[.!?]*/g)?.map((part) => part.trim()).filter(Boolean) ?? [text];
}

export class BrowserVoice {
  // Chrome cuts off long utterances, so the queue feeds this voice sentence by sentence.
  splitsSentences = true;

  constructor() {
    this._voices = speechSynthesis.getVoices();
    speechSynthesis.addEventListener("voiceschanged", () => {
      this._voices = speechSynthesis.getVoices();
    });
  }

  get engine() {
    return "browser";
  }

  async prepare() {}

  say(text, { lang = "en-US", rate = 1.05 } = {}) {
    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.rate = rate;
      const voice = this._voiceFor(lang);
      if (voice) utterance.voice = voice;
      // Some browsers never fire onend (no voices installed, or a stalled engine); don't wait forever.
      const words = text.trim().split(/\s+/).length;
      const fallback = setTimeout(resolve, 3000 + (words * 400) / rate);
      const done = () => {
        clearTimeout(fallback);
        resolve();
      };
      utterance.onend = done;
      utterance.onerror = done; // also fires on cancel()
      speechSynthesis.speak(utterance);
    });
  }

  cancel() {
    speechSynthesis.cancel();
  }

  _voiceFor(lang) {
    const exact = this._voices.filter((voice) => voice.lang === lang);
    const family = this._voices.filter((voice) => voice.lang.startsWith(lang.split("-")[0]));
    const pool = exact.length ? exact : family;
    return (
      pool.find((voice) => /natural|neural|google/i.test(voice.name)) ??
      pool.find((voice) => voice.localService) ??
      pool[0] ??
      null
    );
  }
}

export class ModelVoice {
  // One synthesis call per message avoids audible gaps between generated sentences.
  splitsSentences = false;

  constructor({ fallback = new BrowserVoice() } = {}) {
    this._synthesizer = new VitsSynthesizer();
    this._fallback = fallback;
    this._context = null;
    this._source = null;
    this._finish = null;
    this._generation = 0;
  }

  get engine() {
    return this._synthesizer.ready ? "model" : "browser (model loading)";
  }

  // Call from a user gesture so the AudioContext may start.
  async prepare(onProgress) {
    this._context ??= new AudioContext();
    await this._synthesizer.load(onProgress);
  }

  async say(text, { lang = "en-US", rate = 1.05 } = {}) {
    if (!this._synthesizer.ready || !lang.startsWith("en")) {
      return this._fallback.say(text, { lang, rate });
    }
    const generation = this._generation;
    let speech;
    try {
      speech = await this._synthesizer.synthesize(text);
    } catch (error) {
      console.error(error);
      return this._fallback.say(text, { lang, rate });
    }
    if (generation !== this._generation) return; // cancelled while generating

    this._context ??= new AudioContext();
    // A context created without a recent click starts suspended and would play nothing, forever.
    await this._context.resume().catch(() => {});
    if (this._context.state !== "running") return this._fallback.say(text, { lang, rate });
    const buffer = this._context.createBuffer(1, speech.audio.length, speech.samplingRate);
    buffer.copyToChannel(speech.audio, 0);
    const source = this._context.createBufferSource();
    source.buffer = buffer;
    source.connect(this._context.destination);
    this._source = source;
    await new Promise((resolve) => {
      this._finish = resolve;
      source.onended = resolve;
      source.start();
      // If playback stalls, don't leave the page waiting for a sound that never ends.
      setTimeout(resolve, (buffer.duration + 2) * 1000);
    });
    if (this._source === source) this._source = null;
  }

  cancel() {
    this._generation += 1;
    this._fallback.cancel();
    const source = this._source;
    this._source = null;
    if (!source) return;
    source.onended = null;
    try {
      source.stop();
    } catch {
      // already stopped
    }
    this._finish?.();
  }
}

export class TextToSpeech {
  static isSupported() {
    return "speechSynthesis" in window || "AudioContext" in window;
  }

  constructor({ voice = new BrowserVoice(), rate = 1.05, onSpoken = () => {} } = {}) {
    this.voice = voice;
    this.rate = rate;
    this.onSpoken = onSpoken;
    this.lastSpoken = null;
    this._queue = [];
    this._current = null;
    this._held = false;
  }

  get speaking() {
    return this._current !== null;
  }

  // message: {id?, text, lang?, priority?}
  speak(message) {
    const item = { lang: "en-US", priority: "task", ...message };
    if (!item.text) return;
    if (rankOf(item) >= RANK.warning) {
      if (rankOf(item) === RANK.emergency) {
        // Drop routine chatter; nothing else matters during an emergency.
        this._queue = this._queue.filter((queued) => rankOf(queued) >= RANK.warning);
      }
      this._queue.unshift(item);
      this._interrupt();
    } else {
      this._queue.push(item);
    }
    this._drain();
  }

  repeat() {
    if (this.lastSpoken) this.speak({ ...this.lastSpoken, priority: "task" });
  }

  // While held (push-to-talk pressed), stop talking over the operator and hold the queue.
  hold(held) {
    this._held = held;
    if (held && this._current && rankOf(this._current) < RANK.emergency) this._interrupt();
    if (!held) this._drain();
  }

  cancelAll() {
    this._queue = [];
    this._interrupt();
  }

  _interrupt() {
    if (!this._current) return;
    this._current = null;
    this.voice.cancel();
  }

  _drain() {
    if (this._current || this._queue.length === 0) return;
    const next = this._held
      ? this._queue.find((queued) => rankOf(queued) === RANK.emergency)
      : this._queue[0];
    if (!next) return;
    this._queue.splice(this._queue.indexOf(next), 1);
    this._current = next;
    // A short delay lets a preceding cancel() settle; Chrome can drop speak() right after it.
    setTimeout(() => this._play(next), 60);
  }

  async _play(item) {
    const parts = this.voice.splitsSentences ? splitSentences(item.text) : [item.text];
    const chunks = rankOf(item) === RANK.emergency ? [...parts, ...parts] : parts;
    for (const chunk of chunks) {
      if (this._current !== item) return; // interrupted
      await this.voice.say(chunk, { lang: item.lang, rate: this.rate });
    }
    if (this._current !== item) return;
    this._current = null;
    this.lastSpoken = item;
    this.onSpoken(item);
    this._drain();
  }
}
