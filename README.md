# Omarchy Watch

An Omarchy companion smartwatch for the Waveshare ESP32-S3-Touch-AMOLED-2.06.

![Omarchy Watch synchronized with an Omarchy desktop](docs/images/omarchy-watch-hero.webp)

_This is an independent community project, not an official Omarchy project._

## Key features

<p align="center">
  <img src="docs/images/omarchy-watch-on-wrist.webp" width="560" alt="Omarchy Watch on a wrist with the pink Omarchy theme">
</p>

- A carefully designed watch face using JetBrains Mono and Nerd Fonts glyphs
  to match Omarchy's look and feel.
- Date, time, and weather from your desktop top bar.
- Color scheme automatically synced to your current Omarchy theme.
- Agent status and task completion alerts (Codex-only at the moment).

## Install

For now, the firmware is built from source. A prebuilt release image is planned
for launch.

### 1. Build and flash the watch

Install ESP-IDF 5.5.x, then:

```bash
cd firmware
. /path/to/esp-idf/export.sh
idf.py build
idf.py -p /dev/ttyACM0 flash
```

See the [firmware guide](firmware/README.md) for complete setup and flashing
details.

### 2. Install the Omarchy companion

From the repository root:

```bash
./desktop/install-local.sh
```

The installer adds the desktop bridge, Omarchy bar widget, and Codex lifecycle
hooks without requiring root. Open `/hooks` in Codex and trust the Omarchy
Watch entries before starting a new session.

### 3. Pair

Open Omarchy Watch from the top bar and enter the six-digit code shown on the
watch. Pairing is only required once.

## Agent status and alerts

An Omarchy robot appears while Codex is working. When a turn finishes, the
watch wakes, plays a chime, and gently bounces the robot. The robot remains
until you acknowledge it with a tap. Designed to let you step away and make a
cup of coffee instead of watching the terminal.

The integration uses Codex lifecycle hooks but never reads your prompts,
responses, or transcripts.

## Troubleshooting

Omarchy Watch is new, and Bluetooth behavior can vary across Linux hardware and
drivers. If something does not work, check the
[desktop troubleshooting guide](desktop/README.md#troubleshooting) and
[open an issue](https://github.com/iamjamesim/omarchy-watch/issues) with your
Omarchy version, Bluetooth adapter, and relevant logs. Fixes and PRs are
welcome.

## More details

- [Firmware](firmware/README.md) — build, flash, power, and boot behavior
- [Desktop companion](desktop/README.md) — requirements, settings, and diagnostics
- [Design](docs/design.md) — watch-face and product decisions
- [Connectivity](docs/connectivity.md) — secure pairing and Bluetooth protocol
- [Simulator](simulator/README.md) — deterministic watch-face previews

## License

Project code and design assets are available under the [MIT License](LICENSE).
Generated fonts retain their upstream terms; see
[third-party notices](THIRD_PARTY_NOTICES.md).
