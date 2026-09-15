# Codex allowance rim

The allowance display uses a thin rounded perimeter, with provider, remaining
percentage, and reset countdown below the weather.

Physical-watch review settled on a 115 px outer radius, 2 px centerline inset,
and 3 px stroke. The depleted track uses the accent at 40% opacity; remaining
allowance uses full opacity. There is no animation or sync footer.

Remaining text uses the accent at 20% or less, otherwise normal foreground.
The reset line always uses foreground. Unknown or expired readings do not trigger
a low warning. Battery uses the same 20% threshold, plus accent while charging;
the lightning bolt remains charging-only.

The simulator uses the shared firmware renderer. Its default 79% is a fixture,
not a live account reading, and reset time is fixed sample text unless using
the live-profile preview.

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

The bridge retains validated last-successful metadata when a subsequent fetch
fails. It watches source-record updates and requests overdue limits through the
existing collector during recovery. See [data-freshness.md](data-freshness.md)
for the source, display, and reset contract.

## Implemented behavior

- Codex only. Select the most depleted supported window and its reset time.
  Equal fractions use the first window in the source record.
- Accept schema 1, finite fractions in [0,1], timezone-aware timestamps,
  `Weekly (7-day)` and numeric `h window` / `m window` labels. Unknown windows
  make the reading unavailable rather than hide a potentially binding limit.
- Malformed or failed observations preserve a valid cached reading. Future-dated
  observations are rejected. Reset-past readings show `AWAITING UPDATE`, never
  an inferred refill. Extra unrelated JSON fields are ignored.
- Watch source-file updates with 60-second reconciliation as fallback. Recovery
  can invoke the existing limits collector. Profile v5 is 111 bytes; negotiation
  retains the original v1–v4 wire shapes for older watches.
- The watch marks readings cached after 30 minutes and updates the countdown
  while awake/on wake. A reset deadline never implies a refill without new data.
- Rim geometry updates only when remaining changes. No new animation, alert,
  sound, wake timer, or always-on display behavior.

See [agent-local-test.md](agent-local-test.md) for automated and hardware
validation checks.
