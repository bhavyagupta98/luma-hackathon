import { parseChoice } from "../../../frontend/choice.js";
const cases = [
  ["register voice", "register"], ["Register my voice", "register"], ["I want to register", "register"],
  ["register", "register"], ["enroll me", "register"], ["sign up", "register"], ["I'm a new user", "register"],
  ["sign in", "signin"], ["Sign in please", "signin"], ["log in", "signin"], ["login", "signin"],
  ["let me in", "signin"], ["authenticate me", "signin"], ["I want to sign in", "signin"],
  ["register and then sign in", "register"], ["sign in or register", "signin"],
  ["", ""], ["   ", ""], ["what is the weather", ""], ["hello", ""], ["restart server one hundred", ""],
];
let bad = 0;
for (const [input, want] of cases) {
  const got = parseChoice(input);
  const ok = got === want; if (!ok) bad++;
  console.log(ok ? "ok  " : "FAIL", JSON.stringify(input).padEnd(36), "->", JSON.stringify(got), ok ? "" : `(wanted ${JSON.stringify(want)})`);
}
console.log(bad ? `${bad} FAILED` : "all passed");
process.exit(bad ? 1 : 0);
