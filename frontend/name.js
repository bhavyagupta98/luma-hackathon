// Turns what the speech recognizer heard into a name to store and read aloud.

// "my name is bhavya gupta" -> "Bhavya Gupta"; "" when it doesn't sound like a name.
export function parseName(heard) {
  const name = heard
    .replace(/[.,!?;:]/g, " ")
    .replace(/^\s*(?:hi|hello|hey)\b/i, "")
    .replace(/^\s*(?:my name is|my name's|the name is|i am|i'm|this is|it is|it's|call me|name is)\b/i, "")
    .replace(/\s+/g, " ")
    .trim();
  const words = name.split(" ");
  if (!name || words.length > 4 || !/^[\p{L}][\p{L} .'-]*$/u.test(name)) return "";
  return words.map((word) => word[0].toUpperCase() + word.slice(1)).join(" ");
}
