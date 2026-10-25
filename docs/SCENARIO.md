# Overheat scenario: audio-only script

One technician, no screen, no buttons. Everything is spoken. This runs on its own port (**8090**),
separate from the main demo (8080).

**Run it** (opens Chrome and taps the page for you, so nobody touches the screen):

```powershell
.\.venv\Scripts\python scripts\run_demo.py --scenario --fresh
```

It starts a second server on port 8090 with the alert scenario switched on, and opens the voice menu.
Already registered? Add `signin` to skip registration: `run_demo.py signin --scenario`.
Sessions last 5 minutes here (the walk takes longer than the usual 60 seconds).

**Speaker key:** **SYSTEM** is the voice in the earpiece. **YOU** is the technician. Lines in bold are
spoken exactly as written; everything you say can be phrased in many ways.

---

## Part 1. Registration and authentication

| | |
|---|---|
| SYSTEM | **"Welcome to Luma. Say register voice, or say sign in."** |
| YOU | "Register voice." |
| SYSTEM | **"Okay, let's register you."** |
| SYSTEM | **"Welcome. Let's get you registered."** *(tone)* **"First, tell me your name. Please say: My name is, and then your name."** |
| YOU | "My name is Bhavya Gupta." |
| SYSTEM | **"Nice to meet you, Bhavya Gupta."** **"Phrase 1 of 3. Please say: My voice is my badge, please verify me."** *(tone)* |
| YOU | "My voice is my badge, please verify me." |
| SYSTEM | **"Got it."** **"Phrase 2 of 3. Please say: I am here to work on the servers tonight."** |
| YOU | "I am here to work on the servers tonight." |
| SYSTEM | **"Got it."** **"Phrase 3 of 3. Please say: The quick brown fox jumps over the lazy dog."** |
| YOU | "The quick brown fox jumps over the lazy dog." |
| SYSTEM | **"Bhavya Gupta, you are enrolled."** |
| SYSTEM | **"Welcome. Please verify your voice to go inside."** *(tone)* **"Please say: this is my voice, please let me in."** |
| YOU | "This is my voice, please let me in." |
| SYSTEM | **"Bhavya Gupta is authenticated."** **"You are inside. Say a command, for example, fix server A."** |

**If someone else tries to get in:**

| | |
|---|---|
| YOU (a stranger) | "This is my voice, please let me in." |
| SYSTEM | **"You are not registered."** *(then it asks again)* **"Please say: this is my voice, please let me in."** |

## Part 2. The alert (about 8 seconds after you are inside)

| | |
|---|---|
| SYSTEM *(warning tone)* | **"Alert. Server B in Hall B is overheating, 41 degrees. Do you need directions to get there?"** |

## Part 3. Location and directions

The system knows where you are from the **check-in point you used**: the main entrance reader
(`DC-D-100`), the loading dock (`DC-D-200`) or the break room (`DC-D-ALICE`).

| | |
|---|---|
| YOU | "Yes." |
| SYSTEM | **"You are at the main entrance. We start from here. Step one of four. Walk straight down the main corridor, thirty meters, to the double doors. Say next when done."** |

If you decline:

| | |
|---|---|
| YOU | "No thanks." |
| SYSTEM | **"Okay. The alert stays open. Say directions whenever you need them."** |

## Part 4. Short spoken instructions, with repeats and check-ins

| | |
|---|---|
| YOU | "Repeat." |
| SYSTEM | **"Step one of four. Walk straight down the main corridor, thirty meters, to the double doors. Say next when done."** |
| YOU | "Done." |
| SYSTEM | **"Step two of four. Go through the double doors into Hall B. Say next when done."** |
| YOU | "Next." |
| SYSTEM | **"Step three of four. Turn left. Aisle three is the third aisle on your right. Say next when done."** |
| YOU | "Where am I?" |
| SYSTEM | **"You should be at the front of Hall B. Step three of four. Turn left. Aisle three is the third aisle on your right. Say next when done."** |
| YOU | "Go back." |
| SYSTEM | **"Going back. Step two of four. Go through the double doors into Hall B. Say next when done."** |
| YOU | "Okay." |
| SYSTEM | **"Step three of four. Turn left…"** |
| YOU | "Next." |
| SYSTEM | **"Step four of four. Walk down the aisle. Rack fourteen is the fifth rack on your left. Say next when done."** |
| YOU | "I'm there." |
| SYSTEM | **"You have arrived at rack fourteen. Server B should show an amber light. Say fix server B to start the cooling reset."** |
| YOU | "Fix server B." |
| SYSTEM | **"Task successful. Server B is cooling down. Alert cleared. Good work."** |

