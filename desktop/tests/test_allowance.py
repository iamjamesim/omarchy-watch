import copy
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


class AllowanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "codex.json"
        self.now = 1800000000
        self.record = {
            "schemaVersion": 1, "id": "codex", "updatedAt": self.iso(self.now),
            "usageStatusText": "",
            "limits": [{"label": "Weekly (7-day)", "percent": .21,
                        "resetsAt": self.iso(self.now + 86400)}],
        }

    @staticmethod
    def iso(epoch):
        return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()

    def read(self, record=None, now=None):
        self.path.write_text(json.dumps(self.record if record is None else record))
        return daemon.read_codex_allowance(self.path, self.now if now is None else now)

    def test_remaining_not_used(self):
        self.assertEqual(self.read(), {"remaining": 79, "window": 1,
                                      "updatedAt": self.now, "resetsAt": self.now + 86400})

    def test_selects_most_depleted_window_with_its_reset(self):
        self.record["limits"].append({"label": "5h window", "percent": .9,
                                      "resetsAt": self.iso(self.now + 600)})
        value = self.read()
        self.assertEqual((value["remaining"], value["window"], value["resetsAt"]),
                         (10, 2, self.now + 600))

    def test_zero_and_full_are_valid(self):
        for used, left in ((0, 100), (1, 0)):
            self.record["limits"][0]["percent"] = used
            self.assertEqual(self.read()["remaining"], left)

    def test_invalid_percentages_are_unavailable(self):
        for value in (None, True, "0.21", -1, 21, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.record["limits"][0]["percent"] = value
                self.assertEqual(self.read()["remaining"], 255)

    def test_missing_invalid_and_oversized_files(self):
        for raw in (None, "{", " " * 262145):
            if raw is not None:
                self.path.write_text(raw)
            self.assertEqual(daemon.read_codex_allowance(self.path, self.now)["remaining"], 255)

    def test_incompatible_records_are_unavailable(self):
        for key, value in (("schemaVersion", 2), ("schemaVersion", True),
                           ("id", "claude"), ("limits", []), ("limits", [None]),
                           ("usageStatusText", "Sign-in expired"), ("retryAdvised", True)):
            with self.subTest(key=key, value=value):
                record = copy.deepcopy(self.record)
                record[key] = value
                self.assertEqual(self.read(record)["remaining"], 255)
        self.assertEqual(self.read([])["remaining"], 255)

    def test_stale_future_and_timezone_less_timestamp(self):
        self.assertEqual(self.read(now=self.now + 1800)["remaining"], 79)
        for now in (self.now + 1801, self.now - 1):
            self.assertEqual(self.read(now=now)["remaining"], 255)
        self.record["updatedAt"] = "2027-01-15T08:00:00"
        self.assertEqual(self.read()["remaining"], 255)

    def test_reset_does_not_imply_refill(self):
        self.record["limits"][0]["resetsAt"] = self.iso(self.now)
        self.assertEqual(self.read()["remaining"], 255)

    def test_unknown_window_does_not_silently_disappear(self):
        self.record["limits"].append({"label": "New model limit", "percent": .95,
                                      "resetsAt": self.iso(self.now + 500)})
        self.assertEqual(self.read()["remaining"], 255)

    def test_extra_fields_are_ignored(self):
        self.record["newField"] = "irrelevant"
        self.assertEqual(self.read()["remaining"], 79)

    def watch(self, protocol):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.watch_protocol = protocol
        watch.last_profile_revision = 0
        watch.force_sync_requested = False
        watch.current_theme_name = lambda: "TEST"
        watch.host_id = bytes(16)
        watch.palette = (daemon.DEFAULT_BACKGROUND, daemon.DEFAULT_FOREGROUND, daemon.DEFAULT_ACCENT)
        watch.brightness = daemon.DEFAULT_BRIGHTNESS
        watch.preview_until = 0
        watch.preview_sent_until = 0
        watch.weather = {}
        watch.desktop_hour_cycle = lambda: 24
        watch.log = mock.Mock()
        return watch

    def test_v4_payload_and_fingerprint_follow_source_not_sync_time(self):
        value = self.read()
        watch = self.watch(4)
        with mock.patch.object(daemon, "read_codex_allowance", return_value=value):
            payload = watch.profile_payload()
            fingerprint = watch.profile_fingerprint()
            self.assertEqual(len(payload), 103)
            self.assertEqual(payload[:4], b"OW\x04\x01")
            self.assertEqual(struct.unpack("<BBqq", payload[85:]),
                             (79, 1, self.now, self.now + 86400))
            self.assertEqual(watch.profile_fingerprint(), fingerprint)
        with mock.patch.object(daemon, "read_codex_allowance", return_value={**value, "remaining": 78}):
            self.assertNotEqual(watch.profile_fingerprint(), fingerprint)

    def test_old_protocols_do_not_read_or_receive_allowance(self):
        for protocol, size in ((1, 36), (2, 81), (3, 85)):
            with mock.patch.object(daemon, "read_codex_allowance") as reader:
                self.assertEqual(len(self.watch(protocol).profile_payload()), size)
                reader.assert_not_called()

    def test_unavailable_v4_is_canonical_and_logs_only_transition(self):
        watch = self.watch(4)
        value = {"remaining": 255, "window": 0, "updatedAt": 0, "resetsAt": 0, "reason": "missing"}
        with mock.patch.object(daemon, "read_codex_allowance", side_effect=lambda *a: dict(value)):
            payload = watch.profile_payload()
            watch.profile_payload()
        self.assertEqual(struct.unpack("<BBqq", payload[85:]), (255, 0, 0, 0))
        watch.log.assert_called_once()

    def test_encoded_packet_passes_firmware_validator(self):
        validator = Path(__file__).resolve().parents[2] / "simulator/build/test-profile"
        if not validator.is_file():
            self.skipTest("Build simulator to run the Python-to-C wire test")
        now = int(time.time())
        value = {"remaining": 79, "window": 1, "updatedAt": now, "resetsAt": now + 86400}
        with mock.patch.object(daemon, "read_codex_allowance", return_value=value):
            packet = self.watch(4).profile_payload()
        path = Path(self.temp.name) / "profile.bin"
        path.write_bytes(packet)
        result = subprocess.run([str(validator), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
