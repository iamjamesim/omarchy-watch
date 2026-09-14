# Codex allowance rim

Compare two static, simulator-only concepts on the existing watch face:

- **Bar:** replace location with provider, remaining percentage, a thin bar,
  and the allowance window/reset countdown.
- **Rim:** move the gauge to a thin rounded perimeter; keep the same textual
  information in the location compartment so the frame has an explicit meaning.

Both use the existing palette, no animation, and no sync footer. Fixtures cover
79%, 10%, 0%, 100%, and unavailable. The default 79% is the complement of a
21%-used example, not a live account reading. Reset time is fixed sample text.
The rim is now the selected implementation and uses the shared firmware renderer.
The bar remains simulator-only. Transport and expiration are implemented;
physical-watch validation is still required.

The rim keeps the bottom compartment quieter and provides an ambient fuel signal.
Provider, remaining percentage, window, and reset countdown remain explicit so
the frame is not mistaken for watch battery.

## Existing desktop source

The installed Omarchy agents panel documents its display-ready records at
`${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage/<provider>.json`.
The relevant installed sources are:

- `/usr/share/omarchy/shell/plugins/agents/README.md`
- `/usr/share/omarchy/shell/plugins/agents/Panel.qml`
- `/usr/share/omarchy/bin/omarchy-agent-usage-update`
- `/usr/share/omarchy/bin/omarchy-agent-usage-codex`

The updater atomically replaces each JSON record. The panel normally requests
refreshes every 900 seconds and can refresh limits when opened. This is a local
Omarchy integration contract, not a versioned public watch protocol.

For Codex, the collector obtains limits through its existing app-server RPC
integration. The watch bridge can read the resulting record; it need not inspect
credentials, scan transcripts, or launch another API poller.

Relevant shape (illustrative):

```json
{
  "schemaVersion": 1,
  "id": "codex",
  "updatedAt": "2026-09-14T18:00:00+00:00",
  "usageStatusText": "",
  "limits": [
    {
      "label": "Weekly (7-day)",
      "percent": 0.21,
      "resetsAt": "2026-09-19T14:00:00+00:00"
    }
  ]
}
```

`percent` is the **used fraction**, not 0–100. Validate a finite value in [0,1]
and display `round(100 * (1 - percent))`. Unknown must not become 0% or 100%.
Use `resetsAt` for the countdown and retain the source `updatedAt`; receiving
the same file again or syncing Bluetooth must not refresh its age.

The collector can write a fresh record with an error and no limits. A failed
updater can also leave an old record behind. Both need explicit unavailable/
stale handling. Passing the reset deadline must not manufacture a fresh 100%.
If the agents panel is disabled, records may stop updating: reading this source
does not by itself provide an independent collection service.

## Implemented behavior

- Codex only. Select the most depleted supported window and its reset time.
  Equal fractions use the first window in the source record.
- Accept schema 1, finite fractions in [0,1], timezone-aware timestamps,
  `Weekly (7-day)` and numeric `h window` / `m window` labels. Unknown windows
  make the reading unavailable rather than hide a potentially binding limit.
- Missing, malformed, provider-error, future-dated, reset-past, or more-than-30-
  minute-old data becomes unavailable. Diagnostic changes are logged once per
  transition. Extra unrelated JSON fields are ignored.
- Reuse the bridge's 60-second context reconciliation; no new API calls or
  collection process. Profile v4 adds 18 bytes to v3; negotiation retains the
  original v1/v2/v3 wire shapes for older watches.
- The watch independently expires readings and updates the countdown while
  awake/on wake. A reset deadline never implies a refill without new data.
- Rim geometry updates only when remaining changes. No new animation, alert,
  sound, wake timer, or always-on display behavior.

The 30-minute freshness policy and physical readability remain trial decisions.
General weather/sync UX is separate. See [agent-local-test.md](agent-local-test.md)
for the deployment/test handoff.
