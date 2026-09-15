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
        self.monotonic = mock.patch.object(daemon.time, "monotonic", return_value=1000).start()
        self.location_mock = mock.patch.object(daemon, "weather_location", return_value=self.location).start()
        self.units_mock = mock.patch.object(daemon, "weather_unit_override", return_value=False).start()
        self.addCleanup(mock.patch.stopall)
        self.watch = w = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        w.watch_protocol = 5
        w.weather = self.reading(600)
        w.weather_refresh_context = [1, 2, False]
        # The cached request is outside the retry cooldown, independent of host uptime.
        w.weather_refresh_attempt = self.monotonic.return_value - 600
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

    def start_refresh(self, *, retry=False):
        w = self.watch
        w.theme_path = w.theme_shell_path = self.root / "theme"
        w.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND, daemon.DEFAULT_ACCENT)
        with mock.patch.object(daemon, "theme_palette", return_value=w.palette), \
                mock.patch.object(daemon.threading, "Thread") as thread:
            w.refresh_effective_context(retry_weather=retry)
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
        self.monotonic.return_value += 60
        self.clock.return_value += 60
        thread = self.start_refresh()
        thread.assert_called_once()
        self.assertTrue(self.status()["weatherRefreshing"])
        self.assertTrue(self.status()["weatherFetchFailed"])
        w.weather_context_ready(self.reading(0), "")
        status = self.status()
        self.assertFalse(status["weatherRefreshing"])
        self.assertFalse(status["weatherFetchFailed"])
        self.assertEqual(status["weatherManualRetryAt"], 0)
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

    def test_manual_sync_only_sends_available_data(self):
        w = self.watch
        w.weather = self.reading(1900)
        with mock.patch.object(w, "refresh_effective_context") as refresh:
            w.handle_command({"command": "sync"})
        refresh.assert_not_called()
        w.ensure_connection.assert_called_once_with("manual sync")
        self.assertTrue(w.force_sync_requested)

    def test_automatic_retries_back_off_and_reset_after_success(self):
        w = self.watch
        w.weather = self.reading(1900)
        self.start_refresh().assert_called_once()
        for delay in (60, 120, 240, 480, 900, 900):
            w.weather_context_ready(None, "offline")
            self.assertEqual(self.status()["weatherRetryAt"], self.clock.return_value + delay)
            self.monotonic.return_value += delay - 1
            self.clock.return_value += delay - 1
            self.start_refresh().assert_not_called()
            self.monotonic.return_value += 1
            self.clock.return_value += 1
            self.start_refresh().assert_called_once()
        reading = self.reading(0)
        reading["fetchedAt"] = self.clock.return_value
        w.weather_context_ready(reading, "")
        self.assertFalse(self.status()["weatherFetchFailed"])
        self.assertEqual(self.status()["weatherRetryAt"], 0)
        self.start_refresh().assert_not_called()
        self.clock.return_value += 900
        self.monotonic.return_value += 900
        self.start_refresh().assert_called_once()
        w.weather_context_ready(None, "offline")
        self.assertEqual(self.status()["weatherRetryAt"], self.clock.return_value + 60)

    def test_manual_retry_requires_failure_and_keeps_global_cooldown(self):
        w = self.watch
        w.weather = self.reading(1900)
        self.start_refresh(retry=True).assert_not_called()
        self.start_refresh().assert_called_once()
        w.weather_context_ready(None, "offline")
        self.start_refresh(retry=True).assert_not_called()
        self.monotonic.return_value += 60
        self.clock.return_value += 60
        self.start_refresh(retry=True).assert_called_once()
        w.weather_context_ready(None, "offline")
        self.monotonic.return_value += 60
        self.clock.return_value += 60
        self.start_refresh().assert_not_called()  # The automatic backoff is now two minutes.
        self.start_refresh(retry=True).assert_called_once()
        self.start_refresh(retry=True).assert_not_called()  # A request is already in flight.

    def test_location_changes_cannot_bypass_request_cooldown(self):
        w = self.watch
        w.weather = self.reading(1900)
        self.start_refresh().assert_called_once()
        self.location_mock.return_value = {"latitude": 3, "longitude": 4}
        w.weather_context_ready(self.reading(0), "")
        self.start_refresh().assert_not_called()
        self.assertFalse(self.status()["weatherRefreshing"])
        self.monotonic.return_value += 60
        self.start_refresh().assert_called_once()
        self.assertFalse(self.status()["weatherFetchFailed"])

    def test_no_location_does_not_attempt_a_fetch(self):
        self.location_mock.return_value = {}
        self.start_refresh().assert_not_called()

    def prepare_profile(self):
        w = self.watch
        del w.profile_fingerprint
        w.host_id = bytes(16)
        w.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND, daemon.DEFAULT_ACCENT)
        w.brightness = 50
        w.last_profile_revision = 0
        w.current_theme_name = lambda: "TEST"
        w.desktop_hour_cycle = lambda: 24
        w.cached_allowance = mock.Mock(return_value={"remaining": 255, "window": 0,
                                                    "updatedAt": 0, "resetsAt": 0})
        w.profile_payload()

    def test_unchanged_download_does_not_send_another_profile(self):
        self.prepare_profile()
        w = self.watch
        w.synced_fingerprint = w.desired_fingerprint
        weather = dict(w.weather, fetchedAt=self.now)
        w.weather_context_ready(weather, "")
        self.assertEqual(self.status()["weatherFetched"], self.now)
        self.assertEqual(self.status()["desiredRevision"], self.status()["syncedRevision"])
        w.ensure_connection.assert_not_called()

    def test_delivery_records_the_payload_not_a_later_fetch(self):
        self.prepare_profile()
        w = self.watch
        sent = w.inflight_weather
        self.assertEqual(sent["updatedAt"], self.now - 600)
        # A newer fetch arrives while the BLE write is awaiting acknowledgement.
        w.weather = self.reading(0)
        w.desired_fingerprint = "new-data"
        w.sync_connected_profile = mock.Mock()
        w.on_profile_written()
        self.assertEqual(self.status()["weatherUpdated"], self.now)
        self.assertEqual(self.status()["syncedWeather"], sent)
        self.assertNotEqual(self.status()["desiredRevision"], self.status()["syncedRevision"])
        w.sync_connected_profile.assert_called_once()
        # The receipt survives a daemon restart.
        w.sync_state_path = self.root / "sync.json"
        del w.save_sync_state
        w.save_sync_state()
        self.assertEqual(w.load_sync_state()["syncedWeather"], sent)

    def test_failed_delivery_does_not_replace_last_successful_receipt(self):
        w = self.watch
        w.state["syncedWeather"] = {"valid": False}
        w.state["lastSynced"] = self.now - 100
        w.inflight_weather = self.reading(0)
        w.inflight_was_forced = False
        w.handle_transport_error = mock.Mock(return_value=True)
        w.on_profile_error(OSError("disconnected"))
        w.write_state()
        self.assertEqual(self.status()["lastSynced"], self.now - 100)
        self.assertFalse(self.status()["syncedWeather"]["valid"])
