const play = document.getElementById("play");
const counter = document.getElementById("counter");
const title = document.getElementById("title");
const worker = document.getElementById("worker");
const system = document.getElementById("system");
const result = document.getElementById("result");

let availableVoices = speechSynthesis.getVoices();
speechSynthesis.addEventListener("voiceschanged", () => {
  availableVoices = speechSynthesis.getVoices();
});

function voiceFor(role) {
  const english = availableVoices.filter((voice) => voice.lang.startsWith("en"));
  const preferred = {
    AB: /samantha|alex|daniel/i,
    BG: /victoria|karen|moira/i,
    UNKNOWN: /fred|ralph|zarvox/i,
    SYSTEM: /google|natural|siri/i,
  }[role];
  return english.find((voice) => preferred?.test(voice.name))
    || english[{ AB: 0, BG: 1, UNKNOWN: 2, SYSTEM: 3 }[role] % Math.max(english.length, 1)]
    || null;
}

function say(text, role) {
  return new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voiceFor(role);
    utterance.rate = role === "SYSTEM" ? 1.05 : 1;
    utterance.pitch = { AB: 0.9, BG: 1.15, UNKNOWN: 0.7, SYSTEM: 1.05 }[role] || 1;
    utterance.onend = resolve;
    utterance.onerror = resolve;
    speechSynthesis.speak(utterance);
  });
}

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

play.addEventListener("click", async () => {
  play.disabled = true;
  play.textContent = "Running demo…";
  speechSynthesis.cancel();
  try {
    const response = await fetch("/api/demo/cases", { method: "POST" });
    const demo = await response.json();
    for (const [index, test] of demo.cases.entries()) {
      counter.textContent = `TEST ${index + 1} OF ${demo.count} · ${test.code}`;
      title.textContent = test.title;
      worker.textContent = test.worker;
      system.textContent = "Listening…";
      result.textContent = "";
      await say(test.worker, test.speaker);
      await pause(350);
      system.textContent = test.system;
      await say(test.system, "SYSTEM");
      result.textContent = test.passed ? "PASS" : "FAIL";
      await pause(900);
    }
    counter.textContent = demo.all_passed ? "ALL TESTS PASSED" : "DEMO FAILED";
    title.textContent = "End-to-end demonstration complete";
  } catch (error) {
    result.textContent = `Could not run demo: ${error.message}`;
  } finally {
    play.disabled = false;
    play.textContent = "Play again";
  }
});
