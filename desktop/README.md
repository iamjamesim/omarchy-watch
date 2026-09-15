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
It fetches Open-Meteo when that location has coordinates. While awake, the
minute reconciliation starts a refresh once the last fetch is 15 minutes old;
resume and network recovery also check for overdue data. It retains useful
last-successful readings while offline. The
request includes the configured latitude and longitude; the watch itself never
joins Wi-Fi or calls a weather service.

Theme and settings changes are event-driven. The daemon watches Omarchy's
stable state directories, debounces atomic theme swaps for 200 milliseconds,
and compares the resulting profile content with the last acknowledged profile.
A once-per-minute content-hash reconciliation and an immediate resume check
recover from missed filesystem events without continuous short-interval
polling. Discovery remains active while an unpaired watch awaits its code,
then stops when pairing begins. Unrelated BlueZ device updates are ignored.

After ownership, the bridge maintains the encrypted BLE connection instead of
disconnecting after every profile write. The watch requests a 200–250 ms
connection interval with a peripheral latency of 3, allowing its radio to skip
idle events and normally check in about once per second. The first transaction
on a new link verifies device identity; later updates use the already verified
link directly. Link loss, Bluetooth restoration, and laptop resume are handled
by BlueZ's native client-profile auto-connect behavior, with bounded,
backed-off connection requests as a fallback. Connected and services-resolved
properties drive synchronization directly without general discovery. Pending
profile work remains derived from the desired and acknowledged fingerprints
throughout recovery.

The bundled endpoint is Open-Meteo's non-commercial free API. Commercial
derivatives must use an appropriate Open-Meteo plan or replace the provider.

## Weather and usage recovery

The bridge retains last-successful readings while refreshing overdue sources on
resume, network recovery, and watch reconnect. Usage-file changes trigger prompt
sync; recovery can invoke Omarchy's existing limits-only collector. See
[data freshness](../docs/data-freshness.md) for timestamps, cache files, and
expiry rules.

## Codex alerts

The panel's **Sound** switch applies to both **needs input** (blocking questions
and permission requests) and **task completion** (the turn ended). Turning sound
off keeps activity indicators and the existing visual alert behavior. Working
activity remains quiet. The stored `completionSound` key and `sound` command
remain compatible with earlier versions.

Permission requests can trigger an alert even when Codex's automatic reviewer
resolves them. The companion receives the request before it knows whether human
input is required; the current hook contract does not expose a reliable signal
for that distinction. Permission alerts remain enabled to avoid missing genuine
blocking requests. See the [Codex hook documentation](https://learn.chatgpt.com/docs/hooks#permissionrequest).

## Install a development checkout

From the repository root:

```bash
./desktop/install-local.sh
```

The installer copies the daemon, control command, user service, and plugin into
standard per-user locations, starts the service, and enables the right-side bar
widget. Upgrades restart the user daemon and Omarchy shell after the completed
panel installation, while preserving an existing bar placement. It does not
modify Omarchy's system files and requires no root access.

Re-run the command after changing desktop source files.

## Pair a new watch

Do not start in Omarchy's general Bluetooth panel or pair with `bluetoothctl`.
The desktop bridge must own the pairing transaction so it can verify the
six-digit passkey and establish the watch owner identity.

After the firmware starts on an unowned watch, the Omarchy Watch panel opens
automatically and focuses its code field. Enter the code displayed on the
watch and select **Pair**. If the watch is not found, use **Scan Again** in
that same panel. A single pairing submission makes up to three bounded
transport attempts with the same code when BlueZ cannot initially reach the
watch. The watch icon and pairing panel remain available while the bridge is
searching.

## Remove

From the repository root:

```bash
./desktop/uninstall-local.sh
```

The uninstaller removes only Omarchy Watch's installed files. It preserves
pairing identity, preferences, state, and forecast cache so reinstalling can
reconnect without pairing again. The identity is the watch's desktop-owner
credential; deleting it without also factory-resetting the watch would leave
that watch owned by an identity the desktop no longer has.

## Complete reset or removal

A watch factory reset clears its copy of the Bluetooth bond and owner state,
but BlueZ still retains the laptop's copy. **Disconnect** is not enough: remove
or forget **Omarchy Watch** in the general Bluetooth settings, then close that
panel so it is no longer scanning. The equivalent command is:

```bash
bluetoothctl remove <watch-address>
```

The companion will rediscover the unowned watch and open its pairing panel.
The existing desktop identity and preferences may remain; after secure pairing
they become the reset watch's owner and settings again.

For a completely fresh installation, first back up and then remove the
app-owned desktop directories after running the uninstaller:

```text
$XDG_CONFIG_HOME/omarchy-watch       (fallback: ~/.config/omarchy-watch)
$XDG_STATE_HOME/omarchy-watch        (fallback: ~/.local/state/omarchy-watch)
$XDG_CACHE_HOME/omarchy-watch        (fallback: ~/.cache/omarchy-watch)
```

Do this only together with the watch factory reset and BlueZ removal. Resetting
only one side intentionally does not produce a reusable pairing.

## Diagnostics

```bash
omarchy-watchctl status
systemctl --user status omarchy-watch.service
journalctl --user -u omarchy-watch.service -f
journalctl -k --since "10 minutes ago" --no-pager
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
5. If BlueZ says it is scanning but still cannot find an advertising watch,
   restart the system Bluetooth service:

   ```bash
   sudo systemctl restart bluetooth.service
   ```

   This temporarily disconnects every Bluetooth accessory, but preserves their
   bonds.
6. Reboot the laptop if the Bluetooth controller or driver still appears stuck.

Use `omarchy-watchctl rescan` when an unpaired watch is not found. It does not
force a connection to a watch that is already paired.

Do not remove the watch from BlueZ, delete the desktop identity, or erase the
watch flash as routine troubleshooting. The bond and owner identity exist on
both devices, so resetting only one side can prevent them from reconnecting. A
factory reset must deliberately clear both sides; see
[Complete reset or removal](#complete-reset-or-removal).

Before opening an issue, collect:

```bash
omarchy version
uname -r
omarchy-watchctl status
bluetoothctl show
systemctl --user status omarchy-watch.service --no-pager
journalctl --user -u omarchy-watch.service --since "10 minutes ago" --no-pager
journalctl -b -u bluetooth.service --since "10 minutes ago" --no-pager
journalctl -k --since "10 minutes ago" --no-pager
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

Unacknowledged agent input requests and completions live in `agent-activity.json`. This
file contains no conversation content and is pruned after acknowledgement or a
24-hour recovery limit.

The forecast cache follows `XDG_CACHE_HOME` (falling back to `~/.cache`).
