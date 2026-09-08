# Omarchy Watch

An Omarchy companion for the Waveshare ESP32-S3-Touch-AMOLED-2.06. The first
checkpoint is intentionally small: a polished watch face, secure Bluetooth
pairing, and a dependable clock that survives normal restarts.

This is an independent community project, not an official Omarchy project.

## v0.1 checkpoint

- Plain 01 watch face at the display's native 410 x 502 resolution
- JetBrains Mono typography with time, date, and a weather design fixture
- authenticated Bluetooth LE pairing using the six-digit code on the watch
- persistent watch and desktop identities; pairing is a one-time setup
- automatic time, UTC offset, and 12/24-hour synchronization from Omarchy
- board RTC restore at boot, with an honest unsynchronized state if its time
  cannot be trusted
- Omarchy bar panel for discovery, pairing, connection status, and manual sync

Weather and palette synchronization are not live yet. The current `68°` value
and Solitude colors are deterministic fixtures used to settle the physical
design before expanding the profile.

## Product boundary

The watch inherits useful context from Omarchy without mirroring the desktop
UI. The desktop resolves defaults and future overrides into a complete,
versioned profile; the firmware stores that effective profile and stays useful
when the computer is away.

An owned watch has three truthful boot outcomes:

1. A valid RTC and cached profile render the face immediately.
2. A lost or invalid RTC shows `TIME NOT SET` while the existing Bluetooth bond
   reconnects and repairs it automatically.
3. A watch with no owner shows its pairing code.

See [the design notes](docs/design.md) and
[connectivity contract](docs/connectivity.md) for the decisions and evolution
constraints behind this split.

## Repository

- `firmware/` — ESP-IDF firmware for the Waveshare board
- `desktop/` — BlueZ bridge, command-line client, and Omarchy shell plugin
- `prototype/` — browser design reference and deterministic screenshots
- `docs/` — product, UI, pairing, and protocol decisions
- `tools/` — reproducible font generation

Build and installation details live in `firmware/README.md` and
`desktop/README.md`.

## Direction after v0.1

The next coherent slice is the real effective profile: resolved Omarchy
palette, weather location/data/units, explicit follow-or-override settings,
and seasonal timezone updates. Media controls and additional faces should come
after that foundation rather than widening the first checkpoint.

Longer-term possibilities include a deeper Omarchy companion, agent-generated
watch software, daily-watch fundamentals, and ports to hardware such as
Pebble. The first version remains a focused prototype, not a smartwatch OS.

## License

Project code and design assets are available under the [MIT License](LICENSE).
The generated LVGL font data in `firmware/main/fonts/` is derived from
JetBrains Mono Nerd Font and remains under the
[SIL Open Font License 1.1](firmware/main/fonts-OFL.txt).
