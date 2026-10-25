# Demo run sheet: nobody touches the screen

One terminal command starts everything. The presenter only talks. The screen is for the audience.

```powershell
.\.venv\Scripts\python scripts\run_demo.py --fresh
```

`--fresh` forgets the demo voice so the story starts from nothing. Press Ctrl+C in the terminal to
stop. Use `--debug` to show the on-screen log while rehearsing. `run_demo.py register` or
`run_demo.py signin` skip the spoken menu and start at that step.

## What happens (and what to say)

| # | The system says | You say | What the audience sees |
|---|---|---|---|
| 0 | "Welcome to Luma. Say register voice, or say sign in." | "Register voice." | The voice menu, then "Okay, let's register you." |
| 1 | "Welcome. Let's get you registered. First, tell me your name…" | "My name is *Bhavya Gupta*." | Red "Listening…" button, then the name is acknowledged |
| 2 | "Phrase 1 of 3. Please say: My voice is my badge, please verify me." | (read the phrase) | A tone, then "Got it." |
| 3 | Phrases 2 and 3 the same way, then **"Bhavya Gupta, you are enrolled."** | (read each phrase) | Registered; the page moves on by itself |
| 4 | "Welcome. Please verify your voice to go inside." (the page moves on by itself; you can also begin at the menu by saying "sign in") | "This is my voice, please let me in." | Green "Verified" |
| 5 | **"Bhavya Gupta is authenticated."** then "You are inside. Say a command, for example, fix server A." | | The command page opens |
| 6 | | "Fix server A." | **"Task successful."** |
| 7 | | "Restart server C." | **"You are not allowed to do this task."** (that server belongs to someone else) |
| 8 | After 60 s: "Your session has expired. Please authenticate again." | | Back to sign-in, hands-free |

**The wrong-person moment:** at step 4, have someone else speak. The system says
**"You are not registered."** and asks again; the real person then succeeds.

Servers can be named by letter or number: A, B, C are the same as "one hundred", "two hundred",
"three hundred". The signed-in demo user may control A and B; C belongs to a different operator.

## Rehearsal checklist

- Use the same microphone for registering and signing in. A headset is best (less echo).
- Run once before the audience arrives; the first speech recognition needs internet (Chrome's).
- Speak after the tone, in a normal voice, and pause for about a second when you finish.
- To re-run the story: stop (Ctrl+C) and start again with `--fresh`.
- If a voice is refused too often, the match threshold is `LUMA_VOICE_MATCH_THRESHOLD` (0.6).
- Starting at sign-in only: `python scripts\run_demo.py signin`.

## How it works without a tap

Browsers refuse to speak or open the microphone until the page is clicked once. The launcher opens
Chrome with the autoplay switches the demo needs and runs a small driver that clicks the page's
"Tap to start" cover for you, on the first page and after each page change. The product itself still
needs that one tap per page load because of the browser rule; the driver only stands in for it.
