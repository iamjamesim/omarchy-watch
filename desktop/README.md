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

The command also accepts `pair <six-digit-code>`, `sync`, and `rescan`.

Run the desktop regression tests with:

```bash
python3 -m unittest discover -s desktop/tests
```

Persistent host identity lives at
`$XDG_CONFIG_HOME/omarchy-watch/identity.json` (falling back to
`~/.config`). Runtime socket and status files follow the corresponding XDG
runtime and state directories.