**Other things you can say while walking:**

| You say | System does |
|---|---|
| "Repeat" / "Say that again" / "What?" | Says the current step again |
| "Go back" / "Previous" | Goes back one step |
| "Where am I?" | Says the place you should have reached, then the step |
| "Actually I'm at the loading dock" | **"Got it. You are at the loading dock. Step one of three. Take the service corridor, twenty meters, to the back door of Hall B. Go through it. Say next when done."** |
| "That's the wrong location" | **"Where are you? Say main entrance, loading dock, or break room."** |
| "Stop" / "Cancel" | **"Okay, directions stopped. Say directions any time you need them."** |
| Something unclear | **"Say next when you are there, repeat to hear it again, or stop."** |
| "Fix server B" at any time | Runs the fix straight away and clears the alert |

---

## Part 5. Video script (about 1 minute 45 seconds)

*Written for: the people filming and presenting the demo video.* One presenter, one laptop on a desk,
a headset on. The screen shows only the status orb; don't film it much. About 250 spoken words.

| Time | Picture | Words |
|---|---|---|
| 0:00 – 0:12 | The presenter in a server hall, hands full, no phone | **Narrator:** "A data center at night. Hands full. Eyes on the racks. No time for a screen. This is Luma, a voice-only assistant for the people who will never open an app." |
| 0:12 – 0:40 | Close on the presenter's face; headset | **SYSTEM:** "Welcome to Luma. Say register voice, or say sign in." **YOU:** "Register voice." **SYSTEM:** "First, tell me your name." **YOU:** "My name is Bhavya Gupta." *(cut)* **SYSTEM:** "Bhavya Gupta, you are enrolled." |
| 0:40 – 1:00 | A second person tries the headset | **SYSTEM:** "Please say: this is my voice, please let me in." **STRANGER:** "This is my voice, please let me in." **SYSTEM:** "You are not registered." **YOU:** (same phrase) **SYSTEM:** "Bhavya Gupta is authenticated. You are inside." **Narrator:** "Your voice is your badge." |
| 1:00 – 1:12 | Presenter turns toward the racks | **SYSTEM (alert tone):** "Alert. Server B in Hall B is overheating, 41 degrees. Do you need directions to get there?" **YOU:** "Yes." |
| 1:12 – 1:35 | Walking shots, each step cut short | **SYSTEM:** "You are at the main entrance. We start from here. Step one of four. Walk straight down the main corridor, thirty meters, to the double doors." **YOU:** "Repeat." **SYSTEM:** "Step one of four…" **YOU:** "Done." **SYSTEM:** "Step two of four. Go through the double doors into Hall B." *(jump cut)* **SYSTEM:** "You have arrived at rack fourteen." |
| 1:35 – 1:45 | Presenter at the rack | **YOU:** "Fix server B." **SYSTEM:** "Task successful. Server B is cooling down. Alert cleared. Good work." **Narrator:** "Registered, verified, alerted, guided and fixed. Without touching a screen." |

**Timing tip:** the full walk takes about two minutes live, so in the edit keep the first step, one
repeat, and the arrival; cut the middle steps.

---

## What is real and what is simulated

- **Real:** voice registration and matching, who may touch which server, the spoken dialogue, the
  timed alert, and the directions logic (including correcting your location).
- **Simulated:** the overheat itself (an alert fires about 8 seconds after you are inside; there is
  no temperature sensor), the building map (a small fixed map of Hall B), and your location (taken
  from the check-in point you used, not from live indoor positioning).
- To fire the alert yourself, any time: `curl -X POST http://localhost:8090/api/scenario/overheat`
  (it only reaches workers who are signed in and responsible for server B).
