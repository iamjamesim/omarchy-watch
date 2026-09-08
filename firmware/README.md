# Firmware

ESP-IDF firmware for the Waveshare ESP32-S3-Touch-AMOLED-2.06. It renders the
Plain 01 face, exposes the versioned Omarchy Watch BLE service, and uses the
board's PCF85063A real-time clock to restore trusted time after a restart.

The RTC is powered from the board battery through its power-management circuit.
A normal reboot therefore keeps time. A complete battery loss can set the RTC's
oscillator-stop flag; firmware then shows `TIME NOT SET` instead of displaying a
plausible but wrong clock, and the bonded desktop repairs it on reconnect.

## Toolchain

- ESP-IDF 5.5.x
- target `esp32s3`
- Waveshare board support package 2.x
- Waveshare PCF85063A component 2.x

Managed component versions are recorded in `dependencies.lock`. The partition
layout follows Waveshare's current known-good examples, which use a 16 MB
partition map even though the board is sold with 32 MB flash.

## Build

```bash
cd firmware
. /path/to/esp-idf/export.sh
idf.py build
```

## Flash

Connect the USB-C programming port, then flash without erasing so the BLE bond,
owner identity, and cached preferences survive firmware updates:

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

Exit the monitor with `Ctrl+]`.

`erase-flash` is a factory reset, not a routine development step. It deletes
ownership and bonding state on the watch; remove the corresponding device from
BlueZ before pairing it again.

## Boot behavior

| Ownership | RTC | Initial screen | Recovery |
| --- | --- | --- | --- |
| none | any | six-digit pairing code | pair from the Omarchy panel |
| owned | valid | watch face immediately | background sync refreshes it |
| owned | invalid/unavailable | `TIME NOT SET` | bonded desktop reconnects and syncs |

The RTC stores UTC. The cached profile supplies the display offset and hour
cycle. In v0.1 the offset is refreshed whenever the desktop syncs; automatic
seasonal timezone transitions while fully offline are future profile work.
