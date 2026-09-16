from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[2]


class SupplyChainTests(unittest.TestCase):
    def test_every_github_action_is_pinned_to_a_full_commit(self):
        references = []
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            references.extend(
                (workflow, match.group(1), match.group(2))
                for match in re.finditer(r"uses:\s+([^@\s]+)@([^\s#]+)", workflow.read_text())
            )

        self.assertTrue(references)
        for workflow, action, revision in references:
            with self.subTest(workflow=workflow.name, action=action):
                self.assertRegex(revision, r"^[0-9a-f]{40}$")

    def test_local_install_launchers_use_a_closed_environment(self):
        for name in ("install-local.sh", "uninstall-local.sh"):
            launcher = (ROOT / "desktop" / name).read_text()
            with self.subTest(launcher=name):
                self.assertTrue(launcher.startswith("#!/usr/bin/bash\n"))
                self.assertIn("/usr/bin/env -i", launcher)
                self.assertIn("/usr/bin/python3 -I", launcher)
                self.assertNotIn("command -v", launcher)


if __name__ == "__main__":
    unittest.main()
