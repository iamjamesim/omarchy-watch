# Agent UX and allowance: local test handoff

## Scope

The `ux/allowance-preview` branch includes the committed `ux/agent-state-motion`
work plus the final happy expression and live Codex allowance rim. The companion
repository's `ux/agent-input-state` branch supplies structured question events.
No release, push, service restart, or flash is part of preparing this branch.

- Working: excited robot, brightness pulse.
- Needs input: excited robot, existing bounce.
- Finished: happy robot (U+F1719), relaxed sway.
- Idle: hidden; tap either attention state to acknowledge.
- Rim: Codex remaining allowance, selected weekly/session window and reset time.
- Needs input: existing same-pitch beep-beep; finished: descending two-note pair.
- Allowance and battery highlight at 20% or less; charging also highlights battery.
- Weather/sync redesign is not included.

## Before touching hardware

Finish the existing battery test and record elapsed runtime, battery percentage,
and relevant usage. Plug in only after that measurement is complete.

Run from the watch repository:

```bash
./tools/render-watchface.sh
python -m unittest discover -s desktop/tests
simulator/build/test-profile
python tools/preview-live-allowance.py
python tools/preview-agent-ux.py
```

In the companion checkout, run its tests with `OMARCHY_WATCH_REPO` set to the
absolute watch checkout path. Its Unix-socket integration test needs permission
to create a temporary socket. This does not contact the actual watch.

## Deployment for the physical test (not performed automatically)

1. Use the existing documented ESP-IDF environment; build and flash this branch
   with `idf.py -C firmware -p <confirmed-watch-port> flash`. Do not erase NVS or
   re-pair merely to upgrade. The existing pairing is intended to survive.
2. Install the updated desktop bridge using `./desktop/install-local.sh`. This
   restarts the bridge and Omarchy shell; do it only after the battery test.
3. The local Codex companion is installed separately. Start a new Codex session
   and inspect/trust its changed `/hooks`. Older open sessions retain their
   original hook paths; avoid removing a cache they still use.
4. Confirm bridge status reports protocol 4. Check the Omarchy agents panel has
   a fresh Codex allowance record. Allow up to 60 seconds for bridge reconciliation.

## Acceptance checks

- Rim geometry is calibrated: 115 px outer radius, 2 px inset, 3 px stroke,
  and 40% accent track. Temporary calibration UI has been removed.

- Start a turn: excited face pulses, not bounces.
- In Plan mode, explicitly ask Codex to use `request_user_input`: it bounces
  while waiting, resumes pulsing after the answer, then uses happy eyes/sway
  after completion. Approval prompts and async questions are not covered.
- Tap finished/needs-input: clear activity; a later distinct event can alert.
- Interrupt a turn: clear activity. Check needs-input plays the familiar two equal notes and finished plays
  the high–low pair. Compare on the physical speaker; the pattern test is not
  a substitute for listening.
- Sleep/wake several times in each state: motion stops asleep and resumes
  without an off-center or rotated stuck glyph.
- Compare rim against the desktop's **used** fraction: 26% used means 74% left.
  Verify the displayed window/reset belongs to the selected limit.
- Disconnect and reconnect normally. The rim becomes unavailable after 30
  minutes from source observation, or when reset passes, even without desktop.
  Do not edit actual account records to force a test; use simulator fixtures.
- Check brightness/theme, weather, battery detail, pairing, and normal reconnect
  still behave as before. Inspect rounded corners and low allowance at wrist scale.

## Compatibility and rollback

Old watch firmware negotiates v1–v3 and receives no allowance extension. Old
desktop software still sends accepted v1–v3 profiles to the new firmware.
Agent completion falls back to the legacy attention state on old watches;
old bridges ignore the new companion's needs-input event.

For rollback, reinstall the previously tested desktop revision and flash the
previously tested firmware without erasing pairing storage. Keep these changes
local until the physical test passes; final release/versioning remains separate.
