# Watch-face simulator

This host renderer compiles the same `watch_face_layout.c`, generated fonts,
and LVGL major/minor version as the ESP32 firmware. It produces deterministic
410 x 502 RGB565 previews without flashing or connecting a watch.

## Requirements

- CMake 3.16 or newer
- Ninja
- ImageMagick 7 (`magick`)
- LVGL downloaded by an ESP-IDF configure or build

Configure the firmware once so ESP-IDF materializes its locked managed
components, then run the preview tool from the repository root:

```bash
cd firmware
. /path/to/esp-idf/export.sh
idf.py reconfigure
cd ..
./tools/render-watchface.sh
```

The ignored `simulator/output/` directory receives:

- `watchface.png` — the complete rectangular framebuffer
- `watchface-rounded.png` — the same pixels with a display-shaped alpha mask

The date, time, weather, and battery state in
`simulator/render_watchface.c` are stable design fixtures. Change the shared
layout for visual work; change the fixtures only when deliberately expanding
the content-fit cases.

For palette checks, the renderer binary also accepts resolved background,
foreground, and accent colors after its output path:

```bash
simulator/build/render-watchface /tmp/watch.ppm '#101315' '#cacccc' '#798186'
```

Append a percentage to render the temporary battery-detail state:

```bash
simulator/build/render-watchface /tmp/battery.ppm '#101315' '#cacccc' '#798186' '70%'
```

For agent animation previews, append a state and an output frame prefix:

```bash
simulator/build/render-watchface /tmp/watch.ppm '#101315' '#cacccc' '#798186' '70%' finished /tmp/sway
magick -delay 4 -loop 0 /tmp/sway-*.ppm /tmp/sway.gif
```

States are `working`, `attention`, `finished`, and `idle`. The renderer emits
complete animation cycles at 40 ms intervals using the same animations as the
firmware, then checks sleep/wake and idle animation cleanup. Use a fresh frame
prefix for each state so frames from longer sequences do not remain in the glob.

The PNG is exact at the framebuffer level. Display calibration, ambient light,
rounded glass, and viewing distance still make the physical watch the final
authority for optical decisions.

## Allowance preview and resource-color checks

These options use fixed fixtures and the shared firmware rim implementation.
Every render also checks the 20% highlight boundary, charging, unavailable data,
and the reset line's foreground color.

```bash
WATCH_PREVIEW_ALLOWANCE=rim WATCH_PREVIEW_REMAINING=79 \
  simulator/build/render-watchface simulator/output/allowance-rim.ppm
```

Remaining accepts 0–100 or -1 for unavailable; default is 79. Reset text is a
fixed fixture. Try 10, 0, 100, and -1 as well. Without these environment variables
the original simulator behavior is unchanged. See
[allowance-preview.md](../docs/allowance-preview.md) for the data source and display behavior.

Render local allowance through the real bridge encoder and firmware validator,
without Bluetooth or services (requires the desktop Python dependencies):

```bash
python tools/preview-live-allowance.py
python tools/preview-agent-ux.py
```

These retain a live allowance PNG and three agent-state GIFs; intermediate files
are removed. Live allowance preview time/weather remain fixtures. Generated
images are ignored. `simulator/build/test-profile` checks wire validation and
expiry, and desktop tests also pass an encoded Python packet into that C test.

When accepting a visual checkpoint, copy `simulator/output/watchface.png` to
`docs/images/plain-01.png` to retain the accepted device framebuffer. The repository landing page uses
photos in `docs/images/omarchy-watch-hero.webp` and
`docs/images/omarchy-watch-on-wrist.webp`. Generated working previews remain ignored.
