#!/usr/bin/env python3
"""Merge the Omarchy Watch lifecycle adapter into the user Codex hooks."""

import json
import os
from pathlib import Path


COMMAND = "~/.local/bin/omarchy-watch-agent-hook"
EVENTS = ("UserPromptSubmit", "Stop", "Interrupt", "SessionEnd")


def handler(event: str) -> dict:
    return {"type": "command", "command": COMMAND, "timeout": 3}


def main() -> None:
    root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    path = root / "hooks.json"
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError:
        document = {}
    if not isinstance(document, dict) or not isinstance(document.get("hooks", {}), dict):
        raise SystemExit(f"Refusing to replace invalid Codex hooks file: {path}")

    hooks = document.setdefault("hooks", {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise SystemExit(f"Refusing to replace invalid {event} hooks in {path}")
        installed = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            installed.extend(
                item for item in group.get("hooks", [])
                if isinstance(item, dict) and item.get("command") == COMMAND
            )
        if installed:
            for item in installed:
                item.clear()
                item.update(handler(event))
        else:
            groups.append({"hooks": [handler(event)]})

    root.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


if __name__ == "__main__":
    main()
