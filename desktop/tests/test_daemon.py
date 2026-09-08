#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import unittest

import dbus


DAEMON_PATH = Path(__file__).parents[1] / "daemon" / "omarchy_watchd.py"
SPEC = importlib.util.spec_from_file_location("omarchy_watchd", DAEMON_PATH)
daemon = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(daemon)


class PlainValueTests(unittest.TestCase):
    def test_binary_bluez_property_is_not_decoded_as_utf8(self):
        value = dbus.ByteArray(bytes([0xFE, 0xFF]))

        self.assertEqual(daemon.plain(value), bytes([0xFE, 0xFF]))

    def test_nested_dbus_values_become_builtin_values(self):
        value = {
            dbus.String("Connected"): dbus.Boolean(True),
            dbus.String("RSSI"): dbus.Int16(-42),
        }

        self.assertEqual(daemon.plain(value), {"Connected": True, "RSSI": -42})


if __name__ == "__main__":
    unittest.main()
