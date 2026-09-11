import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "firmware" / "release" / "flash.sh"


class ReleaseFlashTests(unittest.TestCase):
    def run_flash(self, version: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "esptool"
            tool.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = version ]; then\n"
                f"  echo 'esptool.py v{version}'\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' \"$@\"\n"
            )
            tool.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{temporary}:/usr/bin"
            result = subprocess.run(
                [str(SCRIPT), "/dev/fake-watch"],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )
            return result.stdout.splitlines()

    def test_esptool_v4_arguments(self):
        arguments = self.run_flash("4.12.0")
        self.assertIn("write_flash", arguments)
        self.assertIn("--flash_mode", arguments)
        self.assertIn("default_reset", arguments)
        self.assertIn("0x8000", arguments)
        self.assertNotIn("erase_flash", arguments)

    def test_esptool_v5_arguments(self):
        arguments = self.run_flash("5.3.1")
        self.assertIn("write-flash", arguments)
        self.assertIn("--flash-mode", arguments)
        self.assertIn("default-reset", arguments)
        self.assertIn("0x8000", arguments)
        self.assertNotIn("erase-flash", arguments)


if __name__ == "__main__":
    unittest.main()
