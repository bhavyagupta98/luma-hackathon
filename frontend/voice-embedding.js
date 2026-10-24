// Voice to embedding: runs a WavLM speaker-verification model in the browser (Transformers.js,
// ONNX on WebAssembly) and returns one L2-normalized 512-dimension embedding per clip.
// The backend must enroll and verify with embeddings from this same model; ECAPA vectors
// from the Python pipeline are not comparable.

import { loadTransformers, progressReporter } from "./model-runtime.js";

export const EMBEDDING_MODEL = "Xenova/wavlm-base-plus-sv";
export const EMBEDDING_DTYPE = "q8"; // onnx/model_quantized.onnx, about 100 MB, cached after first load
export const EMBEDDING_DIMENSIONS = 512;
// Model card: same speaker about 0.96, different speakers about 0.62.
export const DEFAULT_MATCH_THRESHOLD = 0.86;

export class VoiceEmbedder {
  constructor() {
    this._loading = null;
    this._processor = null;
    this._model = null;
  }

  // onProgress(percent, file) reports the one-time model download.
  load(onProgress = () => {}) {
    this._loading ??= (async () => {
      const { AutoProcessor, WavLMForXVector } = await loadTransformers();
      const progress_callback = progressReporter(onProgress);
      this._processor = await AutoProcessor.from_pretrained(EMBEDDING_MODEL, { progress_callback });
      this._model = await WavLMForXVector.from_pretrained(EMBEDDING_MODEL, {
        dtype: EMBEDDING_DTYPE,
        progress_callback,
      });
    })();
    return this._loading;
  }

  // samples: Float32Array of 16 kHz mono audio.
  async embed(samples) {
    await this.load();
    const inputs = await this._processor(samples);
    const { embeddings } = await this._model(inputs);
    return normalize(Float32Array.from(embeddings.data));
  }
}

export function normalize(vector) {
  const length = Math.hypot(...vector) || 1;
  return vector.map((value) => value / length);
}

export function cosineSimilarity(left, right) {
  let dot = 0;
  for (let index = 0; index < left.length; index += 1) dot += left[index] * right[index];
  return dot / ((Math.hypot(...left) || 1) * (Math.hypot(...right) || 1));
}

// Enrollment profile: the normalized mean of several clip embeddings.
export function averageEmbeddings(vectors) {
  const sum = new Float32Array(vectors[0].length);
  vectors.forEach((vector) => vector.forEach((value, index) => (sum[index] += value)));
  return normalize(sum);
}

// Compact, JSON-safe form for sending to the backend.
export function toWire(vector) {
  return Array.from(vector, (value) => Math.round(value * 1e6) / 1e6);
}
