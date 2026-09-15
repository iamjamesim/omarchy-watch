# Weather and usage freshness

Keep last-known data while it can still be useful. Mark older readings quietly;
hide values when their meaning expires. Reconnecting or retrying a fetch never
changes a reading's original timestamp.

## Display contract

| Data | Fresh | Cached | Hard boundary |
| --- | --- | --- | --- |
| Codex allowance | Successful observation at most 30 minutes old | Keep percentage and rim; show a small neutral history glyph | At the recorded reset, clear the fill and show `AWAITING UPDATE` |
| Current weather | Observation at most 30 minutes old | Keep temperature/conditions with the history glyph through three hours | After three hours, clear temperature, icon, and conditions |
| Daily high/low | Forecast for the configured location's current day | Keep until that forecast day ends | At local midnight, clear high/low independently of current conditions |

At exactly 30 minutes a reading remains fresh; after that it is cached. Current
weather remains usable through exactly three hours. Reset/midnight boundaries
expire at equality. Future observations are rejected. Missing usage has no rim
fill and shows `LIMITS UNAVAILABLE`; missing weather uses placeholders.

Tapping weather replaces the condition text with the observation age for three
seconds. Tapping allowance replaces the reset line with its observation age.
The numbers stay fixed when history markers appear. A touch that wakes the
screen does not also activate the detail beneath it. Routine refreshes do not
wake the screen, play sounds, or start data-update animations.

## Refresh and recovery

- Weather keeps its 15-minute fetch schedule. Age comes from Open-Meteo's current
  observation timestamp, not download time. A separate fetch timestamp determines
  whether another request is due. The existing minute reconciliation checks that
  deadline, so a fetch's duration cannot postpone the next refresh by a full
  interval. A due refresh starts within the next minute while the laptop is awake.
- Usage uses Omarchy's existing 15-minute agents-panel refresh. The bridge watches
  its usage record for atomic replacements, with a 200 ms debounce and the
  existing 60-second reconciliation as a fallback.
- Startup, laptop resume, network recovery, and resolved watch reconnections
  request overdue usage through `omarchy-agent-usage-update --limits-only codex`.
  This requires the agents widget to be configured with Codex enabled. The
  bridge respects a disabled provider and does not add an independent periodic
  Codex API poller.
- Recovery also refreshes overdue weather. Requests in flight are combined;
  failed requests are limited to one attempt per minute per source during
  repeated recovery events. A changed weather location can start a new request
  after the old request finishes.
- Cached profiles can sync immediately while source fetches run asynchronously.
  Failures retain the last successful values and their original timestamps.
- A weather location/unit change invalidates the old context immediately. A late
  response for the previous context cannot become the active reading or cache.
- Removing the usage source clears its cached allowance. A new successful record
  replaces previous values. Omarchy's current record does not expose an account
  identifier, so the bridge cannot detect an account switch before the source
  reflects it; it does not inspect authentication files to infer one.

Last successful allowance metadata is cached in `omarchy-watch/allowance.json`
under `XDG_CACHE_HOME`. It contains only remaining percentage, selected window,
observation time, and reset time. The cache is validated on read. Weather stores
observation time, fetch time, location/unit context, and the forecast day's end.

Daily expiry uses the forecast location's IANA time zone, including 23/25-hour
DST days. Open-Meteo timestamps are requested as Unix seconds; see its
[time format documentation](https://open-meteo.com/en/docs).

## Protocol and compatibility

Profile v5 appends an eight-byte forecast-day expiry to the v4 layout, for a
111-byte packet. It accepts cached allowance observations, including a passed
reset so firmware can distinguish `AWAITING UPDATE` from no prior reading.
The watch applies age and reset rules locally while disconnected and on wake.

Old desktops and watches still negotiate v1–v4. A v4 watch receives the original
103-byte format, with the original 30-minute allowance expiry. New firmware
accepts legacy packets; full freshness behavior requires v5 on both sides.
A later legacy profile removes newer cached profile layouts so reboot cannot
restore superseded data.

## Verification

Desktop tests cover cache/restart recovery, failed refreshes, context changes,
source deletion, unchanged values with new timestamps, request deduplication,
DST midnight, and Python-to-C packet validation. Simulator tests cover freshness
boundaries, reset/midnight behavior, history markers, and the age-detail text.

Before release, on hardware check fresh/cached transitions, both tap targets and
three-second restoration, wake-touch suppression, overnight recovery, and a
legacy-profile downgrade. Use synthetic source fixtures in the simulator rather
than editing real account usage records.
