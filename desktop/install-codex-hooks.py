#!/usr/bin/env python3
"""Add or remove the Omarchy Watch lifecycle adapter in Codex hooks."""

import argparse
import json
import os
from pathlib import Path


COMMAND = "~/.local/bin/omarchy-watch-agent-hook"
EVENTS = ("UserPromptSubmit", "Stop", "Interrupt", "SessionEnd")


def handler(event: str) -> dict:
    return {"type": "command", "command": COMMAND, "timeout": 3}


def load_document(path: Path, *, missing_ok: bool = False) -> dict | None:
    if missing_ok and not path.exists():
        return None
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError:
        document = {}
    if not isinstance(document, dict) or not isinstance(document.get("hooks", {}), dict):
        raise SystemExit(f"Refusing to replace invalid Codex hooks file: {path}")
    return document


def write_document(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def install(path: Path) -> None:
    document = load_document(path)
    assert document is not None

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

    write_document(path, document)


def remove(path: Path) -> None:
    document = load_document(path, missing_ok=True)
    if document is None:
        return

    hooks = document["hooks"]
    for event in EVENTS:
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        retained_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                retained_groups.append(group)
                continue
            retained_handlers = [
                item for item in group["hooks"]
                if not isinstance(item, dict) or item.get("command") != COMMAND
            ]
            if retained_handlers:
                group["hooks"] = retained_handlers
                retained_groups.append(group)
        if retained_groups:
            hooks[event] = retained_groups
        else:
            hooks.pop(event, None)

    write_document(path, document)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remove", action="store_true", help="remove only Omarchy Watch hook entries"
    )
    args = parser.parse_args()
    root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    path = root / "hooks.json"
    if args.remove:
        remove(path)
    else:
        install(path)


if __name__ == "__main__":
    main()
