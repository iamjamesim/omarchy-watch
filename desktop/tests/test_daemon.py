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


class ConnectionStateTests(unittest.TestCase):
    def test_in_progress_connection_remains_recoverable(self):
        class InProgress(dbus.DBusException):
            _dbus_error_name = "org.bluez.Error.InProgress"

        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.connect_inflight = True
        watch.write_state = mock.Mock()

        with mock.patch.object(daemon.GLib, "timeout_add") as timeout:
            watch.on_connect_error(InProgress("Operation already in progress"))

        self.assertFalse(watch.connect_inflight)
        watch.write_state.assert_called_once_with(
            status="syncing", message="Connecting to watch"
        )
        timeout.assert_called_once_with(1000, watch.retry_connection)


class EffectiveContextTests(unittest.TestCase):
    def test_theme_palette_reads_resolved_omarchy_colors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.toml"
            path.write_text(
                'background = "#123456"\n'
                'foreground = "#ABCDEF"\n'
                'accent = "#FEDCBA"\n'
            )

            self.assertEqual(
                daemon.theme_palette(path),
                (
                    bytes.fromhex("123456"),
                    bytes.fromhex("abcdef"),
                    bytes.fromhex("fedcba"),
                ),
            )

    def test_invalid_theme_colors_fall_back_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.toml"
            path.write_text(
                'background = "transparent"\n'
                'foreground = "#F0F0F0"\n'
                'accent = "invalid"\n'
            )

            self.assertEqual(
                daemon.theme_palette(path),
                (
                    daemon.DEFAULT_BACKGROUND,
                    bytes.fromhex("f0f0f0"),
                    daemon.DEFAULT_ACCENT,
                ),
            )

    def test_theme_palette_prefers_resolved_bar_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            colors = Path(directory) / "colors.toml"
            shell = Path(directory) / "shell.toml"
            colors.write_text(
                'background = "#101010"\n'
                'foreground = "#F0F0F0"\n'
                'accent = "#80C0FF"\n'
            )
            shell.write_text(
                '[bar]\nbackground = "#202020"\ntext = "#E0E0E0"\n'
            )

            self.assertEqual(
                daemon.theme_palette(colors, shell),
                (
                    bytes.fromhex("202020"),
                    bytes.fromhex("e0e0e0"),
                    bytes.fromhex("80c0ff"),
                ),
            )

    def test_low_contrast_accent_falls_back_to_foreground(self):
        background = bytes.fromhex("101010")
        foreground = bytes.fromhex("f0f0f0")
        accent = bytes.fromhex("202020")

        self.assertEqual(
            daemon.readable_accent(background, foreground, accent), foreground
        )

    def test_brightness_setting_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.config_dir = Path(directory)
            watch.settings_path = watch.config_dir / "settings.json"
            watch.brightness = 65

            watch.save_settings()

            self.assertEqual(watch.load_brightness(), 65)

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
        watch.palette = (
            bytes.fromhex("101315"),
            bytes.fromhex("cacccc"),
            bytes.fromhex("798186"),
        )
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
        watch.palette = (
            daemon.DEFAULT_BACKGROUND,
            daemon.DEFAULT_FOREGROUND,
            daemon.DEFAULT_ACCENT,
        )
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

    def test_profile_v3_adds_accent_brightness_and_preview(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.watch_protocol = 3
        watch.last_profile_revision = 0
        watch.context_dirty = True
        watch.host_id = bytes(range(16))
        watch.palette = (
            bytes.fromhex("101315"),
            bytes.fromhex("cacccc"),
            bytes.fromhex("798186"),
        )
        watch.brightness = 55
        watch.preview_until = time.monotonic() + 10
        watch.preview_sent_until = 0
        watch.weather = {
            "valid": True,
            "updatedAt": int(time.time()),
            "temperature": 68,
            "high": 72,
            "low": 61,
            "code": 2,
            "location": "SAN FRANCISCO",
        }
        watch.desktop_hour_cycle = lambda: 24

        payload = watch.profile_payload()

        self.assertEqual(len(payload), 85)
        unpacked = struct.unpack("<2sBBIqhBB16s3s3sqhhhB24s3sB", payload)
        self.assertEqual(unpacked[:3], (b"OW", 3, 1))
        self.assertEqual(unpacked[7] & (1 << 3), 1 << 3)
        self.assertEqual(unpacked[17], bytes.fromhex("798186"))
        self.assertEqual(unpacked[18], 55)
        self.assertEqual(watch.preview_sent_until, watch.preview_until)

    def test_profile_v3_does_not_preview_expired_change(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.watch_protocol = 3
        watch.last_profile_revision = 0
        watch.context_dirty = True
        watch.host_id = bytes(16)
        watch.palette = (
            daemon.DEFAULT_BACKGROUND,
            daemon.DEFAULT_FOREGROUND,
            daemon.DEFAULT_ACCENT,
        )
        watch.brightness = daemon.DEFAULT_BRIGHTNESS
        watch.preview_until = time.monotonic() - 1
        watch.preview_sent_until = 0
        watch.weather = {}
        watch.desktop_hour_cycle = lambda: 24

        unpacked = struct.unpack(
            "<2sBBIqhBB16s3s3sqhhhB24s3sB", watch.profile_payload()
        )

        self.assertEqual(unpacked[7] & (1 << 3), 0)
        self.assertEqual(watch.preview_sent_until, 0)


if __name__ == "__main__":
    unittest.main()
