// Microphone capture for voice authentication: push-to-talk clips as 16 kHz mono Float32 samples,
// trimmed of leading/trailing silence and checked for length before they are embedded.

export const SAMPLE_RATE = 16_000;

const FRAME_SECONDS = 0.02;
const SPEECH_RMS = 0.015; // about -36 dBFS; quieter frames count as silence
const EDGE_PADDING_SECONDS = 0.15;

export class VoiceRecorder {
  constructor({ minSeconds = 1.5, maxSeconds = 14 } = {}) {
    this.minSeconds = minSeconds;
    this.maxSeconds = maxSeconds;
    this._stream = null;
    this._recorder = null;
    this._chunks = [];
  }

  get recording() {
    return this._recorder !== null;
  }

  // Asks for microphone permission once and keeps the stream for later clips.
  async open() {
    if (this._stream) return;
    // Keep these settings identical for enrollment and sign-in so embeddings stay comparable.
    this._stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  }

  start() {
    if (!this._stream) throw new Error("Call open() before start().");
    if (this._recorder) return;
    this._chunks = [];
    this._recorder = new MediaRecorder(this._stream);
    this._recorder.ondataavailable = (event) => {
      if (event.data.size > 0) this._chunks.push(event.data);
    };
    this._recorder.start();
  }

  // Resolves with {samples, durationSeconds, rms} or {error} describing why the clip is unusable.
  async stop() {
    const recorder = this._recorder;
    if (!recorder) return { error: "not-recording" };
    this._recorder = null;
    const stopped = new Promise((resolve) => {
      recorder.onstop = resolve;
    });
    recorder.stop();
    await stopped;

    const blob = new Blob(this._chunks, { type: recorder.mimeType });
    if (blob.size === 0) return { error: "empty" };
    const samples = await decodeToMono16k(await blob.arrayBuffer());
    return this._prepare(samples);
  }

  close() {
    this._stream?.getTracks().forEach((track) => track.stop());
    this._stream = null;
  }

  _prepare(samples) {
    const trimmed = trimSilence(samples);
    if (!trimmed) return { error: "silence" };
    const limited = trimmed.subarray(0, Math.floor(this.maxSeconds * SAMPLE_RATE));
    const durationSeconds = limited.length / SAMPLE_RATE;
    if (durationSeconds < this.minSeconds) return { error: "too-short", durationSeconds };
    return { samples: limited, durationSeconds, rms: rms(limited, 0, limited.length) };
  }
}

async function decodeToMono16k(arrayBuffer) {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(arrayBuffer);
    const frames = Math.ceil(decoded.duration * SAMPLE_RATE);
    // Rendering into a 1-channel, 16 kHz offline context both downmixes and resamples.
    const offline = new OfflineAudioContext(1, frames, SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return rendered.getChannelData(0).slice();
  } finally {
    context.close();
  }
}

function rms(samples, start, end) {
  let sum = 0;
  for (let index = start; index < end; index += 1) sum += samples[index] * samples[index];
  return Math.sqrt(sum / Math.max(1, end - start));
}

function trimSilence(samples) {
  const frame = Math.floor(FRAME_SECONDS * SAMPLE_RATE);
  let first = -1;
  let last = -1;
  for (let start = 0; start + frame <= samples.length; start += frame) {
    if (rms(samples, start, start + frame) >= SPEECH_RMS) {
      if (first < 0) first = start;
      last = start + frame;
    }
  }
  if (first < 0) return null;
  const padding = Math.floor(EDGE_PADDING_SECONDS * SAMPLE_RATE);
  return samples.subarray(Math.max(0, first - padding), Math.min(samples.length, last + padding));
}

// 16-bit PCM WAV, for debugging a clip by ear or with the backend's own tools.
export function encodeWav(samples, sampleRate = SAMPLE_RATE) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return new Blob([buffer], { type: "audio/wav" });
}
