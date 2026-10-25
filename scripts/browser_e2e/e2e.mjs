import puppeteer from "puppeteer-core";

const EDGE = process.env.EDGE || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const BASE = process.env.BASE || "http://localhost:8081";
const PROFILE = process.env.PROFILE; // shared so downloaded speech models stay cached
const AUTH_WAV = process.env.AUTH_WAV;
const CMD_100 = process.env.CMD_100;
const CMD_300 = process.env.CMD_300;
const t0 = Date.now();
const stamp = () => `[${((Date.now() - t0) / 1000).toFixed(0).padStart(3)}s]`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function launch(wav) {
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    userDataDir: PROFILE,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${wav}`,
      "--autoplay-policy=no-user-gesture-required",
      "--no-first-run",
      "--disable-features=Translate",
    ],
  });
  const page = await browser.newPage();
  page.on("pageerror", (error) => console.log(stamp(), "PAGE ERROR:", error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log(stamp(), "console.error:", msg.text().slice(0, 200));
  });
  return { browser, page };
}

const logText = (page) => page.$eval("#log", (el) => el.innerText).catch(() => "");

async function waitForLog(page, needle, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const text = await logText(page);
    if (text.includes(needle)) return text;
    await sleep(1000);
  }
  throw new Error(`timed out (${label}) waiting for "${needle}"\n${await logText(page)}`);
}

async function hold(page, ms) {
  await page.keyboard.down("Space");
  await sleep(ms);
  await page.keyboard.up("Space");
}

const stage = process.argv[2];

if (stage === "warmup") {
  // Loads Whisper + MMS-TTS from the CDN/Hub once; later stages reuse the browser cache.
  const { browser, page } = await launch(CMD_100);
  await page.goto(`${BASE}/ear.html?device=DC-D-100&mock=1&debug=1`);
  await page.click("#overlay");
  const log = await waitForLog(page, "text to speech: model ready", 600_000, "tts model");
  await waitForLog(page, "speech to text: Xenova/whisper-base.en ready", 600_000, "stt model");
  console.log(stamp(), "models ready\n" + (await logText(page)));
  await browser.close();
} else if (stage === "signin") {
  const { browser, page } = await launch(AUTH_WAV);
  await page.goto(`${BASE}/auth.html?device=DC-D-100&debug=1&manual=1`);
  await page.click("#overlay");
  await page.waitForFunction(() => document.getElementById("dot").dataset.state === "ready", {
    timeout: 60_000,
  });
  console.log(stamp(), "ready, speaking the sign-in phrase");
  await sleep(1500);
  await hold(page, 7000);
  console.log(stamp(), "released; waiting for the redirect to the earpiece");
  await page.waitForFunction(() => location.pathname.endsWith("ear.html"), { timeout: 120_000 });
  const session = await page.evaluate(() => sessionStorage.getItem("luma.voiceSession"));
  console.log(stamp(), "redirected to", page.url());
  console.log(stamp(), "session:", session);
  await browser.close();
  if (process.env.SESSION_OUT) (await import("node:fs")).writeFileSync(process.env.SESSION_OUT, session);
} else if (stage === "enroll") {
  // Enroll through the page (3 phrases), expect the redirect to sign-in, then sign in.
  const { browser, page } = await launch(process.env.ENROLL_WAV);
  await page.goto(`${BASE}/auth.html?device=DC-D-100&enroll=1&debug=1&tts=browser`);
  await page.click("#overlay");
  await page.waitForFunction(() => document.getElementById("dot").dataset.state === "ready", {
    timeout: 60_000,
  });
  for (let phrase = 1; phrase <= 3; phrase += 1) {
    await sleep(1000);
    console.log(stamp(), `phrase ${phrase}: ${await page.$eval("#status", (el) => el.textContent)}`);
    await hold(page, 6500);
    if (phrase < 3) {
      await sleep(600);
      await page.waitForFunction(() => document.getElementById("dot").dataset.state === "ready", {
        timeout: 60_000,
      });
    }
  }
  console.log(stamp(), "released the third phrase; waiting for the redirect to sign-in");
  await page.waitForFunction(
    () => location.pathname.endsWith("auth.html") && !location.search.includes("enroll"),
    { timeout: 120_000 },
  );
  console.log(stamp(), "redirected to", page.url());
  await browser.close();
} else if (stage === "command") {
  const wav = process.env.WAV;
  const session = (await import("node:fs")).readFileSync(process.env.SESSION_OUT, "utf8");
  const { browser, page } = await launch(wav);
  await page.evaluateOnNewDocument((stored) => sessionStorage.setItem("luma.voiceSession", stored), session);
  await page.goto(`${BASE}/ear.html?device=DC-D-100&debug=1&manual=1&stt=model&tts=model`);
  console.log(stamp(), "on", page.url());
  await page.click("#overlay");
  await waitForLog(page, "speech to text: Xenova/whisper-base.en ready", 300_000, "stt model");
  await sleep(500);
  console.log(stamp(), "holding Space while the command audio plays");
  await hold(page, 7500);
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const text = await logText(page);
    if (text.includes("Task successful") || text.includes("not allowed")) break;
    await sleep(1000);
  }
  await sleep(3000);
  console.log(stamp(), "log:\n" + (await logText(page)));
  await browser.close();
} else {
  console.log("usage: node e2e.mjs warmup|enroll|signin|command");
}
