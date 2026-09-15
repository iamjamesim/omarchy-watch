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
    def test_active_pairing_survives_temporary_bluez_device_removal(self):
        adapter_path = dbus.ObjectPath("/org/bluez/hci0")
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.current_device_properties = {"Paired": False}
        watch.pending_passkey = 123456
        watch.state = {
            "status": "pairing",
            "name": "Omarchy Watch",
            "address": "28:84:85:B4:F2:6A",
            "paired": False,
            "message": "Retrying secure connection (2/3)",
        }
        watch.managed_objects = mock.Mock(return_value={
            adapter_path: {daemon.ADAPTER: {"Powered": True}},
        })
        watch.write_state = mock.Mock()

        self.assertTrue(watch.refresh_devices())

        self.assertEqual(watch.device_path, "")
        watch.write_state.assert_called_once_with(
            status="pairing", connected=False, watchOwned=False
        )

    def test_unpaired_error_survives_temporary_bluez_device_removal(self):
        adapter_path = dbus.ObjectPath("/org/bluez/hci0")
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.current_device_properties = {"Paired": False}
        watch.pending_passkey = None
        watch.state = {
            "status": "error",
            "name": "Omarchy Watch",
            "address": "28:84:85:B4:F2:6A",
            "paired": False,
            "message": "Couldn't reach the watch. Keep it nearby and try again.",
        }
        watch.managed_objects = mock.Mock(return_value={
            adapter_path: {daemon.ADAPTER: {"Powered": True}},
        })
        watch.write_state = mock.Mock()

        self.assertTrue(watch.refresh_devices())

        self.assertEqual(watch.device_path, "")
        watch.write_state.assert_called_once_with(
            connected=False, watchOwned=False
        )

    def test_unpaired_watch_remains_live_while_discovery_continues(self):
        adapter_path = dbus.ObjectPath("/org/bluez/hci0")
        device_path = dbus.ObjectPath("/org/bluez/hci0/dev_watch")
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = ""
        watch.device_path = ""
        watch.current_device_properties = {}
        watch.pending_passkey = None
        watch.state = {"status": "discovering", "address": "", "lastSynced": 0}
        watch.managed_objects = mock.Mock(return_value={
            adapter_path: {daemon.ADAPTER: {"Powered": True}},
            device_path: {daemon.DEVICE: {
                "Name": "Omarchy Watch",
                "Address": "28:84:85:B4:F2:6A",
                "Paired": False,
                "Connected": False,
                "RSSI": -42,
            }},
        })
        watch.stop_discovery = mock.Mock()
        watch.write_state = mock.Mock()

        self.assertTrue(watch.refresh_devices())

        watch.stop_discovery.assert_not_called()
        watch.write_state.assert_called_once_with(
            status="found", name="Omarchy Watch",
            address="28:84:85:B4:F2:6A", paired=False, connected=False,
            watchOwned=False,
            message="Ready to pair",
        )

    def test_losing_unpaired_candidate_restarts_discovery(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.refresh_devices = mock.Mock(return_value=True)
        watch.refresh_devices.side_effect = lambda: setattr(watch, "device_path", "") or True
        watch.update_property_receivers = mock.Mock()
        watch.schedule_discovery_restart = mock.Mock()

        watch.on_interfaces_removed(
            "/org/bluez/hci0/dev_watch", [daemon.DEVICE]
        )

        watch.schedule_discovery_restart.assert_called_once_with()

    def test_discovery_restarts_when_bluez_stops_scanning(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.connect_inflight = False
        watch.discovery_active = True
        watch.schedule_discovery_restart = mock.Mock()

        watch.on_properties_changed(
            daemon.ADAPTER, {"Discovering": dbus.Boolean(False)}, []
        )

        self.assertFalse(watch.discovery_active)
        watch.schedule_discovery_restart.assert_called_once_with()

    def test_rescan_forces_a_new_discovery_session(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.schedule_discovery_restart = mock.Mock()

        watch.handle_command({"command": "rescan"})

        watch.schedule_discovery_restart.assert_called_once_with()

    def test_discovery_avoids_bluez_587_uuid_filter_crash(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.device_path = ""
        watch.current_device_properties = {}
        watch.discovery_active = False
        watch.refresh_devices = mock.Mock(return_value=True)
        watch.ensure_gatt_profile_registered = mock.Mock()
        watch.update_property_receivers = mock.Mock()
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.adapter)
        adapter = mock.Mock()

        with mock.patch.object(daemon.dbus, "Interface", return_value=adapter):
            watch.start_discovery()

        discovery_filter = adapter.SetDiscoveryFilter.call_args.args[0]
        self.assertEqual(str(discovery_filter["Transport"]), "le")
        self.assertNotIn("UUIDs", discovery_filter)
        adapter.StartDiscovery.assert_called_once_with()
        self.assertTrue(watch.discovery_active)

    def test_discovery_continues_for_cached_unpaired_watch(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.current_device_properties = {"Paired": False}
        watch.discovery_active = False
        watch.refresh_devices = mock.Mock(return_value=True)
        watch.ensure_gatt_profile_registered = mock.Mock()
        watch.update_property_receivers = mock.Mock()
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.adapter)
        adapter = mock.Mock()

        with mock.patch.object(daemon.dbus, "Interface", return_value=adapter):
            watch.start_discovery()

        watch.ensure_gatt_profile_registered.assert_called_once_with()
        watch.update_property_receivers.assert_called_once_with()
        adapter.StartDiscovery.assert_called_once_with()
        self.assertTrue(watch.discovery_active)

    def test_in_progress_manual_connection_is_left_to_bluez(self):
        class InProgress(dbus.DBusException):
            _dbus_error_name = "org.bluez.Error.InProgress"

        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.connect_inflight = True
        watch.state = {"paired": True}
        watch.write_state = mock.Mock()

        watch.on_connect_error(InProgress("Operation already in progress"))

        self.assertFalse(watch.connect_inflight)
        watch.write_state.assert_called_once_with(
            status="syncing", message="Connecting to watch"
        )

    def test_connect_timeout_is_left_to_bluez(self):
        class NoReply(dbus.DBusException):
            _dbus_error_name = "org.freedesktop.DBus.Error.NoReply"

        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.connect_inflight = True
        watch.state = {"paired": True, "connected": False}
        watch.write_state = mock.Mock()
        watch.schedule_reconnect = mock.Mock()
        watch.schedule_transport_recovery = mock.Mock()

        watch.on_connect_error(NoReply("Did not receive a reply"))

        self.assertFalse(watch.connect_inflight)
        watch.write_state.assert_called_once_with(
            status="syncing", message="Connecting to watch"
        )
        watch.schedule_reconnect.assert_called_once_with()
        watch.schedule_transport_recovery.assert_not_called()

    def test_failed_already_in_progress_is_left_to_bluez(self):
        class Failed(dbus.DBusException):
            _dbus_error_name = "org.bluez.Error.Failed"

        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.connect_inflight = True
        watch.state = {"paired": True, "connected": False}
        watch.write_state = mock.Mock()
        watch.schedule_reconnect = mock.Mock()
        watch.schedule_transport_recovery = mock.Mock()

        watch.on_connect_error(Failed("Operation already in progress"))

        watch.write_state.assert_called_once_with(
            status="syncing", message="Connecting to watch"
        )
        watch.schedule_reconnect.assert_called_once_with()
        watch.schedule_transport_recovery.assert_not_called()

    def test_gatt_profile_requests_native_autoconnect_for_watch_service(self):
        self.assertEqual(
            daemon.WatchGattProfile.properties(),
            {"UUIDs": [daemon.SERVICE_UUID]},
        )

    def test_gatt_profile_registration_uses_adapter_gatt_manager(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.gatt_registration_inflight = False
        watch.gatt_registered_adapter = ""
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.adapter)
        manager = mock.Mock()

        with mock.patch.object(daemon.dbus, "Interface", return_value=manager):
            watch.ensure_gatt_profile_registered()

        manager.RegisterApplication.assert_called_once()
        args, kwargs = manager.RegisterApplication.call_args
        self.assertEqual(args[0], daemon.GATT_APPLICATION_PATH)
        self.assertEqual(dict(args[1]), {})
        self.assertTrue(watch.gatt_registration_inflight)
        kwargs["reply_handler"]()
        self.assertEqual(watch.gatt_registered_adapter, watch.adapter_path)

    def test_synced_but_disconnected_watch_is_not_reported_ready(self):
        adapter_path = dbus.ObjectPath("/org/bluez/hci0")
        device_path = dbus.ObjectPath("/org/bluez/hci0/dev_watch")
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = ""
        watch.device_path = ""
        watch.current_device_properties = {}
        watch.pending_passkey = None
        watch.identity_verified = True
        watch.state = {
            "status": "ready", "address": "28:84:85:B4:F2:6A",
            "lastSynced": 123, "connected": True,
        }
        watch.managed_objects = mock.Mock(return_value={
            adapter_path: {daemon.ADAPTER: {"Powered": True}},
            device_path: {daemon.DEVICE: {
                "Name": "Omarchy Watch",
                "Address": "28:84:85:B4:F2:6A",
                "Paired": True,
                "Connected": False,
                "ServicesResolved": False,
            }},
        })
        watch.stop_discovery = mock.Mock()
        watch.write_state = mock.Mock()
        watch.schedule_reconnect = mock.Mock()

        with mock.patch.object(daemon.GLib, "idle_add") as idle_add:
            self.assertTrue(watch.refresh_devices())

        watch.write_state.assert_called_once_with(
            status="disconnected", name="Omarchy Watch",
            address="28:84:85:B4:F2:6A", paired=True, connected=False,
            watchOwned=False,
            message="Waiting for watch to reconnect",
        )
        idle_add.assert_not_called()
        watch.schedule_reconnect.assert_called_once_with()

    def test_connected_watch_is_not_ready_until_services_resolve(self):
        adapter_path = dbus.ObjectPath("/org/bluez/hci0")
        device_path = dbus.ObjectPath("/org/bluez/hci0/dev_watch")
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = ""
        watch.device_path = ""
        watch.current_device_properties = {}
        watch.pending_passkey = None
        watch.identity_verified = False
        watch.state = {
            "status": "disconnected", "address": "28:84:85:B4:F2:6A",
            "lastSynced": 123, "connected": False,
        }
        watch.managed_objects = mock.Mock(return_value={
            adapter_path: {daemon.ADAPTER: {"Powered": True}},
            device_path: {daemon.DEVICE: {
                "Name": "Omarchy Watch",
                "Address": "28:84:85:B4:F2:6A",
                "Paired": True,
                "Connected": True,
                "ServicesResolved": False,
            }},
        })
        watch.stop_discovery = mock.Mock()
        watch.cancel_reconnect = mock.Mock()
        watch.write_state = mock.Mock()

        self.assertTrue(watch.refresh_devices())

        watch.write_state.assert_called_once_with(
            status="paired", name="Omarchy Watch",
            address="28:84:85:B4:F2:6A", paired=True, connected=True,
            watchOwned=False,
            message="Finishing secure connection",
        )
        watch.cancel_reconnect.assert_called_once_with()

    def test_new_connection_verifies_identity_even_when_profile_is_current(self):
        adapter_path = dbus.ObjectPath("/org/bluez/hci0")
        device_path = dbus.ObjectPath("/org/bluez/hci0/dev_watch")
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = ""
        watch.device_path = ""
        watch.current_device_properties = {}
        watch.pending_passkey = None
        watch.identity_verified = False
        watch.activity_dirty = False
        watch.desired_fingerprint = "current"
        watch.synced_fingerprint = "current"
        watch.state = {
            "status": "disconnected", "address": "28:84:85:B4:F2:6A",
            "lastSynced": 123, "connected": False, "watchOwned": True,
        }
        watch.managed_objects = mock.Mock(return_value={
            adapter_path: {daemon.ADAPTER: {"Powered": True}},
            device_path: {daemon.DEVICE: {
                "Name": "Omarchy Watch",
                "Address": "28:84:85:B4:F2:6A",
                "Paired": True,
                "Connected": True,
                "ServicesResolved": True,
            }},
        })
        watch.stop_discovery = mock.Mock()
        watch.cancel_reconnect = mock.Mock()
        watch.write_state = mock.Mock()
        watch.sync_needed = mock.Mock(return_value=False)
        watch.sync_connected_profile = mock.Mock()

        self.assertTrue(watch.refresh_devices())

        watch.sync_connected_profile.assert_called_once_with()

    def test_disconnected_watch_reconnects_with_bounded_backoff(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.state = {"paired": True, "connected": False}
        watch.reconnect_source = 0
        watch.reconnect_delay_milliseconds = daemon.RECONNECT_INITIAL_MILLISECONDS
        watch.connect_inflight = False
        watch.recovery_inflight = False
        watch.write_inflight = False
        watch.pending_passkey = None

        with mock.patch.object(daemon.GLib, "timeout_add", return_value=42) as timeout_add:
            watch.schedule_reconnect()

        timeout_add.assert_called_once_with(
            daemon.RECONNECT_INITIAL_MILLISECONDS, watch.reconnect
        )
        self.assertEqual(watch.reconnect_source, 42)
        self.assertEqual(
            watch.reconnect_delay_milliseconds,
            daemon.RECONNECT_INITIAL_MILLISECONDS * 2,
        )

    def test_reconnect_timer_issues_explicit_connection(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.pending_passkey = None
        watch.connect_inflight = False
        watch.recovery_inflight = False
        watch.write_inflight = False
        watch.reconnect_source = 42
        watch.device_properties = mock.Mock(return_value={"Connected": False})
        watch.ensure_connection = mock.Mock()

        self.assertFalse(watch.reconnect())

        self.assertEqual(watch.reconnect_source, 0)
        watch.ensure_connection.assert_called_once_with("automatic reconnect")

    def test_transport_error_schedules_state_recovery(self):
        class NotConnected(dbus.DBusException):
            _dbus_error_name = "org.bluez.Error.NotConnected"

        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.state = {"paired": True}
        watch.identity_verified = True
        watch.transport_recovery_source = 0
        watch.write_state = mock.Mock()

        with mock.patch.object(daemon.GLib, "timeout_add", return_value=73) as timeout_add:
            self.assertTrue(watch.handle_transport_error(NotConnected("Not connected")))

        self.assertFalse(watch.identity_verified)
        watch.write_state.assert_called_once_with(
            status="disconnected", connected=False,
            message="Waiting for watch to reconnect",
        )
        timeout_add.assert_called_once_with(
            daemon.TRANSPORT_RECOVERY_MILLISECONDS, watch.recover_transport
        )

    def test_half_open_transport_is_disconnected_before_retry(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.transport_recovery_source = 73
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.pending_passkey = None
        watch.recovery_inflight = False
        watch.state = {"paired": True, "connected": True}
        watch.current_device_properties = {
            "Paired": True, "Connected": True, "ServicesResolved": False,
        }
        watch.refresh_devices = mock.Mock(return_value=True)
        watch.cancel_reconnect = mock.Mock()
        watch.write_state = mock.Mock()
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.device)
        device = mock.Mock()

        with mock.patch.object(daemon.dbus, "Interface", return_value=device):
            self.assertFalse(watch.recover_transport())

        self.assertEqual(watch.transport_recovery_source, 0)
        self.assertTrue(watch.recovery_inflight)
        watch.refresh_devices.assert_called_once_with(allow_sync=False)
        watch.write_state.assert_called_once_with(
            status="syncing", connected=True,
            message="Recovering watch connection",
        )
        device.Disconnect.assert_called_once_with(
            reply_handler=watch.on_recovery_disconnected,
            error_handler=watch.on_recovery_disconnect_error,
            timeout=10,
        )

    def test_unrelated_bluez_device_changes_are_ignored(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.refresh_devices = mock.Mock()

        watch.on_properties_changed(
            daemon.DEVICE, {"RSSI": dbus.Int16(-60)}, [],
            path="/org/bluez/hci0/dev_someone_else",
        )

        watch.refresh_devices.assert_not_called()

    def test_watch_advertisement_is_left_to_native_autoconnect(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.state = {"paired": True, "connected": False}
        watch.connect_inflight = False
        watch.refresh_devices = mock.Mock()

        with mock.patch.object(daemon.GLib, "idle_add") as idle_add:
            watch.on_properties_changed(
                daemon.DEVICE, {"RSSI": dbus.Int16(-60)}, [],
                path=watch.device_path,
            )

        watch.refresh_devices.assert_not_called()
        idle_add.assert_not_called()

    def test_link_loss_is_left_to_native_autoconnect(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.state = {"connected": True}
        watch.identity_verified = True
        watch.refresh_devices = mock.Mock()

        with mock.patch.object(daemon.GLib, "idle_add") as idle_add:
            watch.on_properties_changed(
                daemon.DEVICE, {"Connected": dbus.Boolean(False)}, [],
                path=watch.device_path,
            )

        self.assertFalse(watch.identity_verified)
        idle_add.assert_not_called()
        watch.refresh_devices.assert_called_once_with()

    def test_bluez_property_receivers_are_scoped_to_adapter_and_watch(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.adapter_path = "/org/bluez/hci0"
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.property_signal_paths = ()
        watch.property_signal_matches = []
        watch.bus = mock.Mock()
        watch.bus.add_signal_receiver.side_effect = [mock.Mock(), mock.Mock()]

        watch.update_property_receivers()

        paths = [call.kwargs["path"] for call in watch.bus.add_signal_receiver.call_args_list]
        self.assertEqual(paths, [watch.adapter_path, watch.device_path])

    def test_verified_connection_skips_redundant_identity_round_trip(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.connect_inflight = False
        watch.write_inflight = False
        watch.identity_verified = True
        watch.sync_needed = mock.Mock(return_value=True)
        watch.find_characteristic = mock.Mock(side_effect=["/identity", "/control"])
        watch.write_state = mock.Mock()
        watch.write_profile = mock.Mock()

        watch.sync_connected_profile()

        self.assertTrue(watch.write_inflight)
        watch.write_profile.assert_called_once_with()

    def test_current_profile_finishes_after_fresh_identity_verification(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.write_inflight = True
        watch.synced_fingerprint = "current"
        watch.desired_fingerprint = "current"
        watch.force_sync_requested = False
        watch.state = {"deviceId": "01010101-0101-0101-0101-010101010101"}
        watch.activity_dirty = False
        watch.write_state = mock.Mock()
        watch.write_profile = mock.Mock()
        watch.save_sync_state = mock.Mock()
        watch.sync_connected_activity = mock.Mock()
        identity = struct.pack(
            "<2sBBB3s16sIBBBB",
            b"OW", 1, daemon.PROTOCOL_VERSION, 1, b"\0" * 3,
            b"\1" * 16, 255, 0, 5, 2, 0,
        )

        watch.on_identity_read(identity)

        self.assertTrue(watch.identity_verified)
        self.assertFalse(watch.write_inflight)
        watch.write_profile.assert_not_called()
        watch.write_state.assert_has_calls([
            mock.call(
                deviceId="01010101-0101-0101-0101-010101010101",
                protocol=daemon.PROTOCOL_VERSION,
                firmware="0.5.2",
                capabilities=255,
                watchOwned=True,
            ),
            mock.call(
                status="ready", paired=True, connected=True,
                message="Up to date",
            ),
        ])
        watch.save_sync_state.assert_called_once_with()


class RevisionStateTests(unittest.TestCase):

    def test_initial_pair_uses_live_device_without_rediscovery(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.pending_passkey = None
        watch.pair_attempt = 0
        watch.pair_transport_attempt = 0
        watch.state = {"address": "28:84:85:B4:F2:6A"}
        watch.write_state = mock.Mock()
        watch.log = mock.Mock()
        watch.stop_discovery = mock.Mock()
        watch.start_discovery = mock.Mock()
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.device)
        device = mock.Mock()

        with (
            mock.patch.object(daemon.dbus, "Interface", return_value=device),
            mock.patch.object(daemon.GLib, "timeout_add", return_value=73) as timeout_add,
        ):
            watch.pair(123456)

        watch.stop_discovery.assert_called_once_with()
        watch.start_discovery.assert_not_called()
        timeout_add.assert_called_once_with(
            daemon.PAIRING_CLEANUP_MILLISECONDS, watch.begin_pair, 1
        )

    def test_pairing_transport_timeout_retries_without_reentering_code(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.pair_attempt = 1
        watch.pair_transport_attempt = 1
        watch.pair_timeout_id = 42
        watch.pending_passkey = 123456
        watch.pairing_device = "/org/bluez/hci0/dev_watch"
        watch.ignore_agent_cancel_until = 0
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.device)
        watch.write_state = mock.Mock()
        watch.log = mock.Mock()
        device = mock.Mock()

        with (
            mock.patch.object(daemon.dbus, "Interface", return_value=device),
            mock.patch.object(daemon.GLib, "timeout_add", return_value=73) as timeout_add,
        ):
            self.assertFalse(watch.on_pair_timeout(1))

        self.assertEqual(watch.pending_passkey, 123456)
        self.assertEqual(watch.pair_attempt, 2)
        self.assertEqual(watch.pair_transport_attempt, 2)
        watch.write_state.assert_called_once_with(
            status="pairing", message="Retrying secure connection (2/3)"
        )
        timeout_add.assert_called_once_with(
            daemon.PAIRING_RETRY_DELAY_MILLISECONDS, watch.prepare_pair, 2
        )

    def test_pairing_retry_refreshes_bluez_device(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.pair_attempt = 1
        watch.pair_transport_attempt = 2
        watch.pending_passkey = 123456
        watch.start_discovery = mock.Mock()

        with mock.patch.object(daemon.GLib, "timeout_add", return_value=73) as timeout_add:
            self.assertFalse(watch.prepare_pair(1))

        watch.start_discovery.assert_called_once_with(force=True)
        timeout_add.assert_called_once_with(
            daemon.PAIRING_RETRY_DISCOVERY_MILLISECONDS, watch.begin_pair, 1
        )

    def test_pairing_preflight_retries_when_bluez_device_disappears(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.pair_attempt = 1
        watch.pair_transport_attempt = 1
        watch.pending_passkey = 123456
        watch.device_path = "/org/bluez/hci0/dev_watch"
        watch.stop_discovery = mock.Mock()
        watch.refresh_devices = mock.Mock(
            side_effect=lambda **kwargs: setattr(watch, "device_path", "") or True
        )
        watch.retry_pairing_transport = mock.Mock(return_value=False)

        self.assertFalse(watch.begin_pair(1))

        watch.stop_discovery.assert_called_once_with()
        watch.refresh_devices.assert_called_once_with(allow_sync=False)
        watch.retry_pairing_transport.assert_called_once_with(
            1, "Pairing transport attempt 1 could not rediscover the watch"
        )

    def test_pairing_transport_timeout_fails_after_bounded_retries(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.pair_attempt = 3
        watch.pair_transport_attempt = daemon.PAIRING_MAX_TRANSPORT_ATTEMPTS
        watch.pair_timeout_id = 42
        watch.pending_passkey = 123456
        watch.pairing_device = "/org/bluez/hci0/dev_watch"
        watch.ignore_agent_cancel_until = 0
        watch.bluez_object = mock.Mock(return_value=mock.sentinel.device)
        watch.log = mock.Mock()
        watch.fail = mock.Mock()
        device = mock.Mock()

        with mock.patch.object(daemon.dbus, "Interface", return_value=device):
            self.assertFalse(watch.on_pair_timeout(3))

        watch.fail.assert_called_once_with(
            "Couldn't reach the watch. Keep it nearby and try again."
        )

    def test_pending_is_derived_from_desired_and_synced_revisions(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.desired_fingerprint = "same"
        watch.synced_fingerprint = "same"
        watch.force_sync_requested = False

        self.assertFalse(watch.sync_pending())
        self.assertFalse(watch.sync_needed())

        watch.desired_fingerprint = "new"

        self.assertTrue(watch.sync_pending())
        self.assertTrue(watch.sync_needed())

    def test_file_signature_hashes_content_not_only_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.toml"
            path.write_text("aaaa")
            first = daemon.WatchDaemon.file_signature(path)
            path.write_text("bbbb")

            self.assertNotEqual(first, daemon.WatchDaemon.file_signature(path))

    def test_network_recovery_refreshes_weather(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.refresh_effective_context = mock.Mock()

        watch.on_network_changed(None, False)
        watch.refresh_effective_context.assert_not_called()

        watch.on_network_changed(None, True)
        watch.refresh_effective_context.assert_called_once_with()

    def test_acknowledging_old_snapshot_keeps_newer_change_pending(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.write_inflight = True
        watch.preview_until = 0
        watch.preview_sent_until = 0
        watch.pairing_device = ""
        watch.pending_passkey = None
        watch.desired_fingerprint = "newer"
        watch.synced_fingerprint = "older"
        watch.inflight_fingerprint = "sent"
        watch.inflight_theme = "SOLITUDE"
        watch.inflight_was_forced = False
        watch.force_sync_requested = False
        watch.write_state = mock.Mock()
        watch.save_sync_state = mock.Mock()
        watch.sync_connected_profile = mock.Mock()

        watch.on_profile_written()

        self.assertEqual(watch.synced_fingerprint, "sent")
        watch.sync_connected_profile.assert_called_once_with()

    def test_completed_sync_keeps_low_power_connection_open(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.write_inflight = True
        watch.preview_until = 0
        watch.preview_sent_until = 0
        watch.pairing_device = ""
        watch.pending_passkey = None
        watch.desired_fingerprint = "sent"
        watch.synced_fingerprint = "older"
        watch.inflight_fingerprint = "sent"
        watch.inflight_theme = "SOLITUDE"
        watch.inflight_was_forced = False
        watch.force_sync_requested = False
        watch.write_state = mock.Mock()
        watch.save_sync_state = mock.Mock()
        watch.sync_connected_profile = mock.Mock()

        watch.on_profile_written()

        watch.write_state.assert_called_once_with(
            status="ready", paired=True, connected=True,
            lastSynced=mock.ANY,
            watchOwned=True,
            message="Watch sync complete",
            theme="SOLITUDE",
            syncedWeather={},
        )
        watch.sync_connected_profile.assert_not_called()


class AgentActivityTests(unittest.TestCase):
    def make_ledger(self, directory: str, epoch: int = 1_800_000_000):
        return daemon.AgentActivityLedger(
            Path(directory) / "agent-activity.json", epoch=epoch
        )

    def test_three_state_lifecycle_and_implicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)

            self.assertTrue(ledger.working("provider", "session-1", "turn-1"))
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_WORKING)
            self.assertTrue(ledger.completed(
                "provider", "session-1", "turn-1", completed_at=int(time.time())
            ))
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_FINISHED)
            self.assertTrue(ledger.working("provider", "session-1", "turn-2"))
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_WORKING)

    def test_each_distinct_completion_alerts_once(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)
            now = int(time.time())
            ledger.completed("provider", "one", "turn-1", completed_at=now)
            state, revision, alert = ledger.aggregate(now)
            self.assertEqual(state, daemon.ACTIVITY_FINISHED)
            self.assertTrue(alert)

            ledger.mark_delivered_through(revision)
            ledger.completed("provider", "two", "turn-2", completed_at=now)
            state, revision, alert = ledger.aggregate(now)
            self.assertEqual(state, daemon.ACTIVITY_FINISHED)
            self.assertTrue(alert)

            ledger.mark_delivered_through(revision)
            self.assertFalse(ledger.aggregate(now)[2])

    def test_duplicate_completion_does_not_alert_again(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)
            now = int(time.time())
            self.assertTrue(ledger.completed(
                "provider", "one", "turn-1", completed_at=now
            ))
            _, revision, alert = ledger.aggregate(now)
            self.assertTrue(alert)
            ledger.mark_delivered_through(revision)

            self.assertFalse(ledger.completed(
                "provider", "one", "turn-1", completed_at=now
            ))
            self.assertFalse(ledger.aggregate(now)[2])

    def test_watch_acknowledgement_only_clears_seen_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)
            now = int(time.time())
            ledger.completed("provider", "one", "turn-1", completed_at=now)
            acknowledged_revision = ledger.revision
            ledger.completed("provider", "two", "turn-2", completed_at=now)

            self.assertTrue(ledger.acknowledge_through(acknowledged_revision))
            self.assertNotIn("provider:one", ledger.sessions)
            self.assertIn("provider:two", ledger.sessions)

    def test_old_completion_cannot_replace_a_newer_running_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)
            ledger.working("provider", "session-1", "turn-2")

            self.assertFalse(ledger.completed(
                "provider", "session-1", "turn-1", completed_at=int(time.time())
            ))
            self.assertEqual(ledger.sessions["provider:session-1"]["turn"], "turn-2")
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_WORKING)

    def test_old_turn_cannot_replace_current_input_request(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)
            ledger.working("provider", "session-1", "turn-2")
            ledger.completed("provider", "session-1", "turn-2", needs_input=True)
            revision = ledger.revision
            for needs_input in (False, True):
                with self.subTest(needs_input=needs_input):
                    self.assertFalse(ledger.completed(
                        "provider", "session-1", "turn-1", needs_input=needs_input
                    ))
                    self.assertEqual(ledger.revision, revision)
                    self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_ATTENTION)
                    self.assertEqual(ledger.sessions["provider:session-1"]["turn"], "turn-2")

    def test_retained_watch_ack_keeps_future_revisions_monotonic(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory, epoch=100)

            self.assertTrue(ledger.acknowledge_through(500))
            ledger.working("provider", "session-1", "turn-1")

            self.assertGreater(ledger.revision, 500)

    def test_old_completion_restores_without_delayed_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time())
            ledger = self.make_ledger(directory)
            ledger.completed(
                "provider", "session-1", "turn-1",
                completed_at=now - daemon.AGENT_ALERT_FRESH_SECONDS - 1,
            )

            state, _, alert = ledger.aggregate(now)
            self.assertEqual(state, daemon.ACTIVITY_FINISHED)
            self.assertFalse(alert)

    def test_only_pending_completions_survive_daemon_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time())
            ledger = self.make_ledger(directory, epoch=now)
            ledger.working("provider", "working", "turn-1")
            ledger.completed("provider", "done", "turn-2", completed_at=now)

            restored = self.make_ledger(directory, epoch=now)

            self.assertNotIn("provider:working", restored.sessions)
            self.assertIn("provider:done", restored.sessions)

    def test_activity_packet_is_fixed_width(self):
        payload = struct.pack(
            "<2sBBBBII", b"OA", 1, daemon.ACTIVITY_ATTENTION, 1, 0, 42, 21
        )

        self.assertEqual(len(payload), 14)
        self.assertEqual(
            daemon.WatchDaemon.parse_activity_packet(payload), (42, 21, 1)
        )

    def test_input_request_takes_priority_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time())
            ledger = self.make_ledger(directory, epoch=now)
            ledger.working("provider", "busy", "turn-1")
            ledger.completed("provider", "done", "turn-1")
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_FINISHED)
            ledger.completed("provider", "question", "turn-1", needs_input=True)
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_ATTENTION)
            restored = self.make_ledger(directory, epoch=now)
            self.assertEqual(restored.aggregate()[0], daemon.ACTIVITY_ATTENTION)
            restored.remove("provider", "question")
            self.assertEqual(restored.aggregate()[0], daemon.ACTIVITY_FINISHED)

    def test_completion_after_input_request_is_a_new_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self.make_ledger(directory)
            ledger.completed("provider", "one", "turn-1", needs_input=True)
            ledger.mark_delivered_through(ledger.revision)
            self.assertTrue(ledger.completed("provider", "one", "turn-1"))
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_FINISHED)
            self.assertTrue(ledger.aggregate()[2])
            ledger.acknowledge_through(ledger.revision)
            self.assertEqual(ledger.aggregate()[0], daemon.ACTIVITY_NONE)

    def test_finished_state_requires_firmware_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.agent_activity = self.make_ledger(directory)
            watch.agent_activity.completed("provider", "one", "turn-1")
            watch.completion_sound = False
            for capabilities, expected in (
                (0, daemon.ACTIVITY_ATTENTION),
                (daemon.CAP_ACTIVITY_FINISHED, daemon.ACTIVITY_FINISHED),
            ):
                watch.state = {"capabilities": capabilities}
                payload = watch.activity_payload()
                self.assertEqual(struct.unpack("<2sBBBBII", payload)[2], expected)
                self.assertIsNotNone(watch.parse_activity_packet(payload))

    def test_explicit_input_event_cancels_pending_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.agent_activity = self.make_ledger(directory)
            watch.cancel_pending_completion = mock.Mock()
            watch.agent_activity_changed = mock.Mock()
            watch.handle_agent_event({
                "source": "provider", "session": "one", "turn": "turn-1",
                "event": "needs-input",
            })
            watch.cancel_pending_completion.assert_called_once_with("provider", "one")
            self.assertEqual(watch.agent_activity.aggregate()[0], daemon.ACTIVITY_ATTENTION)
            watch.agent_activity_changed.assert_called_once()

    def test_fresh_completion_requests_sound_when_supported_and_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.agent_activity = self.make_ledger(directory)
            watch.agent_activity.completed(
                "provider", "session-1", "turn-1", completed_at=int(time.time())
            )
            watch.completion_sound = True
            watch.state = {"capabilities": daemon.CAP_COMPLETION_SOUND}

            _, _, _, flags, _, _, _ = struct.unpack(
                "<2sBBBBII", watch.activity_payload()
            )

            self.assertEqual(
                flags, daemon.ACTIVITY_ALERT | daemon.ACTIVITY_SOUND
            )

    def test_sound_is_not_requested_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.agent_activity = self.make_ledger(directory)
            watch.agent_activity.completed(
                "provider", "session-1", "turn-1", completed_at=int(time.time())
            )
            watch.completion_sound = False
            watch.state = {"capabilities": daemon.CAP_COMPLETION_SOUND}

            _, _, _, flags, _, _, _ = struct.unpack(
                "<2sBBBBII", watch.activity_payload()
            )

            self.assertEqual(flags, daemon.ACTIVITY_ALERT)

    def test_old_firmware_never_receives_unknown_sound_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.agent_activity = self.make_ledger(directory)
            watch.agent_activity.completed(
                "provider", "session-1", "turn-1", completed_at=int(time.time())
            )
            watch.completion_sound = True
            watch.state = {"capabilities": 0}

            _, _, _, flags, _, _, _ = struct.unpack(
                "<2sBBBBII", watch.activity_payload()
            )

            self.assertEqual(flags, daemon.ACTIVITY_ALERT)


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
            watch.completion_sound = True

            watch.save_settings()

            self.assertEqual(watch.load_brightness(), 65)

    def test_completion_sound_setting_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.config_dir = Path(directory)
            watch.settings_path = watch.config_dir / "settings.json"
            watch.brightness = daemon.DEFAULT_BRIGHTNESS
            watch.completion_sound = False

            watch.save_settings()

            self.assertFalse(watch.load_completion_sound())

    def test_completion_sound_defaults_on_for_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
            watch.settings_path = Path(directory) / "settings.json"
            watch.settings_path.write_text('{"schema":1,"brightness":50}\n')

            self.assertTrue(watch.load_completion_sound())

    def test_open_meteo_weather_reuses_omarchy_location_and_units(self):
        report = {
            "timezone": "America/Los_Angeles",
            "current": {"time": int(time.time()) - 300, "temperature_2m": 68.4, "weather_code": 2, "is_day": 1},
            "daily": {"time": [int(time.time())], "temperature_2m_max": [72.2], "temperature_2m_min": [60.6]},
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
        watch.force_sync_requested = False
        watch.current_theme_name = lambda: "TEST"
        watch.host_id = bytes(range(16))
        watch.brightness = daemon.DEFAULT_BRIGHTNESS
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
        self.assertEqual(watch.inflight_fingerprint, watch.desired_fingerprint)

    def test_profile_v2_marks_stale_weather_unavailable(self):
        watch = daemon.WatchDaemon.__new__(daemon.WatchDaemon)
        watch.watch_protocol = 2
        watch.last_profile_revision = 0
        watch.force_sync_requested = False
        watch.current_theme_name = lambda: "TEST"
        watch.host_id = bytes(16)
        watch.brightness = daemon.DEFAULT_BRIGHTNESS
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
        watch.force_sync_requested = False
        watch.current_theme_name = lambda: "TEST"
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
        watch.force_sync_requested = False
        watch.current_theme_name = lambda: "TEST"
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
