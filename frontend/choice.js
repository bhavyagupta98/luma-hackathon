// Decides which option of the spoken start menu was chosen.
// Returns "register", "signin", or "" when the speech was neither.

export function parseChoice(heard) {
  const text = ` ${heard.toLowerCase().replace(/[^a-z\s]/g, " ").replace(/\s+/g, " ")} `;
  const register = text.search(/\b(register|registration|registered|enrol|enroll|enrolment|enrollment|sign up|signup|new user)\b/);
  const signIn = text.search(/\b(sign in|signin|sign-in|log in|login|authenticate|verify|let me in|go in|enter)\b/);
  if (register === -1 && signIn === -1) return "";
  if (register === -1) return "signin";
  if (signIn === -1) return "register";
  return register < signIn ? "register" : "signin"; // both said: take the one said first
}
