#!/usr/bin/env python3
"""Keep only three GIFs; intermediate frames live in a temporary directory."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
output = root / "simulator/output"
output.mkdir(parents=True, exist_ok=True)
environment = {**os.environ, "WATCH_PREVIEW_ALLOWANCE": "rim", "WATCH_PREVIEW_REMAINING": "79"}
environment.pop("WATCH_PREVIEW_PROFILE", None)
for state in ("working", "attention", "finished"):
    with tempfile.TemporaryDirectory(prefix="watch-agent-preview-") as directory:
        frames = Path(directory)
        subprocess.run([
            str(root / "simulator/build/render-watchface"), str(frames / "final.ppm"),
            "#101315", "#cacccc", "#798186", "70%", state, str(frames / "frame"),
        ], env=environment, check=True)
        target = output / f"agent-{state}-ready.gif"
        subprocess.run(["magick", "-delay", "4", "-loop", "0",
                        *map(str, sorted(frames.glob("frame-*.ppm"))), str(target)], check=True)
        print(target)
