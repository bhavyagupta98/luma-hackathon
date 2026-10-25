import { parseName } from "../../../frontend/name.js";
const cases = [
  ["My name is Bhavya Gupta.", "Bhavya Gupta"], ["my name is bhavya gupta", "Bhavya Gupta"],
  ["Hi, my name is Avinash", "Avinash"], ["I'm Devansh Gupta", "Devansh Gupta"],
  ["this is Abhinandan Sharma", "Abhinandan Sharma"], ["It's Jean-Luc Picard", "Jean-Luc Picard"],
  ["O'Brien", "O'Brien"], ["my name is Zoë Müller", "Zoë Müller"], ["Alice", "Alice"],
  ["my name is McDonald", "McDonald"],
  ["", ""], ["   ", ""], ["my name is", ""], ["restart server one hundred and fifty now please", ""],
  ["my name is 7 of 9", ""], ["call me", ""],
];
let bad = 0;
for (const [input, want] of cases) { const got = parseName(input); const ok = got === want; if (!ok) bad++; console.log(ok ? "ok  " : "FAIL", JSON.stringify(input), "->", JSON.stringify(got), ok ? "" : `(wanted ${JSON.stringify(want)})`); }
console.log(bad ? `${bad} FAILED` : "all passed");
