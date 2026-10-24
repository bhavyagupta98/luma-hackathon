// Speech to text, push to talk. Two engines share one interface (prepare/start/stop/abort):
//   ModelSpeechToText - on-device Whisper; audio never leaves the browser.
//   SpeechToText      - the browser Web Speech API (Chrome sends audio to Google); used as fallback.

import { VoiceRecorder } from "./recorder.js";
import { STT_MODELS, WhisperTranscriber } from "./speech-models.js";

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

export class ModelSpeechToText {
  constructor({ model = STT_MODELS.base } = {}) {
    // Commands can be a single word ("stop"), so accept much shorter clips than sign-in does.
    this._recorder = new VoiceRecorder({ minSeconds: 0.3, maxSeconds: 25 });
    this._whisper = new WhisperTranscriber({ model });
  }

  get engine() {
    return "model";
  }

  get listening() {
    return this._recorder.recording;
  }

  async prepare(onProgress) {
    await this._recorder.open();
    await this._whisper.load(onProgress);
  }

  start() {
    this._recorder.start();
  }

  // Resolves with the transcript ("" when the clip was silent or too short).
  async stop() {
    const clip = await this._recorder.stop();
    if (clip.error) return "";
    return this._whisper.transcribe(clip.samples);
  }

  abort() {
    if (this._recorder.recording) this._recorder.stop();
  }
}

export class SpeechToText {
  static isSupported() {
    return Boolean(Recognition);
  }

  get engine() {
    return "browser";
  }

  async prepare() {}

  constructor({ lang = "en-US", onInterim = () => {} } = {}) {
    this.lang = lang;
    this.onInterim = onInterim;
    this._recognition = null;
    this._ended = Promise.resolve();
    this._finalText = "";
    this._interimText = "";
    this._error = null;
  }

  get listening() {
    return this._recognition !== null;
  }

  start() {
    if (!Recognition) throw new Error("Speech recognition is not supported in this browser.");
    if (this._recognition) return;

    const recognition = new Recognition();
    recognition.lang = this.lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    this._finalText = "";
    this._interimText = "";
    this._error = null;

    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) this._finalText += `${result[0].transcript} `;
        else interim += result[0].transcript;
      }
      this._interimText = interim;
      this.onInterim(this._transcript());
    };
    recognition.onerror = (event) => {
      // "no-speech" and "aborted" just mean an empty transcript.
      if (event.error !== "no-speech" && event.error !== "aborted") this._error = event.error;
    };
    this._ended = new Promise((resolve) => {
      recognition.onend = resolve;
    });

    this._recognition = recognition;
    recognition.start();
  }

  // Ends listening and resolves with the transcript ("" when nothing was heard).
  async stop() {
    const recognition = this._recognition;
    if (!recognition) return "";
    recognition.stop();
    // Chrome delivers the last final result just before "end"; don't wait forever for it.
    await Promise.race([this._ended, new Promise((resolve) => setTimeout(resolve, 1500))]);
    this._recognition = null;
    if (this._error) throw new Error(`Speech recognition failed: ${this._error}`);
    return this._transcript();
  }

  abort() {
    if (!this._recognition) return;
    this._recognition.abort();
    this._recognition = null;
  }

  _transcript() {
    return `${this._finalText}${this._interimText}`.replace(/\s+/g, " ").trim();
  }
}
