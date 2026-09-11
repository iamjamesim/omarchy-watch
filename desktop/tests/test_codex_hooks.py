import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "install-codex-hooks.py"
COMMAND = "~/.local/bin/omarchy-watch-agent-hook"
EVENTS = ("UserPromptSubmit", "Stop", "Interrupt", "SessionEnd")


class CodexHookInstallerTests(unittest.TestCase):
    def run_installer(self, root: Path, *arguments: str) -> None:
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(root)
        subprocess.run(
            [str(SCRIPT), *arguments],
            check=True,
            env=environment,
            capture_output=True,
            text=True,
        )

    def test_install_is_idempotent_and_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "hooks.json"
            path.write_text(
                json.dumps(
                    {
                        "custom": True,
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {"type": "command", "command": "other-hook"}
                                    ]
                                }
                            ]
                        },
                    }
                )
            )

            self.run_installer(root)
            self.run_installer(root)

            document = json.loads(path.read_text())
            self.assertTrue(document["custom"])
            self.assertEqual(
                sum(
                    item.get("command") == COMMAND
                    for groups in document["hooks"].values()
                    for group in groups
                    for item in group.get("hooks", [])
                ),
                len(EVENTS),
            )
            self.assertEqual(
                document["hooks"]["Stop"][0]["hooks"][0]["command"],
                "other-hook",
            )

    def test_remove_deletes_only_watch_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "hooks.json"

            self.run_installer(root)
            document = json.loads(path.read_text())
            document["hooks"]["Stop"][0]["hooks"].append(
                {"type": "command", "command": "other-hook"}
            )
            path.write_text(json.dumps(document))

            self.run_installer(root, "--remove")

            document = json.loads(path.read_text())
            self.assertNotIn("UserPromptSubmit", document["hooks"])
            self.assertNotIn("Interrupt", document["hooks"])
            self.assertNotIn("SessionEnd", document["hooks"])
            self.assertEqual(
                document["hooks"]["Stop"][0]["hooks"],
                [{"type": "command", "command": "other-hook"}],
            )

    def test_remove_is_a_noop_when_hooks_file_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.run_installer(root, "--remove")
            self.assertFalse((root / "hooks.json").exists())


if __name__ == "__main__":
    unittest.main()
