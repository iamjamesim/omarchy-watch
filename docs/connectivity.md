# Connectivity and pairing

The normal setup path is Bluetooth LE. USB is reserved for firmware,
diagnostics, and recovery; it is not an ownership shortcut.

## Ownership flow

1. An unowned watch advertises the Omarchy Watch service and displays a
   randomly generated six-digit passkey.
2. The desktop bridge discovers the service. Its bar widget appears only when
   a watch is nearby or already owned.
3. The user enters the displayed passkey in the bar panel.
4. BlueZ and NimBLE create an authenticated LE Secure Connections bond.
5. Across that encrypted link, the desktop sends protocol version 1 of the
   effective profile, including its persistent random owner ID.
6. The watch commits the owner, complete effective profile, and profile
   revision to NVS before leaving the setup screen. It also writes UTC to the
   board RTC.

The Bluetooth address is a transport locator, never product identity. The
watch creates a persistent random 128-bit device ID and the desktop creates a
persistent random 128-bit host ID. A later transport can reuse those identities
without pretending a USB port or Wi-Fi address is an owner.

Version 1 deliberately supports one desktop owner. Supporting another desktop
will require an explicit invitation or reset rather than silently replacing
the current owner.

## BLE contract

| Role | UUID |
| --- | --- |
| Omarchy Watch service | `7f510001-1b15-4f0d-b7a5-4cf3a2c98ee1` |
| Effective profile write | `7f510002-1b15-4f0d-b7a5-4cf3a2c98ee1` |
| Device identity read | `7f510003-1b15-4f0d-b7a5-4cf3a2c98ee1` |

Profile writes require authenticated encryption. Integers are little-endian.
The version 1 packet is a complete 36-byte snapshot:

| Bytes | Field |
| ---: | --- |
| 2 | `OW` magic |
| 1 | protocol version |
| 1 | message kind (`1` = effective profile) |
| 4 | monotonic profile revision |
| 8 | Unix time |
| 2 | current UTC offset in minutes |
| 1 | hour cycle (`12` or `24`) |
| 1 | reserved |
| 16 | desktop owner ID |

The initial identity value is 32 bytes and reports the supported protocol
range, ownership flag, device ID, capability bits, and firmware version.
Future versions add new message kinds rather than changing a published packet.

The version 1 capability bits are time sync (`1 << 0`), hour cycle (`1 << 1`),
and a board RTC (`1 << 2`). Capability bits describe optional device behavior;
they do not change the packet layout.

## Reconnect and boot contract

The NimBLE bond, watch device ID, owner ID, effective profile, and latest
profile revision live in NVS. The desktop host ID lives in the user's XDG
config directory, while transient panel status is an atomic document in the
XDG state directory. Neither side treats the BLE address as durable identity.

After an ordinary reboot, an owned watch reads UTC from the PCF85063A and the
display offset/hour cycle from its cached profile before Bluetooth starts. It
does not wait for the desktop to become a watch again. If the RTC oscillator
stop flag is set, its calendar is invalid, or its value predates the last
successfully cached sync, the watch keeps its ownership and bond but displays
`TIME NOT SET`; the desktop reconnects and rewrites both RTC and profile
without asking the user to pair again.

Firmware updates should preserve NVS. Erasing flash is an explicit factory
reset and requires removing the stale bond from BlueZ as well.

## Current vertical slice

The first working slice pairs, persists the bond, identities, and effective
profile, and sends desktop time, current UTC offset, and desktop-derived hour
cycle. It renders a live clock and restores it from the board RTC across normal
restarts. Theme, live weather, explicit settings overrides, seasonal timezone
rules, and watch-side reset UI remain subsequent profile work.
