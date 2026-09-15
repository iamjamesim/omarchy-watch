"""Freshness is a display policy; failed fetches must not erase good data."""
import datetime as dt
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from test_daemon import daemon


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = int(time.time())
        self.watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        w = self.watch
        w.watch_protocol = 5
        w.allowance_path = self.root / 'usage' / 'codex.json'
        w.allowance_path.parent.mkdir()
        w.allowance_cache_path = self.root / 'cache' / 'allowance.json'
        w.last_allowance = {}
        w.log = mock.Mock()
        w.last_profile_revision = 0
        w.force_sync_requested = False
        w.current_theme_name = lambda: 'TEST'
        w.host_id = bytes(16)
        w.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND, daemon.DEFAULT_ACCENT)
        w.brightness = 50
        w.preview_until = 0
        w.weather = {}
        w.desktop_hour_cycle = lambda: 24
        w.usage_refresh_inflight = False
        w.usage_refresh_attempt = -1000
        w.context_refresh_inflight = False
        w.refresh_desired_profile = mock.Mock()
        w.weather_cache_path = self.root / 'weather.json'
        w.cache_dir = self.root
        w.write_state = mock.Mock()
        w.context_changed = mock.Mock()
        w.usage_monitor_root = None
        w.shell_config_path = self.root / 'shell.json'
        w.shell_config_path.write_text(json.dumps({'bar': {'layout': {'right': [{'id': 'omarchy.agents'}]}}}))

    def record(self, age=0, remaining=54, reset=None, error=''):
        d = {'schemaVersion': 1, 'id': 'codex',
             'updatedAt': dt.datetime.fromtimestamp(self.now-age, dt.timezone.utc).isoformat(),
             'usageStatusText': error,
             'limits': [{'label': 'Weekly (7-day)', 'percent': 1-remaining/100,
                         'resetsAt': dt.datetime.fromtimestamp(reset or self.now+86400, dt.timezone.utc).isoformat()}]}
        self.watch.allowance_path.write_text(json.dumps(d))

    def weather(self, age, expires=None):
        return {'valid': True, 'updatedAt': self.now-age, 'fetchedAt': self.now-age,
                'dailyExpiresAt': expires or self.now+7200, 'context': [1, 2, False],
                'temperature': 18, 'high': 22, 'low': 14, 'code': 2,
                'location': 'TEST', 'fahrenheit': False}

    def test_sleep_keeps_usage_and_original_timestamp(self):
        self.record(age=8*3600)
        first = self.watch.cached_allowance(self.now)
        self.assertEqual(first['remaining'], 54)
        self.assertEqual(first['updatedAt'], self.now-8*3600)
        self.assertEqual(self.watch.cached_allowance(self.now+60), first)
        self.assertEqual(daemon.read_codex_allowance(self.watch.allowance_path, self.now)['remaining'], 255)

    def test_failed_refresh_and_restart_retain_last_success(self):
        self.record(age=3600)
        expected = self.watch.cached_allowance(self.now)
        self.record(error='Codex limits unavailable')
        self.assertEqual(self.watch.cached_allowance(self.now), expected)
        self.watch.last_allowance = {}
        self.assertEqual(self.watch.cached_allowance(self.now), expected)
        self.assertEqual(self.watch.cached_allowance(self.now+900)['updatedAt'], expected['updatedAt'])

    def test_reset_retains_evidence_for_awaiting_update_without_refill(self):
        self.record(age=3600, reset=self.now-1, remaining=4)
        packet = self.watch.profile_payload()
        self.assertEqual(struct.unpack('<BBqq', packet[85:103]), (4, 1, self.now-3600, self.now-1))
        validator = Path(__file__).resolve().parents[2] / 'simulator/build/test-profile'
        if not validator.exists():
            self.skipTest('Build the firmware validator')
        path = self.root / 'profile.bin'
        path.write_bytes(packet)
        result = subprocess.run([str(validator), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_removed_source_invalidates_cached_usage(self):
        self.record()
        self.watch.cached_allowance(self.now)
        self.watch.allowance_path.unlink()
        self.assertEqual(self.watch.cached_allowance(self.now)['remaining'], 255)
        self.assertFalse(self.watch.allowance_cache_path.exists())

    def test_successful_unchanged_usage_gets_a_fresh_timestamp(self):
        self.record(age=7200)
        self.watch.cached_allowance(self.now)
        self.record()
        value = self.watch.cached_allowance(self.now)
        self.assertEqual(value['remaining'], 54)
        self.assertEqual(value['updatedAt'], self.now)

    def test_usage_refresh_deduplicates_recovery_events(self):
        self.record(age=3600)
        with mock.patch.object(daemon.threading, 'Thread') as thread:
            self.watch.refresh_usage_if_due()
            self.watch.refresh_usage_if_due()
            thread.assert_called_once()
            self.assertTrue(self.watch.usage_refresh_inflight)
            with mock.patch.object(daemon.subprocess, 'run') as run, mock.patch.object(daemon.GLib, 'idle_add'):
                thread.call_args.kwargs['target']()
                self.assertEqual(run.call_args.args[0], ['omarchy-agent-usage-update', '--limits-only', 'codex'])
            self.watch.usage_refresh_finished()
            self.watch.refresh_usage_if_due()
            thread.assert_called_once()  # retry cooldown

    def test_recent_usage_does_not_refetch_on_brief_reconnect(self):
        self.record(age=120)
        with mock.patch.object(daemon.threading, 'Thread') as thread:
            self.watch.refresh_usage_if_due()
            thread.assert_not_called()

    def test_new_record_file_triggers_prompt_sync_without_waking(self):
        self.record()
        self.watch.ensure_usage_monitor = mock.Mock()
        self.watch.schedule_context_check = mock.Mock()
        moved = mock.Mock()
        moved.get_path.return_value = str(self.watch.allowance_path)
        self.watch.on_usage_changed(None, moved, None, None)
        self.watch.schedule_context_check.assert_called_once_with()
        self.assertEqual(self.watch.preview_until, 0)

    def test_weather_keeps_daily_forecast_after_current_conditions_expire(self):
        self.watch.weather = self.weather(4*3600)
        with mock.patch.object(daemon, 'weather_location', return_value={'latitude': 1, 'longitude': 2}), \
             mock.patch.object(daemon, 'weather_unit_override', return_value=False):
            value = self.watch.effective_weather(self.now)
            self.assertTrue(value['valid'])
            self.assertEqual(value['updatedAt'], self.now-4*3600)
            self.watch.weather['dailyExpiresAt'] = self.now
            self.assertFalse(self.watch.effective_weather(self.now)['valid'])

    def test_location_change_hides_previous_location_even_if_fetch_fails(self):
        self.watch.weather = self.weather(60)
        with mock.patch.object(daemon, 'weather_location', return_value={'latitude': 3, 'longitude': 4}), \
             mock.patch.object(daemon, 'weather_unit_override', return_value=False):
            self.watch.weather_context_ready(None, 'offline')
            self.assertFalse(self.watch.effective_weather(self.now)['valid'])
            self.watch.refresh_effective_context = mock.Mock()
            self.watch.weather_context_ready(self.weather(0), '')
            self.watch.refresh_effective_context.assert_called_once()
            self.watch.context_changed.assert_not_called()

    def test_weather_failure_keeps_last_observation(self):
        original = self.weather(3600)
        self.watch.weather = dict(original)
        self.watch.weather_context_ready(None, 'offline')
        self.assertEqual(self.watch.weather, original)
        self.watch.refresh_desired_profile.assert_called_once()

    def test_v5_packet_preserves_both_weather_times(self):
        self.record(age=3600)
        self.watch.weather = self.weather(7200)
        with mock.patch.object(daemon, 'weather_location', return_value={'latitude': 1, 'longitude': 2}), \
             mock.patch.object(daemon, 'weather_unit_override', return_value=False):
            packet = self.watch.profile_payload()
        self.assertEqual(len(packet), 111)
        self.assertEqual(packet[:4], b'OW\x05\x01')
        self.assertEqual(struct.unpack('<q', packet[42:50])[0], self.now-7200)
        self.assertEqual(struct.unpack('<q', packet[103:111])[0], self.now+7200)
        self.assertFalse(packet[19] & (1 << 3))  # no preview wake

    def test_forecast_day_uses_location_midnight_across_dst(self):
        # Los Angeles has a 23-hour forecast day when DST starts.
        from zoneinfo import ZoneInfo
        zone = ZoneInfo('America/Los_Angeles')
        start = int(dt.datetime(2026, 3, 8, tzinfo=zone).timestamp())
        now = start + 3600
        report = {'timezone': 'America/Los_Angeles',
                  'current': {'time': now-300, 'temperature_2m': 18, 'weather_code': 2},
                  'daily': {'time': [start], 'temperature_2m_max': [22], 'temperature_2m_min': [14]}}
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(report).encode()
        with mock.patch.object(daemon, 'weather_location', return_value={'latitude': 1, 'longitude': 2, 'name': 'TEST'}), \
             mock.patch.object(daemon, 'weather_unit_override', return_value=False), \
             mock.patch.object(daemon.time, 'time', return_value=now):
            value = daemon.fetch_weather(mock.Mock(return_value=response))
        self.assertEqual(value['dailyExpiresAt'], start+23*3600)
        self.assertEqual(value['updatedAt'], now-300)
        self.assertEqual(value['fetchedAt'], now)

    def test_fresh_weather_does_not_refetch_on_recovery(self):
        self.watch.weather = self.weather(60)
        with mock.patch.object(daemon, 'weather_location', return_value={'latitude': 1, 'longitude': 2}), \
             mock.patch.object(daemon, 'weather_unit_override', return_value=False):
            self.assertFalse(self.watch.weather_refresh_due())
            self.watch.weather['fetchedAt'] = self.now-901
            self.assertTrue(self.watch.weather_refresh_due())

    def test_source_failure_does_not_erase_cache_when_cache_disk_is_unwritable(self):
        self.record(age=3600)
        with mock.patch.object(Path, 'mkdir', side_effect=PermissionError('read-only')):
            value = self.watch.cached_allowance(self.now)
        self.assertEqual(value['remaining'], 54)
        self.record(error='network unavailable')
        self.assertEqual(self.watch.cached_allowance(self.now), value)

    def test_weather_deadline_is_rechecked_after_a_slow_fetch(self):
        w = self.watch
        w.weather = self.weather(899)
        w.ensure_usage_monitor = mock.Mock()
        w.theme_path = w.theme_shell_path = w.theme_name_path = self.root / 'theme'
        w.weather_location_path = self.root / 'location'
        w.context_signature = w.file_signature(
            w.theme_path, w.theme_shell_path, w.theme_name_path,
            w.weather_location_path, w.shell_config_path)
        with mock.patch.object(daemon, 'weather_location', return_value={'latitude': 1, 'longitude': 2}), \
             mock.patch.object(daemon, 'weather_unit_override', return_value=False), \
             mock.patch.object(daemon, 'theme_palette', return_value=w.palette), \
             mock.patch.object(daemon.time, 'time', return_value=self.now) as clock, \
             mock.patch.object(daemon.threading, 'Thread') as thread:
            w.check_context_files()
            thread.assert_not_called()
            clock.return_value = self.now + 60
            w.check_context_files()
            thread.assert_called_once()
            self.assertTrue(w.context_refresh_inflight)

    def test_recovery_respects_disabled_usage_provider(self):
        self.record(age=3600)
        self.watch.shell_config_path.write_text(json.dumps({'bar': {'layout': {'right': [
            {'id': 'omarchy.agents', 'providers': {'codex': {'enabled': False}}}]}}}))
        with mock.patch.object(daemon.threading, 'Thread') as thread:
            self.watch.refresh_usage_if_due()
            thread.assert_not_called()

    def test_missing_agents_panel_does_not_start_a_usage_collector(self):
        self.record(age=3600)
        self.watch.shell_config_path.write_text('{}')
        with mock.patch.object(daemon.threading, 'Thread') as thread:
            self.watch.refresh_usage_if_due()
            thread.assert_not_called()
