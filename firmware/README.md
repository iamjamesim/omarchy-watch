# Firmware

ESP-IDF firmware for the Waveshare ESP32-S3-Touch-AMOLED-2.06. It renders the
Plain 01 face, exposes the versioned Omarchy Watch BLE service, and uses the
board's PCF85063A real-time clock to restore trusted time after a restart. It
also reads battery level and charging state directly from the AXP2101 power
manager.

The display runs at 30% brightness and sleeps after 15 seconds; touching it
wakes it and restarts the timeout. Dynamic CPU frequency scaling, tickless
idle, automatic light sleep, Bluetooth modem sleep, and slower owned-device
advertising reduce the idle load. The cached v2 profile restores the last
theme and forecast without waiting for Bluetooth.

While USB power is present, firmware holds a no-light-sleep lock so the native
USB serial/JTAG interface remains reliable for flashing and monitoring. The
lock is released when the AXP2101 reports that external power has gone away.

The RTC is powered from the board battery through its power-management circuit.
A normal reboot therefore keeps time. A complete battery loss can set the RTC's
oscillator-stop flag; firmware then shows `TIME NOT SET` instead of displaying a
plausible but wrong clock, and the bonded desktop repairs it on reconnect.

## Toolchain

- ESP-IDF 5.5.x
- target `esp32s3`
- Waveshare board support package 2.x
- Waveshare PCF85063A component 2.x
- LVGL 9.5.x

Managed component versions are recorded in `dependencies.lock`. The partition
layout follows Waveshare's current known-good examples, which use a 16 MB
partition map even though the board is sold with 32 MB flash.

## Build

```bash
cd firmware
. /path/to/esp-idf/export.sh
idf.py build
```

The face itself lives in `main/watch_face_layout.c`. Both the device UI and the
host preview renderer compile that source, so layout changes have one source of
truth. From the repository root, run `./tools/render-watchface.sh` after the
first firmware configure/build; see `simulator/README.md` for details.

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

The RTC stores UTC. The cached profile supplies the display offset, hour cycle,
palette, and forecast. The offset is refreshed whenever the desktop syncs;
automatic seasonal timezone transitions while fully offline are future profile
work.
