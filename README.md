# Omarchy Watch

An Omarchy companion smartwatch for the
[Waveshare ESP32-S3-Touch-AMOLED-2.06](https://www.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-2.06).

![Omarchy Watch synchronized with an Omarchy desktop](docs/images/omarchy-watch-hero.webp)

_This is an independent community project, not an official Omarchy project._

## Key features

<p align="center">
  <img src="docs/images/omarchy-watch-on-wrist.webp" width="560" alt="Omarchy Watch on a wrist with a pink theme, Codex allowance rim, and reset countdown">
</p>

- A watch face designed to match Omarchy's look and feel with JetBrains Mono and Nerd Fonts glyphs.
- Date, time, and weather from your desktop top bar.
- Color scheme automatically synced to your current Omarchy theme.
- Codex remaining allowance and reset countdown from Omarchy's agents panel, with a colored rim showing how much is left.
- Last-known weather and usage stay visible while useful, with a history marker and tap-to-view update age.
- Distinct Codex working, needs-input, and done indicators, with separate sounds for input requests and completion, through an optional companion integration.

Allowance tracking, data freshness, and the new Codex indicators are unreleased.
To test them, build and install both the desktop bridge and firmware from this
checkout. Needs-input alerts require the optional Codex companion v0.2.0 or newer.

## Install

The easiest way to get started is to ask your coding agent to follow the steps below. It can flash the watch, install the bar widget and desktop client, and guide you through pairing.

Omarchy Watch requires Omarchy 4.0 or newer, Bluetooth LE, and the exact
Waveshare ESP32-S3-Touch-AMOLED-2.06 board. The board is development hardware,
not a waterproof consumer watch.

### 1. Flash the watch

Download `omarchy-watch-v0.5.3-flash.tar.gz` from the
[latest release](https://github.com/iamjamesim/omarchy-watch/releases/latest),
extract it, connect the board's USB-C programming port, and run:

```bash
./flash.sh /dev/ttyACM0
```

The release bundle requires Espressif's `esptool`. It writes the bootloader,
partition table, and application separately so firmware upgrades preserve the
watch's pairing and settings. See the [firmware guide](firmware/README.md) for
source builds, recovery, and complete flashing details.

### 2. Install the bar widget and desktop client

Clone the repository, then run its installer:

```bash
git clone https://github.com/iamjamesim/omarchy-watch.git
cd omarchy-watch
./desktop/install-local.sh
```

The installer adds the desktop bridge and Omarchy bar widget without requiring
root.

### 3. Pair

Pair through the Omarchy Watch panel, not Omarchy's general Bluetooth panel or `bluetoothctl`. When the desktop client discovers an unpaired watch, its top-bar panel opens automatically and focuses the code field. Enter the six-digit code shown on the watch and select **Pair**.

If discovery takes longer than expected, open the persistent watch icon and
select **Scan Again**. Pairing is only required once.

### 4. Optional: enable Codex activity indicators

Codex activity, needs-input, and completion alerts are available through the separate
[Omarchy Watch for Codex](https://github.com/iamjamesim/omarchy-watch-codex)
companion, distributed as a Codex plugin and managed independently through
Codex. This keeps the base watch installation independent of agent
configuration and lets users enable or remove Codex support without
reinstalling Omarchy Watch. The companion is never installed automatically.

Needs-input alerts cover blocking questions and permission requests. After
installing or updating the companion, start a new Codex session and review its
hooks with `/hooks`. Allowance tracking reads Omarchy's agents panel separately
and does not require the companion plugin.

If an agent is performing this installation, it should explain that the
companion adds Codex activity and tool hooks and ask whether the user wants this
feature. It must not install or configure the companion unless the user gives
separate, explicit approval. Review the companion's behavior and privacy
disclosure before opting in; installing Omarchy Watch alone does not constitute
consent to install the Codex integration.

## Update

Update the desktop client from its checkout:

```bash
git pull --ff-only
./desktop/install-local.sh
```

Flash the three-file bundle from the newest tagged release to update the watch
without erasing its bond or settings.

## Remove

From the repository checkout:

```bash
./desktop/uninstall-local.sh
```

Removal stops the bridge and removes its commands, panel, and service. Pairing
identity, settings, and cached state are deliberately preserved so a reinstall
can reconnect. The identity is also the watch's owner credential: deleting only
the desktop copy would require a watch factory reset before it could be paired
again. For coordinated removal of both sides, see the
[desktop guide](desktop/README.md#complete-reset-or-removal).

## Troubleshooting

Bluetooth behavior can vary across Linux hardware and drivers. If something does not work, check the [desktop troubleshooting guide](desktop/README.md#troubleshooting) and [open an issue](https://github.com/iamjamesim/omarchy-watch/issues) with your Omarchy version, Bluetooth adapter, and relevant logs. Fixes and PRs are welcome.

## More details

- [Firmware](firmware/README.md) — build, flash, power, and boot behavior
- [Desktop client](desktop/README.md) — requirements, settings, and diagnostics
- [Data freshness](docs/data-freshness.md) — cached readings, expiry, and recovery
- [Design](docs/design.md) — watch-face and product decisions
- [Connectivity](docs/connectivity.md) — secure pairing and Bluetooth protocol
- [Simulator](simulator/README.md) — deterministic watch-face previews

## License

Project code and design assets are available under the [MIT License](LICENSE).
Generated fonts retain their upstream terms; see
[third-party notices](THIRD_PARTY_NOTICES.md).
