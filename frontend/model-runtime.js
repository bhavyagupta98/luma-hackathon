// Shared loader for Transformers.js, which runs the frontend's ONNX models
// (voice embedding, speech to text, text to speech) in the browser on WebAssembly.
// Model files download once from the Hugging Face Hub and are then served from the browser cache.

export const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1";

let library = null;

export function loadTransformers() {
  library ??= import(TRANSFORMERS_URL);
  return library;
}

// Adapts onProgress(percent, file) to Transformers.js's progress_callback events.
export function progressReporter(onProgress = () => {}) {
  return (event) => {
    if (event.status === "progress") onProgress(event.progress ?? 0, event.file);
  };
}
