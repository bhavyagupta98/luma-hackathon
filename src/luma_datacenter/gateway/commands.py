from __future__ import annotations

import re
from dataclasses import dataclass

TASK_VERBS = {
    "restart": "restart",
    "reboot": "restart",
    "fix": "fix",
    "repair": "fix",
}

_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_FILLER = {"number", "no", "the", "please", "named", "called", "id", "and"}
# How speech recognition tends to write a spoken letter name ("server A" -> "server ay").
_LETTER_WORDS = {
    "ay": "a", "eh": "a", "alpha": "a",
    "bee": "b", "be": "b", "bravo": "b",
    "see": "c", "sea": "c", "charlie": "c",
}


@dataclass(frozen=True, slots=True)
class Command:
    task: str  # "restart" | "fix"
    server_id: str | None  # normalized, e.g. "SRV-100"; None when no server was understood


def words_to_int(tokens: list[str]) -> int | None:
    """Spoken number to int: "one hundred", "two fifty", "one oh oh", "100"."""
    if not tokens:
        return None
    if all(token.isdigit() for token in tokens):
        return int("".join(tokens))
    # Digit-by-digit reading ("one zero zero", "one oh oh") rather than a composed number.
    if len(tokens) > 1 and all(token in _UNITS and _UNITS[token] < 10 for token in tokens):
        return int("".join(str(_UNITS[token]) for token in tokens))

    total = current = 0
    seen = False
    for token in tokens:
        value = _UNITS.get(token, _TENS.get(token))
        if value is not None and value >= 10 and 1 <= current <= 9:
            current = current * 100 + value  # "two fifty" -> 250
        elif token in _UNITS:
            current += _UNITS[token]
        elif token in _TENS:
            current += _TENS[token]
        elif token == "hundred":
            current = max(current, 1) * 100
        elif token == "thousand":
            total += max(current, 1) * 1000
            current = 0
        elif token.isdigit():
            current += int(token)
        else:
            return None
        seen = True
    return total + current if seen else None


def parse_command(text: str) -> Command | None:
    """Understand "restart server X" / "fix server X"; None if it is neither."""
    lowered = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
    lowered = re.sub(r"\bs\s*r\s*v\b", "srv", lowered)  # "S R V" / "s-r-v" spoken as letters
    lowered = re.sub(r"\b(server|srv)(?=\d)", r"\1 ", lowered)  # "server100"
    tokens = lowered.replace("-", " ").split()

    task = next((TASK_VERBS[token] for token in tokens if token in TASK_VERBS), None)
    if task is None:
        return None

    anchor = next((i for i, token in enumerate(tokens) if token in {"server", "srv"}), None)
    if anchor is None:
        return Command(task, None)
    rest = [token for token in tokens[anchor + 1 :] if token not in _FILLER]

    number_tokens: list[str] = []
    for token in rest:
        if token.isdigit() or token in _UNITS or token in _TENS or token in {"hundred", "thousand"}:
            number_tokens.append(token)
        else:
            break
    number = words_to_int(number_tokens)
    if number is not None:
        return Command(task, f"SRV-{number}")
    if rest and re.fullmatch(r"[a-z]\w*", rest[0]):
        letter = _LETTER_WORDS.get(rest[0], rest[0])
        return Command(task, f"SRV-{letter.upper()}")  # e.g. "server a"
    return Command(task, None)
