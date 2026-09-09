# Desktop bridge

The desktop side has two parts separated by a small file/command boundary:

- `omarchy_watchd.py` owns BlueZ discovery, secure pairing, reconnection,
  persistent host identity, and effective-profile synchronization.
- The Omarchy shell plugin watches the daemon's atomic status document and
  invokes `omarchy-watchctl`. Closing or restarting the panel cannot interrupt
  Bluetooth ownership.

## Requirements

- Omarchy with the user plugin system
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
link directly. Link loss, Bluetooth restoration, and laptop resume all trigger
one bounded exponential reconnect path. BlueZ's connected and
services-resolved properties drive synchronization directly, without a
separate GATT polling timer. Pending profile work remains derived from the
desired and acknowledged fingerprints throughout recovery.

The bundled endpoint is Open-Meteo's non-commercial free API. Commercial
derivatives must use an appropriate Open-Meteo plan or replace the provider.

## Install a development checkout

From the repository root:

```bash
./desktop/install-local.sh
```

The installer copies the daemon, command, user service, and plugin into
standard per-user locations, starts the service, and enables the right-side bar
widget. It does not modify Omarchy's system files and requires no root access.

Re-run the command after changing desktop source files.

## Diagnostics

```bash
omarchy-watchctl status
systemctl --user status omarchy-watch.service
journalctl --user -u omarchy-watch.service -f
```

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

The forecast cache follows `XDG_CACHE_HOME` (falling back to `~/.cache`).
