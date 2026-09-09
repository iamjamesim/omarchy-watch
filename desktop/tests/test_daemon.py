#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest import mock

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


class EffectiveContextTests(unittest.TestCase):
    def test_theme_palette_reads_resolved_omarchy_colors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.toml"
            path.write_text('background = "#123456"\nforeground = "#ABCDEF"\n')

            self.assertEqual(
                daemon.theme_palette(path),
                (bytes.fromhex("123456"), bytes.fromhex("abcdef")),
            )

    def test_invalid_theme_colors_fall_back_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.toml"
            path.write_text('background = "transparent"\nforeground = "#010203"\n')

            self.assertEqual(
                daemon.theme_palette(path),
                (daemon.DEFAULT_BACKGROUND, bytes.fromhex("010203")),
            )

    def test_open_meteo_weather_reuses_omarchy_location_and_units(self):
        report = {
            "current": {"temperature_2m": 68.4, "weather_code": 2, "is_day": 1},
            "daily": {"temperature_2m_max": [72.2], "temperature_2m_min": [60.6]},
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(report).encode()

        opener = mock.Mock(return_value=Response())
        with (mock.patch.object(daemon, "weather_location", return_value={
                  "name": "SAN FRANCISCO", "latitude": 37.77, "longitude": -122.42,
              }),
              mock.patch.object(daemon, "weather_unit_override", return_value=True)):
            weather = daemon.fetch_weather(opener)

        self.assertEqual(weather["temperature"], 68)
        self.assertEqual(weather["high"], 72)
        self.assertEqual(weather["low"], 61)
        self.assertEqual(weather["code"], 2)
        self.assertEqual(weather["location"], "SAN FRANCISCO")
        request = opener.call_args.args[0]
        self.assertIn("temperature_unit=fahrenheit", request.full_url)

    def test_profile_v2_is_complete_and_fixed_width(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.watch_protocol = 2
        watch.last_profile_revision = 0
        watch.context_dirty = True
        watch.host_id = bytes(range(16))
        watch.palette = (bytes.fromhex("101315"), bytes.fromhex("cacccc"))
        watch.weather = {
            "valid": True,
            "updatedAt": int(time.time()),
            "temperature": 68,
            "high": 72,
            "low": 61,
            "code": 2,
            "night": False,
            "fahrenheit": True,
            "location": "SAN FRANCISCO",
        }
        watch.desktop_hour_cycle = lambda: 12

        payload = watch.profile_payload()

        self.assertEqual(len(payload), 81)
        unpacked = struct.unpack("<2sBBIqhBB16s3s3sqhhhB24s", payload)
        self.assertEqual(unpacked[:3], (b"OW", 2, 1))
        self.assertEqual(unpacked[6], 12)
        self.assertEqual(unpacked[7] & 0b11, 0b11)
        self.assertEqual(unpacked[9], bytes.fromhex("101315"))
        self.assertEqual(unpacked[10], bytes.fromhex("cacccc"))
        self.assertEqual(unpacked[12:16], (68, 72, 61, 2))
        self.assertEqual(unpacked[16].rstrip(b"\0"), b"SAN FRANCISCO")
        self.assertFalse(watch.context_dirty)

    def test_profile_v2_marks_stale_weather_unavailable(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.watch_protocol = 2
        watch.last_profile_revision = 0
        watch.context_dirty = True
        watch.host_id = bytes(16)
        watch.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND)
        watch.weather = {
            "valid": True,
            "updatedAt": int(time.time()) - daemon.WEATHER_MAX_AGE_SECONDS - 1,
            "temperature": 68,
            "high": 72,
            "low": 61,
            "code": 2,
            "location": "SAN FRANCISCO",
        }
        watch.desktop_hour_cycle = lambda: 24

        unpacked = struct.unpack(
            "<2sBBIqhBB16s3s3sqhhhB24s", watch.profile_payload()
        )

        self.assertEqual(unpacked[7] & 1, 0)
        self.assertEqual(unpacked[11], 0)
        self.assertEqual(unpacked[16], bytes(24))


if __name__ == "__main__":
    unittest.main()
