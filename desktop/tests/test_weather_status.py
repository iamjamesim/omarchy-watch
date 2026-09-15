"""Weather source health must survive successful delivery of a cached profile."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from test_daemon import daemon


class WeatherStatusTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = int(time.time())
        self.location = {"name": "TEST", "latitude": 1, "longitude": 2}
        self.clock = mock.patch.object(daemon.time, "time", return_value=self.now).start()
        self.location_mock = mock.patch.object(daemon, "weather_location", return_value=self.location).start()
        self.units_mock = mock.patch.object(daemon, "weather_unit_override", return_value=False).start()
        self.addCleanup(mock.patch.stopall)
        self.watch = w = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        w.watch_protocol = 5
        w.weather = self.reading(600)
        w.weather_refresh_context = [1, 2, False]
        w.weather_fetch_failed = False
        w.context_refresh_inflight = False
        w.state = {"status": "ready", "paired": True, "connected": True}
        w.state_dir = w.cache_dir = self.root
        w.status_path = self.root / "status.json"
        w.weather_cache_path = self.root / "weather.json"
        w.desired_fingerprint = w.synced_fingerprint = w.inflight_fingerprint = "same"
        w.profile_fingerprint = mock.Mock(return_value="same")
        w.ensure_connection = mock.Mock()
        w.save_sync_state = mock.Mock()
        w.pending_passkey = None
        w.preview_until = w.preview_sent_until = 0
        w.inflight_theme = "TEST"
        w.force_sync_requested = False
        w.log = mock.Mock()
        w.write_state()

    def reading(self, age):
        return {"valid": True, "updatedAt": self.now - age,
                "fetchedAt": self.now - age, "dailyExpiresAt": self.now + 7200,
                "context": [1, 2, False], "temperature": 18, "high": 22,
                "low": 14, "code": 2, "location": "TEST", "fahrenheit": False}

    def status(self):
        return json.loads(self.watch.status_path.read_text())

    def start_refresh(self):
        w = self.watch
        w.theme_path = w.theme_shell_path = self.root / "theme"
        w.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND, daemon.DEFAULT_ACCENT)
        with mock.patch.object(daemon, "theme_palette", return_value=w.palette), \
                mock.patch.object(daemon.threading, "Thread") as thread:
            w.refresh_effective_context()
            return thread

    def test_failure_survives_successful_watch_sync(self):
        w = self.watch
        w.weather_context_ready(None, "DNS lookup failed")
        w.on_profile_written()
        status = self.status()
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["message"], "Watch sync complete")
        self.assertEqual(status["lastSynced"], self.now)
        self.assertTrue(status["weatherFetchFailed"])
        self.assertEqual(status["weatherUpdated"], self.now - 600)
        self.assertEqual(status["weatherFetched"], self.now - 600)
        self.assertNotIn("DNS lookup failed", json.dumps(status))

    def test_retry_stays_visible_until_success(self):
        w = self.watch
        w.weather = self.reading(1900)
        w.weather_context_ready(None, "offline")
        thread = self.start_refresh()
        thread.assert_called_once()
        self.assertTrue(self.status()["weatherRefreshing"])
        self.assertTrue(self.status()["weatherFetchFailed"])
        w.weather_context_ready(self.reading(0), "")
        status = self.status()
        self.assertFalse(status["weatherRefreshing"])
        self.assertFalse(status["weatherFetchFailed"])
        self.assertEqual(status["weatherStatus"], "fresh")
        self.assertEqual(status["weatherUpdated"], self.now)

    def test_first_fetch_failure_has_no_usable_data(self):
        w = self.watch
        w.weather = {}
        thread = self.start_refresh()
        with mock.patch.object(daemon, "fetch_weather", side_effect=OSError("offline")), \
                mock.patch.object(daemon.GLib, "idle_add", side_effect=lambda fn, *args: fn(*args)):
            thread.call_args.kwargs["target"]()
        status = self.status()
        self.assertEqual(status["weatherStatus"], "unavailable")
        self.assertTrue(status["weatherFetchFailed"])
        self.assertFalse(status["weatherRefreshing"])
        self.assertEqual(status["weatherUpdated"], 0)

    def test_freshness_updates_without_a_new_profile_or_radio_write(self):
        w = self.watch
        self.clock.return_value = self.now + 1200
        w.refresh_desired_profile()
        self.assertEqual(self.status()["weatherStatus"], "fresh")
        self.clock.return_value += 1
        w.refresh_desired_profile()
        self.assertEqual(self.status()["weatherStatus"], "cached")
        w.ensure_connection.assert_not_called()
        self.assertEqual(self.status()["desiredRevision"], "same")

    def test_forecast_only_and_midnight_expiry(self):
        w = self.watch
        w.weather = self.reading(4 * 3600)
        w.write_state()
        self.assertEqual(self.status()["weatherStatus"], "forecast")
        self.clock.return_value = w.weather["dailyExpiresAt"]
        w.write_state()
        self.assertEqual(self.status()["weatherStatus"], "unavailable")
        self.assertEqual(self.status()["weatherUpdated"], 0)

    def test_legacy_current_conditions_keep_the_legacy_cutoff(self):
        w = self.watch
        w.watch_protocol = 3
        w.weather = self.reading(4 * 3600)
        w.write_state()
        self.assertEqual(self.status()["weatherStatus"], "cached")
        w.weather = self.reading(6 * 3600 + 1)
        w.write_state()
        self.assertEqual(self.status()["weatherStatus"], "unavailable")

    def test_location_change_does_not_show_previous_data_or_failure(self):
        w = self.watch
        w.weather_context_ready(None, "offline")
        self.location_mock.return_value = {"latitude": 3, "longitude": 4}
        w.write_state()
        status = self.status()
        self.assertEqual(status["weatherStatus"], "unavailable")
        self.assertFalse(status["weatherFetchFailed"])
        self.assertEqual(status["weatherUpdated"], 0)
        self.assertEqual(status["weatherFetched"], 0)
        thread = self.start_refresh()
        thread.assert_called_once()
        self.assertTrue(self.status()["weatherRefreshing"])
        self.assertFalse(self.status()["weatherFetchFailed"])

    def test_units_change_invalidates_weather_and_resets_previous_failure(self):
        w = self.watch
        w.weather_context_ready(None, "offline")
        self.units_mock.return_value = True
        thread = self.start_refresh()
        thread.assert_called_once()
        status = self.status()
        self.assertEqual(status["weatherStatus"], "unavailable")
        self.assertTrue(status["weatherRefreshing"])
        self.assertFalse(status["weatherFetchFailed"])

    def test_unconfigured_location_does_not_report_cached_weather_as_healthy(self):
        self.location_mock.return_value = {}
        self.watch.write_state()
        status = self.status()
        self.assertEqual(status["weatherStatus"], "unconfigured")
        self.assertEqual(status["weatherUpdated"], 0)

    def test_manual_sync_retries_overdue_weather_without_bypassing_cooldown(self):
        w = self.watch
        w.weather = self.reading(1900)
        thread = self.start_refresh()
        thread.assert_called_once()
        w.weather_context_ready(None, "offline")
        with mock.patch.object(daemon, "theme_palette", return_value=w.palette), \
                mock.patch.object(daemon.threading, "Thread") as retry:
            w.handle_command({"command": "sync"})
        retry.assert_not_called()
        w.ensure_connection.assert_called_once_with("manual sync")
        self.assertTrue(self.status()["weatherFetchFailed"])

    def test_manual_sync_starts_overdue_refresh(self):
        w = self.watch
        w.weather = self.reading(1900)
        w.theme_path = w.theme_shell_path = self.root / "theme"
        w.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND, daemon.DEFAULT_ACCENT)
        with mock.patch.object(daemon, "theme_palette", return_value=w.palette), \
                mock.patch.object(daemon.threading, "Thread") as thread:
            w.handle_command({"command": "sync"})
        thread.assert_called_once()
        self.assertTrue(self.status()["weatherRefreshing"])
        w.ensure_connection.assert_called_once_with("manual sync")
