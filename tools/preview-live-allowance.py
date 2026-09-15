#!/usr/bin/env python3
"""Read local allowance -> real profile encoder -> firmware validator/renderer.

No service startup, Bluetooth access, collection, or installation. Output stays
in the ignored simulator/output directory; time and weather remain fixtures.
"""
import importlib.util
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("watch_bridge", ROOT / "desktop/daemon/omarchy_watchd.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
watch = bridge.WatchDaemon.__new__(bridge.WatchDaemon)
watch.watch_protocol = 5
watch.last_profile_revision = 0
watch.force_sync_requested = False
watch.current_theme_name = lambda: "PREVIEW"
watch.host_id = bytes(16)
watch.palette = (bridge.DEFAULT_BACKGROUND, bridge.DEFAULT_FOREGROUND, bridge.DEFAULT_ACCENT)
watch.brightness = bridge.DEFAULT_BRIGHTNESS
watch.preview_until = 0
watch.preview_sent_until = 0
watch.weather = {}
watch.desktop_hour_cycle = lambda: 24
output = ROOT / "simulator/output"
output.mkdir(parents=True, exist_ok=True)
packet = output / "allowance-live.bin"
ppm = output / "allowance-live.ppm"
png = output / "allowance-live.png"
packet.write_bytes(watch.profile_payload())
subprocess.run([str(ROOT / "simulator/build/test-profile"), str(packet)], check=True)
environment = {**os.environ, "WATCH_PREVIEW_PROFILE": str(packet)}
environment.pop("WATCH_PREVIEW_ALLOWANCE", None)
subprocess.run([str(ROOT / "simulator/build/render-watchface"), str(ppm)],
               env=environment, check=True)
subprocess.run(["magick", str(ppm), str(png)], check=True)
ppm.unlink()
packet.unlink()
print(png)
