import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


MANAGER_PATH = Path(__file__).parents[1] / "manage_local.py"
SPEC = importlib.util.spec_from_file_location("manage_local", MANAGER_PATH)
manage = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = manage
SPEC.loader.exec_module(manage)


class LocalInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.layout = manage.Layout(
            source_root=Path(__file__).parents[2],
            home=self.home,
            config_home=self.home / ".config",
        )

    def test_install_and_uninstall_round_trip_preserves_application_state(self):
        manage.install_files(self.layout)

        daemon = self.layout.lib_dir / "omarchy_watchd.py"
        command = self.layout.bin_dir / "omarchy-watchctl"
        unit = self.layout.unit_dir / manage.SERVICE_NAME
        manifest = self.layout.plugin_dir / "manifest.json"
        widget = self.layout.plugin_dir / "desktop/plugin/BarWidget.qml"
        for path in (daemon, command, unit, manifest, widget):
            self.assertTrue(path.is_file(), path)
            self.assertFalse(path.is_symlink(), path)
        self.assertEqual(stat.S_IMODE(daemon.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(unit.stat().st_mode), 0o644)

        state = self.layout.config_home / "omarchy-watch/identity.json"
        state.parent.mkdir(parents=True)
        state.write_text("preserved")

        manage.uninstall_files(self.layout)
        manage.uninstall_files(self.layout)  # A repeated removal is a no-op.

        self.assertFalse(daemon.exists())
        self.assertFalse(command.exists())
        self.assertFalse(unit.exists())
        self.assertFalse(self.layout.plugin_dir.exists())
        self.assertEqual(state.read_text(), "preserved")

    def test_install_refuses_a_symlinked_destination_component(self):
        victim = self.root / "victim"
        victim.mkdir()
        (self.home / ".local").mkdir()
        (self.home / ".local/lib").symlink_to(victim, target_is_directory=True)

        with self.assertRaises(manage.InstallError):
            manage.install_file(
                self.layout.source_root / "manifest.json",
                self.layout.lib_dir / "manifest.json",
                0o644,
            )

        self.assertEqual(list(victim.iterdir()), [])

    def test_install_refuses_a_symlinked_destination_file(self):
        destination = self.home / "destination"
        destination.mkdir()
        victim = self.root / "victim.txt"
        victim.write_text("unchanged")
        (destination / "manifest.json").symlink_to(victim)

        with self.assertRaises(manage.InstallError):
            manage.install_file(
                self.layout.source_root / "manifest.json",
                destination / "manifest.json",
                0o644,
            )

        self.assertEqual(victim.read_text(), "unchanged")

    def test_removal_unlinks_a_directory_symlink_without_following_it(self):
        parent = self.home / "plugins"
        parent.mkdir()
        victim = self.root / "victim"
        victim.mkdir()
        marker = victim / "keep"
        marker.write_text("safe")
        link = parent / "watch"
        link.symlink_to(victim, target_is_directory=True)

        manage.remove_tree(link)

        self.assertFalse(link.exists())
        self.assertEqual(marker.read_text(), "safe")

    def test_open_parent_descriptor_prevents_directory_swap_redirect(self):
        parent = self.home / "destination"
        parent.mkdir()
        moved = self.home / "opened-destination"
        victim = self.root / "victim"
        victim.mkdir()

        with manage.pinned_directory(parent) as descriptor:
            parent.rename(moved)
            parent.symlink_to(victim, target_is_directory=True)
            manage.install_file_at(
                self.layout.source_root / "manifest.json",
                descriptor,
                "manifest.json",
                0o644,
            )

        self.assertTrue((moved / "manifest.json").is_file())
        self.assertFalse((victim / "manifest.json").exists())

    def test_clean_environment_drops_path_and_shell_startup_injection(self):
        with mock.patch.dict(
            os.environ,
            {"PATH": str(self.root), "BASH_ENV": str(self.root / "payload")},
        ):
            environment = manage.clean_environment(self.layout)

        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertNotIn("BASH_ENV", environment)
        self.assertNotIn(str(self.root), environment.values())

    def test_relative_xdg_config_home_is_rejected(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            with self.assertRaises(manage.InstallError):
                manage.default_layout()

    def test_relative_executable_is_rejected(self):
        with self.assertRaises(manage.InstallError):
            manage.verify_absolute_executable("systemctl")


if __name__ == "__main__":
    unittest.main()
