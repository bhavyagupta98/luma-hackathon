// On-device speech models (Transformers.js): Whisper for speech to text and
// MMS-TTS (VITS) for text to speech. Audio never leaves the browser.

import { loadTransformers, progressReporter } from "./model-runtime.js";

export const STT_MODELS = {
  base: "Xenova/whisper-base.en", // about 77 MB quantized; better with server ids and numbers
  tiny: "Xenova/whisper-tiny.en", // about 41 MB quantized; faster, less accurate
};
export const TTS_MODEL = "Xenova/mms-tts-eng"; // about 38 MB quantized, 16 kHz output, English only

export class WhisperTranscriber {
  constructor({ model = STT_MODELS.base } = {}) {
    this.model = model;
    this.ready = false;
    this._loading = null;
    this._pipeline = null;
  }

  load(onProgress) {
    this._loading ??= (async () => {
      const { pipeline } = await loadTransformers();
      this._pipeline = await pipeline("automatic-speech-recognition", this.model, {
        dtype: "q8",
        progress_callback: progressReporter(onProgress),
      });
      this.ready = true;
    })();
    return this._loading;
  }

  // samples: Float32Array of 16 kHz mono audio, at most 30 s.
  async transcribe(samples) {
    await this.load();
    const { text } = await this._pipeline(samples);
    return cleanTranscript(text);
  }
}

export class VitsSynthesizer {
  constructor({ model = TTS_MODEL } = {}) {
    this.model = model;
    this.ready = false;
    this._loading = null;
    this._pipeline = null;
  }

  load(onProgress) {
    this._loading ??= (async () => {
      const { pipeline } = await loadTransformers();
      this._pipeline = await pipeline("text-to-speech", this.model, {
        dtype: "q8",
        progress_callback: progressReporter(onProgress),
      });
      this.ready = true;
    })();
    return this._loading;
  }

  // Resolves with {audio: Float32Array, samplingRate}.
  async synthesize(text) {
    await this.load();
    const { audio, sampling_rate } = await this._pipeline(speakable(text));
    return { audio, samplingRate: sampling_rate };
  }
}

// Whisper marks non-speech as "[BLANK_AUDIO]", "(wind blowing)" and similar.
function cleanTranscript(text) {
  return text
    .replace(/\[[^\]]*\]|\([^)]*\)/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// ---- Text normalization for MMS-TTS, whose vocabulary has letters but no digits ----

const ONES = [
  "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
  "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
  "nineteen",
];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
const SCALES = [
  [1_000_000_000, "billion"],
  [1_000_000, "million"],
  [1_000, "thousand"],
];

export function numberToWords(value) {
  if (value < 20) return ONES[value];
  if (value < 100) {
    return TENS[Math.floor(value / 10)] + (value % 10 ? ` ${ONES[value % 10]}` : "");
  }
  if (value < 1000) {
    const rest = value % 100;
    return `${ONES[Math.floor(value / 100)]} hundred${rest ? ` ${numberToWords(rest)}` : ""}`;
  }
  for (const [scale, name] of SCALES) {
    if (value >= scale) {
      const rest = value % scale;
      return `${numberToWords(Math.floor(value / scale))} ${name}${rest ? ` ${numberToWords(rest)}` : ""}`;
    }
  }
  return String(value);
}

function digitsToWords(digits) {
  // Long digit runs (serials, phone numbers) read best digit by digit.
  if (digits.length > 6 || (digits.length > 1 && digits.startsWith("0"))) {
    return [...digits].map((digit) => ONES[Number(digit)]).join(" ");
  }
  return numberToWords(Number(digits));
}

export function speakable(text) {
  return text
    .replace(/(\d+)\s*°\s*C\b/g, "$1 degrees")
    .replace(/(\d+)%/g, "$1 percent")
    .replace(/(\d+)\.(\d+)/g, (_, whole, fraction) => `${whole} point ${[...fraction].join(" ")}`)
    .replace(/\b([A-Z]{1,4})(?=-[A-Z0-9])/g, (letters) => [...letters].join(" ")) // SRV-100 -> S R V-100
    .replace(/\d+/g, (digits) => ` ${digitsToWords(digits)} `)
    .replace(/-/g, " ")
    .replace(/\s+([.,!?;:])/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}
