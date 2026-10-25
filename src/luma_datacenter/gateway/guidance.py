"""The overheat scenario: an audio-only alert and turn-by-turn spoken directions.

When a server overheats, the signed-in worker responsible for it is alerted, asked whether they need
directions, told where the system believes they are (from the check-in point they used), and then
walked to the rack one short step at a time. They can answer "next", "repeat", "back", "where am I",
correct their location, or say "fix server B" once they arrive. Everything is plain text in and out,
so it works the same over the gateway's websocket and in the tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- The facility (a small fixed map) -------------------------------------------------------

PLACES = {
    "main_entrance": "the main entrance",
    "break_room": "the break room",
    "loading_dock": "the loading dock",
    "double_doors": "the double doors to Hall B",
    "hall_b_front": "the front of Hall B",
    "hall_b_rear": "the back of Hall B",
    "aisle_3": "aisle three",
    "rack_14": "rack fourteen",
}

# Where each check-in device is installed: this is how the system knows where the worker is.
DEVICE_LOCATIONS = {
    "DC-D-100": "main_entrance",
    "DC-D-200": "loading_dock",
    "DC-D-ALICE": "break_room",
}

# What a worker might say to correct their location.
PLACE_WORDS = {
    "main_entrance": ("main entrance", "entrance", "front door", "lobby", "reception"),
    "break_room": ("break room", "breakroom", "cafeteria", "kitchen", "canteen"),
    "loading_dock": ("loading dock", "dock", "loading bay"),
}

# From each place, the one short instruction that moves the worker to the next place, ending at
# the rack. Instructions are written to be said aloud: short, with distances and landmarks.
NEXT_STEP = {
    "main_entrance": (
        "double_doors",
        "Walk straight down the main corridor, thirty meters, to the double doors.",
    ),
    "break_room": (
        "double_doors",
        "Turn right out of the break room. Follow the corridor, twenty meters, "
        "to the double doors.",
    ),
    "double_doors": ("hall_b_front", "Go through the double doors into Hall B."),
    "hall_b_front": ("aisle_3", "Turn left. Aisle three is the third aisle on your right."),
    "loading_dock": (
        "hall_b_rear",
        "Take the service corridor, twenty meters, to the back door of Hall B. Go through it.",
    ),
    "hall_b_rear": ("aisle_3", "Aisle three is the first aisle on your left. Turn into it."),
    "aisle_3": ("rack_14", "Walk down the aisle. Rack fourteen is the fifth rack on your left."),
}

NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


def route(start: str, goal: str = "rack_14") -> list[tuple[str, str]] | None:
    """The (place reached, instruction) steps from `start` to `goal`, or None if there is no way."""
    steps: list[tuple[str, str]] = []
    place = start
    while place != goal:
        if place not in NEXT_STEP or len(steps) > len(NEXT_STEP):
            return None
        place, instruction = NEXT_STEP[place]
        steps.append((place, instruction))
    return steps


# --- Understanding the worker --------------------------------------------------------------


def _words(text: str) -> str:
    return " " + re.sub(r"\s+", " ", re.sub(r"[^a-z' ]", " ", text.lower())).strip() + " "


def _has(text: str, *phrases: str) -> bool:
    return any(f" {phrase} " in text for phrase in phrases)


def _place_in(text: str) -> str | None:
    for place, words in PLACE_WORDS.items():
        if _has(text, *words):
            return place
    return None


DECLINE = ("no", "nope", "not now", "later", "no thanks", "no thank you", "i know the way",
           "i know where", "dont need", "don't need", "do not need", "not needed", "i'm fine")
ACCEPT = ("yes", "yeah", "yep", "yup", "sure", "please", "ok", "okay", "directions", "guide me",
          "show me", "take me", "i do", "i need", "go ahead", "lead the way")
STOP = ("stop", "cancel", "never mind", "nevermind", "forget it", "quit", "exit", "end")
WHERE = ("where am i", "where are we", "my location", "where am", "what's my location")
BACK = ("back", "go back", "previous", "last step", "before that")
REPEAT = ("repeat", "again", "say that again", "say again", "what", "pardon", "sorry",
          "come again", "once more", "say it again", "i didn't hear", "i did not hear", "huh")
NEXT = ("next", "done", "finished", "okay", "ok", "got it", "continue", "ready", "yes", "yeah",
        "there", "i'm there", "i am there", "arrived", "made it", "go on", "go ahead", "and then",
        "what next", "then what")
WRONG = ("wrong", "not here", "not there", "incorrect", "not right", "that's not right")


# --- The dialogue ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Walk:
    phase: str  # offered | navigating | locating | arrived | idle
    start: str  # where the worker is believed to be at step one
    steps: list[tuple[str, str]] = field(default_factory=list)
    index: int = 0  # the step being given (0-based)


class Guide:
    """One overheating server, and the spoken dialogue that gets a worker to it."""

    def __init__(
        self,
        *,
        server_id: str = "SRV-200",
        letter: str = "B",
        hall: str = "Hall B",
        rack: str = "rack_14",
        temperature: int = 41,
        alert_delay: float = 8.0,
    ) -> None:
        self.server_id = server_id
        self.letter = letter
        self.hall = hall
        self.rack = rack
        self.temperature = temperature
        self.alert_delay = alert_delay
        self._walks: dict[str, _Walk] = {}
        self._alerted: set[str] = set()

    # -- events

    def alert(self, session_id: str, device_id: str) -> str | None:
        """Start the scenario for a session; None if it was already alerted."""
        if session_id in self._alerted:
            return None
        self._alerted.add(session_id)
        self._walks[session_id] = _Walk("offered", DEVICE_LOCATIONS.get(device_id, "main_entrance"))
        return (
            f"Alert. Server {self.letter} in {self.hall} is overheating, "
            f"{self.temperature} degrees. Do you need directions to get there?"
        )

    def forget(self, session_id: str) -> None:
        self._walks.pop(session_id, None)
        self._alerted.discard(session_id)

    def active(self, session_id: str) -> bool:
        return session_id in self._walks

    def resolved(self, session_id: str, server_id: str) -> str | None:
        """Called after a successful task: a fix on the overheating server ends the alert."""
        if server_id != self.server_id or session_id not in self._walks:
            return None
        del self._walks[session_id]
        return f"Task successful. Server {self.letter} is cooling down. Alert cleared. Good work."

    # -- conversation

    def reply(self, session_id: str, text: str) -> str | None:
        """What to say to `text`, or None if this conversation has nothing to do with it."""
        walk = self._walks.get(session_id)
        if walk is None:
            return None
        heard = _words(text)
        if walk.phase == "offered":
            return self._offered(walk, heard)
        if walk.phase == "idle":
            return self._begin(walk) if _has(heard, "directions", "guide me", "take me") else None
        if _has(heard, *STOP):
            walk.phase = "idle"
            return "Okay, directions stopped. Say directions any time you need them."
        if walk.phase == "locating":
            return self._located(walk, heard)
        if _has(heard, *WHERE):
            return self._where(walk)
        place = _place_in(heard)
        saying_where = _has(heard, "i'm", "i am", "im", "actually", "at", "in", *WRONG)
        if place and saying_where:
            return self._relocate(walk, place)
        if _has(heard, *WRONG):
            walk.phase = "locating"
            return "Where are you? Say main entrance, loading dock, or break room."
        if walk.phase == "arrived":
            return self._arrived(walk, heard)
        if _has(heard, *BACK):
            return self._back(walk)
        if _has(heard, *REPEAT) and not _has(heard, *NEXT[:3]):
            return self._say_step(walk)
        if _has(heard, *NEXT):
            return self._advance(walk)
        return "Say next when you are there, repeat to hear it again, or stop."

    # -- phases

    def _offered(self, walk: _Walk, heard: str) -> str:
        if _has(heard, *DECLINE):
            walk.phase = "idle"
            return "Okay. The alert stays open. Say directions whenever you need them."
        if _has(heard, *ACCEPT):
            return self._begin(walk)
        return "Do you need directions to the server? Say yes or no."

    def _begin(self, walk: _Walk) -> str:
        steps = route(walk.start, self.rack)
        if steps is None:
            walk.phase = "idle"
            return "Sorry, I can't find a route from here. Please ask someone nearby."
        walk.steps, walk.index, walk.phase = steps, 0, "navigating"
        return f"You are at {PLACES[walk.start]}. We start from here. {self._step_text(walk)}"

    def _step_text(self, walk: _Walk) -> str:
        number = NUMBER_WORDS.get(walk.index + 1, str(walk.index + 1))
        total = NUMBER_WORDS.get(len(walk.steps), str(len(walk.steps)))
        return f"Step {number} of {total}. {walk.steps[walk.index][1]} Say next when done."

    def _say_step(self, walk: _Walk) -> str:
        return self._step_text(walk)

    def _advance(self, walk: _Walk) -> str:
        walk.index += 1
        if walk.index < len(walk.steps):
            return self._step_text(walk)
        walk.phase = "arrived"
        return (
            f"You have arrived at {PLACES[self.rack]}. Server {self.letter} should show an amber "
            f"light. Say fix server {self.letter} to start the cooling reset."
        )

    def _back(self, walk: _Walk) -> str:
        if walk.index == 0:
            return f"You are at the first step. {self._step_text(walk)}"
        walk.index -= 1
        return f"Going back. {self._step_text(walk)}"

    def _where(self, walk: _Walk) -> str:
        place = walk.start if walk.index == 0 else walk.steps[walk.index - 1][0]
        return f"You should be at {PLACES[place]}. {self._step_text(walk)}"

    def _arrived(self, walk: _Walk, heard: str) -> str:
        if _has(heard, *REPEAT):
            return (
                f"You are at {PLACES[self.rack]}. Say fix server {self.letter} to start "
                "the cooling reset."
            )
        return f"Say fix server {self.letter} when you are ready."

    def _relocate(self, walk: _Walk, place: str) -> str:
        walk.start = place
        walk.phase = "navigating"
        steps = route(place, self.rack)
        if steps is None:
            walk.phase = "idle"
            return "Sorry, I can't find a route from there. Please ask someone nearby."
        walk.steps, walk.index = steps, 0
        return f"Got it. You are at {PLACES[place]}. {self._step_text(walk)}"

    def _located(self, walk: _Walk, heard: str) -> str:
        place = _place_in(heard)
        if place is None:
            return "Say main entrance, loading dock, or break room."
        return self._relocate(walk, place)
