# Desktop bridge

The desktop side has two parts separated by a small file/command boundary:

- `omarchy_watchd.py` owns BlueZ discovery, secure pairing, reconnection,
  persistent host identity, and effective-profile synchronization.
- The Omarchy shell plugin watches the daemon's atomic status document and
  invokes `omarchy-watchctl`. Closing or restarting the panel cannot interrupt
  Bluetooth ownership.

## Requirements

- Omarchy 4.0 or newer
- BlueZ and a Bluetooth LE adapter
- Python 3 with `dbus-python` and PyGObject/GLib
- a running user systemd session
- outbound HTTPS access for forecast refreshes

The bridge reads the resolved background, foreground, and accent from
Omarchy's current theme state and reuses Omarchy's canonical weather location.
It fetches Open-Meteo when that location has coordinates, refreshes every 15
minutes while awake, and refreshes immediately after resume or network
recovery. It retains the last successful result for brief offline periods. The
request includes the configured latitude and longitude; the watch itself never
joins Wi-Fi or calls a weather service.

Theme and settings changes are event-driven. The daemon watches Omarchy's
stable state directories, debounces atomic theme swaps for 200 milliseconds,
and compares the resulting profile content with the last acknowledged profile.
A once-per-minute content-hash reconciliation and an immediate resume check
recover from missed filesystem events without continuous short-interval
polling. Bluetooth discovery stops after a watch is found, and unrelated
BlueZ device updates are ignored.

After ownership, the bridge maintains the encrypted BLE connection instead of
disconnecting after every profile write. The watch requests a 200–250 ms
connection interval with a peripheral latency of 3, allowing its radio to skip
idle events and normally check in about once per second. The first transaction
on a new link verifies device identity; later updates use the already verified
link directly. Link loss, Bluetooth restoration, and laptop resume are handled
by BlueZ's native client-profile auto-connect behavior. Connected and
services-resolved properties drive synchronization directly, without
application discovery or reconnect timers. Pending profile work remains
derived from the desired and acknowledged fingerprints throughout recovery.

The bundled endpoint is Open-Meteo's non-commercial free API. Commercial
derivatives must use an appropriate Open-Meteo plan or replace the provider.

## Agent activity

The bridge accepts provider-neutral lifecycle events over its local socket. A
small Codex adapter uses the official
[`UserPromptSubmit`, `Stop`, `Interrupt`, and `SessionEnd` hooks](https://learn.chatgpt.com/docs/hooks).
It never reads transcripts, prompts, or responses.
Running turns live only in memory; the state directory retains opaque IDs and
delivery metadata only for unacknowledged completions.

The watch renders one aggregate state: any completion awaiting attention wins
over running work. Every distinct completion produces one alert, even while an
earlier result still awaits attention. Firmware with speaker support plays the
panel's toggleable completion sound; GPIO18 can also drive an optional motor. A
watch tap acknowledges all completion revisions it has seen. Reconnects reconcile
that revision before sending a current snapshot without repeating delivered
alerts; delayed alerts are limited to results completed within the last two hours.

## Install a development checkout

From the repository root:

```bash
./desktop/install-local.sh
```

The installer copies the daemon, commands, user service, and plugin into
standard per-user locations, merges the lifecycle adapter into
`~/.codex/hooks.json`, starts the service, and enables the right-side bar
widget. Upgrades restart the user daemon and Omarchy shell after the completed
panel installation, while preserving an existing bar placement. It does not
modify Omarchy's system files and requires no root access.
Codex requires review of newly installed user hooks; open `/hooks` in Codex and
trust the Omarchy Watch entries before starting a new session.

Re-run the command after changing desktop source files.

## Remove

From the repository root:

```bash
./desktop/uninstall-local.sh
```

The uninstaller removes only Omarchy Watch's installed files and lifecycle
hook entries. It preserves pairing identity, preferences, state, and forecast
cache so reinstalling can reconnect without pairing again.

## Diagnostics

```bash
omarchy-watchctl status
systemctl --user status omarchy-watch.service
journalctl --user -u omarchy-watch.service -f
```

## Troubleshooting

If a paired watch stops reconnecting, try these steps in order. Check the
status after each step:

```bash
omarchy-watchctl status
```

1. Keep the watch near the computer and close any Bluetooth settings window
   that may still be scanning. Run `omarchy-watchctl sync` once and allow up to
   30 seconds for the connection.
2. Restart only the desktop bridge, then try the sync again:

   ```bash
   systemctl --user restart omarchy-watch.service
   omarchy-watchctl sync
   ```

3. Restart the watch normally, then run `omarchy-watchctl sync` while it is in
   its initial fast-reconnect window.
4. Turn the laptop's Bluetooth off and back on. This will temporarily disconnect
   other Bluetooth accessories.
5. Reboot the laptop if the Bluetooth controller or driver still appears stuck.

Use `omarchy-watchctl rescan` when an unpaired watch is not found. It does not
force a connection to a watch that is already paired.

Do not remove the watch from BlueZ, delete the desktop identity, or erase the
watch flash as routine troubleshooting. The bond and owner identity exist on
both devices, so resetting only one side can prevent them from reconnecting. A
factory reset must deliberately clear both sides; see the
[firmware guide](../firmware/README.md#flash).

Before opening an issue, collect:

```bash
omarchy version
uname -r
omarchy-watchctl status
bluetoothctl show
systemctl --user status omarchy-watch.service --no-pager
journalctl --user -u omarchy-watch.service --since "10 minutes ago" --no-pager
journalctl -b -u bluetooth.service --since "10 minutes ago" --no-pager
```

Review the output before posting it and redact Bluetooth addresses or device
IDs if desired.

The command also accepts `pair <six-digit-code>`, `brightness <20-100>`,
`sync`, and `rescan`. Brightness defaults to 50%; changing it or the resolved
theme requests a five-second watch preview when the battery is above 15%.
Routine weather and time synchronization does not wake the display.

Run the desktop regression tests with:

```bash
python3 -m unittest discover -s desktop/tests
```

Persistent host identity lives at
`$XDG_CONFIG_HOME/omarchy-watch/identity.json` (falling back to
`~/.config`). Runtime socket and status files follow the corresponding XDG
runtime and state directories.

The last acknowledged profile fingerprint and device metadata are persisted in
`$XDG_STATE_HOME/omarchy-watch/sync.json`. The panel derives pending state by
comparing that fingerprint with the daemon's current desired fingerprint; it
does not rely on a mutable pending flag.

Watch settings live beside the identity in `settings.json`.

Unacknowledged agent completion envelopes live in `agent-activity.json`. This
file contains no conversation content and is pruned after acknowledgement or a
24-hour recovery limit.

The forecast cache follows `XDG_CACHE_HOME` (falling back to `~/.cache`).
