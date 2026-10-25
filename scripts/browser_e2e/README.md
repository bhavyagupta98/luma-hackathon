# Browser end-to-end test

Drives Edge/Chrome (headless) through the real pages with a **fake microphone that plays a
WAV file**, so sign-in and spoken commands run without a person or a microphone:
record voice -> gateway verifies it -> redirect -> on-device Whisper -> command -> spoken reply.

The pages are hands-free by default (they listen on their own). This harness drives the manual
fallback (`&manual=1`, hold Space) because a fake microphone file cannot be timed to a voice
prompt. The `enroll` stage predates the spoken-name step, which needs Chrome's real speech
recognition, so run enrollment by hand.

Quick unit checks (no browser): `node unit/listen.test.mjs` (end-of-speech detection) and
`node unit/name.test.mjs` (name parsing).

Setup (needs Node 18+ and Microsoft Edge or Chrome):

    cd scripts/browser_e2e && npm install
    python scripts/make_demo_voices.py && python scripts/demo_setup.py --onboard
    LUMA_GATEWAY_PORT=8081 LUMA_SESSION_TTL_SECONDS=300 luma-gateway     # long session for slow runs

Create two command clips (any speaker, ending in ~1 s of silence), e.g. "Restart server one
hundred." and "Restart server three hundred.", then run the stages in order. The first stage
downloads about 115 MB of speech models into `PROFILE`, which later stages reuse:

    export PROFILE=/tmp/luma-profile AUTH_WAV=samples/avery/auth-1.wav \
           CMD_100=cmd/restart100.wav CMD_300=cmd/restart300.wav SESSION_OUT=/tmp/session.json
    node e2e.mjs warmup
    node e2e.mjs signin                      # expects a redirect to ear.html and a session
    WAV=$CMD_100 node e2e.mjs command        # expects "Task successful."
    node e2e.mjs signin
    WAV=$CMD_300 node e2e.mjs command        # expects "You are not allowed to do this task."

Set `EDGE` (browser path) and `BASE` (default http://localhost:8081) if yours differ.
