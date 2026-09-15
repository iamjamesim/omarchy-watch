# Codex activity and allowance checks

## Scope

This checkout supports distinct Codex activity states and allowance
tracking. Activity events come from the separately installed
[Codex companion v0.2.0 or newer](https://github.com/iamjamesim/omarchy-watch-codex).
Allowance comes from Omarchy's agents panel. This checklist describes repeatable
validation; it is not a record of completed test runs.

## Automated checks

Run from the watch repository:

```bash
./tools/render-watchface.sh
python -m unittest discover -s desktop/tests
ctest --test-dir simulator/build --output-on-failure
python tools/preview-live-allowance.py
python tools/preview-agent-ux.py
```

In the companion checkout, run its tests with `OMARCHY_WATCH_REPO` set to the
absolute watch checkout path. Its Unix-socket integration test needs permission
to create a temporary socket. This does not contact the actual watch.

## Hardware test setup

1. Use the existing documented ESP-IDF environment; build and flash the revision under test
   with `idf.py -C firmware -p <confirmed-watch-port> flash`. Do not erase NVS or
   re-pair merely to upgrade. The existing pairing is intended to survive.
2. Install the updated desktop bridge using `./desktop/install-local.sh`. This
   restarts the bridge and Omarchy shell.
3. The Codex companion is installed separately with explicit opt-in. Start a new Codex session
   and inspect/trust its changed `/hooks`. Older open sessions retain their
   original hook paths; avoid removing a cache they still use.
4. Confirm bridge status reports protocol 5. Check the Omarchy agents panel has
   a fresh Codex allowance record. File updates should sync promptly; the fallback
   reconciliation runs every 60 seconds.

## Acceptance checks

- Start a turn: the robot pulses in opacity while screen brightness stays fixed.
- In Plan mode, explicitly ask Codex to use `request_user_input`: it bounces
  while waiting, resumes pulsing after the answer, then uses happy eyes/sway
  after completion.
- Approve a harmless permission request: needs-input clears when the tool
  finishes. Deny a request: attention clears at turn end if no tool result arrives.
- Async questions and ordinary commands must not raise needs-input.
- With two sessions waiting for input, resolving one must leave the other active.
- Tap finished/needs-input: clear activity; a later distinct event can alert.
- Interrupt a turn: clear activity. Check needs-input plays the familiar two equal notes and finished plays
  the high–low pair. Compare on the physical speaker; the pattern test is not
  a substitute for listening.
- Sleep/wake several times in each state: motion stops asleep and resumes
  without an off-center or rotated stuck glyph.
- Compare rim against the desktop's **used** fraction: 26% used means 74% left.
  Verify the displayed window/reset belongs to the selected limit.
- Disconnect and reconnect normally. Cached readings show a history marker
  after 30 minutes; the rim clears at reset even without desktop. Check weather
  current/daily cutoffs and both tap-for-age targets using
  [data-freshness.md](data-freshness.md).
  Do not edit actual account records to force a test; use simulator fixtures.
- Check brightness/theme, weather, battery detail, pairing, and normal reconnect
  still behave as before. Inspect rounded corners and low allowance at wrist scale.
  Verify allowance and battery highlights at 20% or less, plus the charging highlight.

## Compatibility and rollback

Peers negotiating v1–v3 exchange no allowance fields. The bridge also supports
the intermediate v4 layout; full freshness behavior requires v5 on both sides.
Agent completion falls back to the legacy attention state on old watches;
old bridges ignore the new companion's needs-input event.

For rollback, reinstall the previously tested desktop revision and flash the
previously tested firmware without erasing pairing storage. See
[releasing.md](releasing.md) for packaging and publication checks.
