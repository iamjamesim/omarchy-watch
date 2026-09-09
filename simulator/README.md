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

The PNG is exact at the framebuffer level. Display calibration, ambient light,
rounded glass, and viewing distance still make the physical watch the final
authority for optical decisions.

When accepting a visual checkpoint, copy `simulator/output/watchface.png` to
`docs/images/plain-01.png` so the repository landing page shows the accepted
device framebuffer. Generated working previews remain ignored.
