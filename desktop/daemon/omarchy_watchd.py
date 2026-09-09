#!/usr/bin/env python3
"""Bluetooth owner and profile bridge for Omarchy Watch."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import socket
import struct
import threading
import time
import tomllib
import unicodedata
import urllib.parse
import urllib.request
import uuid

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


BLUEZ = "org.bluez"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
GATT_CHARACTERISTIC = "org.bluez.GattCharacteristic1"
AGENT_MANAGER = "org.bluez.AgentManager1"
AGENT = "org.bluez.Agent1"

SERVICE_UUID = "7f510001-1b15-4f0d-b7a5-4cf3a2c98ee1"
CONTROL_UUID = "7f510002-1b15-4f0d-b7a5-4cf3a2c98ee1"
IDENTITY_UUID = "7f510003-1b15-4f0d-b7a5-4cf3a2c98ee1"
AGENT_PATH = "/io/github/omarchy/watch/agent"
PROTOCOL_VERSION = 2
PAIRING_TIMEOUT_SECONDS = 20
PAIRING_CLEANUP_MILLISECONDS = 750
WEATHER_REFRESH_SECONDS = 15 * 60
WEATHER_MAX_AGE_SECONDS = 6 * 60 * 60
DEFAULT_BACKGROUND = bytes((0x10, 0x13, 0x15))
DEFAULT_FOREGROUND = bytes((0xCA, 0xCC, 0xCC))


def parse_hex_color(value: object, fallback: bytes) -> bytes:
    text = str(value or "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return fallback
    return bytes.fromhex(text[1:])


def theme_palette(path: Path | None = None) -> tuple[bytes, bytes]:
    colors_path = path or Path.home() / ".local/state/omarchy/current/theme/colors.toml"
    try:
        document = tomllib.loads(colors_path.read_text())
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return DEFAULT_BACKGROUND, DEFAULT_FOREGROUND
    return (
        parse_hex_color(document.get("background"), DEFAULT_BACKGROUND),
        parse_hex_color(document.get("foreground"), DEFAULT_FOREGROUND),
    )


def ascii_label(value: object, maximum: int = 23) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    label = normalized.encode("ascii", "ignore").decode("ascii").upper().strip()
    label = re.sub(r"\s+", " ", label)
    return label[:maximum]


def locale_uses_imperial() -> bool:
    locale_name = os.environ.get("LC_MEASUREMENT") or os.environ.get("LC_ALL") or os.environ.get("LANG", "")
    if not locale_name or locale_name in {"C", "C.UTF-8", "POSIX"}:
        try:
            for line in Path("/etc/locale.conf").read_text().splitlines():
                if line.startswith("LANG="):
                    locale_name = line.partition("=")[2].strip('"\'')
                    break
        except OSError:
            pass
    return bool(re.match(r"^(en[_-](US|LR)|my)(?:$|[_.-])", locale_name, re.IGNORECASE))


def weather_unit_override(shell_config: Path | None = None) -> bool:
    path = shell_config or xdg_path("XDG_CONFIG_HOME", ".config") / "omarchy" / "shell.json"
    try:
        document = json.loads(path.read_text())
        layout = document["bar"]["layout"]
        for section in ("left", "center", "right"):
            for widget in layout.get(section, []):
                if widget.get("id") != "omarchy.weather":
                    continue
                unit = str(widget.get("unit", "")).strip().lower()
                if unit == "imperial":
                    return True
                if unit == "metric":
                    return False
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return locale_uses_imperial()


def weather_location(path: Path | None = None) -> dict:
    location_path = path or Path.home() / ".local/state/omarchy/settings/weather.json"
    try:
        document = json.loads(location_path.read_text())
        latitude = float(document["latitude"])
        longitude = float(document["longitude"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordinates out of range")
        return {
            "name": ascii_label(document.get("name") or "LOCAL WEATHER"),
            "latitude": latitude,
            "longitude": longitude,
        }
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def fetch_weather(opener=urllib.request.urlopen) -> dict:
    location = weather_location()
    imperial = weather_unit_override()
    if not location:
        raise ValueError("Set an Omarchy weather location before syncing weather")
    query = urllib.parse.urlencode({
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": "temperature_2m,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min",
        "forecast_days": 1,
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "timezone": "auto",
    })
    request = urllib.request.Request(
        f"https://api.open-meteo.com/v1/forecast?{query}",
        headers={"User-Agent": "omarchy-watch/0.2"},
    )
    with opener(request, timeout=6) as response:
        report = json.loads(response.read())
    current = report["current"]
    daily = report["daily"]
    return {
        "valid": True,
        "updatedAt": int(time.time()),
        "temperature": round(float(current["temperature_2m"])),
        "high": round(float(daily["temperature_2m_max"][0])),
        "low": round(float(daily["temperature_2m_min"][0])),
        "code": int(current["weather_code"]),
        "night": int(current.get("is_day", 1)) == 0,
        "fahrenheit": imperial,
        "location": location["name"],
    }


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.Rejected"


def xdg_path(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable, str(Path.home() / fallback)))


def plain(value):
    if isinstance(value, (bytes, bytearray, dbus.ByteArray)):
        return bytes(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, dbus.Array)):
        return [plain(item) for item in value]
    if isinstance(value, (dbus.Boolean, bool)):
        return bool(value)
    if isinstance(value, (dbus.Byte, dbus.Int16, dbus.Int32, dbus.Int64,
                          dbus.UInt16, dbus.UInt32, dbus.UInt64, int)):
        return int(value)
    return str(value)


class PairingAgent(dbus.service.Object):
    def __init__(self, daemon: "WatchDaemon"):
        self.daemon = daemon
        super().__init__(daemon.bus, AGENT_PATH)

    def _check(self, device) -> None:
        if str(device) != self.daemon.pairing_device or self.daemon.pending_passkey is None:
            raise Rejected("No Omarchy Watch pairing is pending")

    @dbus.service.method(AGENT, in_signature="", out_signature="")
    def Release(self):
        return None

    @dbus.service.method(AGENT, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        self._check(device)
        self.daemon.log("BlueZ requested the watch PIN")
        return f"{self.daemon.pending_passkey:06d}"

    @dbus.service.method(AGENT, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        self._check(device)
        self.daemon.log("BlueZ requested the watch passkey")
        return dbus.UInt32(self.daemon.pending_passkey)

    @dbus.service.method(AGENT, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        raise Rejected("The passkey must be displayed by the watch")

    @dbus.service.method(AGENT, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        raise Rejected("The passkey must be displayed by the watch")

    @dbus.service.method(AGENT, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        self._check(device)
        self.daemon.log("BlueZ requested passkey confirmation")
        if int(passkey) != self.daemon.pending_passkey:
            raise Rejected("Pairing code mismatch")

    @dbus.service.method(AGENT, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        self._check(device)

    @dbus.service.method(AGENT, in_signature="os", out_signature="")
    def AuthorizeService(self, device, service):
        self._check(device)

    @dbus.service.method(AGENT, in_signature="", out_signature="")
    def Cancel(self):
        if time.monotonic() < self.daemon.ignore_agent_cancel_until:
            self.daemon.log("Ignored cancellation from stale pairing cleanup")
        elif self.daemon.pending_passkey is not None:
            self.daemon.fail("Pairing was cancelled")


class WatchDaemon:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.root = self.bluez_object("/")
        self.objects = dbus.Interface(self.root, OBJECT_MANAGER)
        self.adapter_path = ""
        self.device_path = ""
        self.pairing_device = ""
        self.pending_passkey: int | None = None
        self.pair_attempt = 0
        self.pair_timeout_id = 0
        self.ignore_agent_cancel_until = 0.0
        self.sync_deadline = 0.0
        self.connect_inflight = False
        self.sync_timer_active = False
        self.write_inflight = False
        self.discovery_retry_pending = False
        self.context_dirty = False
        self.context_refresh_inflight = False
        self.watch_protocol = 1
        self.last_profile_revision = 0
        self.agent = PairingAgent(self)

        self.runtime_dir = xdg_path("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.state_dir = xdg_path("XDG_STATE_HOME", ".local/state") / "omarchy-watch"
        self.config_dir = xdg_path("XDG_CONFIG_HOME", ".config") / "omarchy-watch"
        self.socket_path = self.runtime_dir / "omarchy-watch.sock"
        self.status_path = self.state_dir / "status.json"
        self.identity_path = self.config_dir / "identity.json"
        self.cache_dir = xdg_path("XDG_CACHE_HOME", ".cache") / "omarchy-watch"
        self.weather_cache_path = self.cache_dir / "weather.json"
        self.theme_path = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
        self.weather_location_path = Path.home() / ".local/state/omarchy/settings/weather.json"
        self.theme_name_path = Path.home() / ".local/state/omarchy/current/theme.name"
        self.shell_config_path = xdg_path("XDG_CONFIG_HOME", ".config") / "omarchy" / "shell.json"
        self.context_signature = ()
        self.palette = theme_palette(self.theme_path)
        self.weather = self.load_cached_weather()
        self.host_id = self.load_host_id()
        self.state = {
            "schema": 1,
            "status": "starting",
            "name": "",
            "address": "",
            "paired": False,
            "connected": False,
            "lastSynced": 0,
            "message": "Starting Bluetooth bridge",
            "theme": self.current_theme_name(),
            "weatherLocation": self.weather.get("location", ""),
            "weatherUpdated": self.weather.get("updatedAt", 0),
        }
        self.write_state()

    @staticmethod
    def log(message: str) -> None:
        print(f"omarchy-watchd: {message}", flush=True)

    def bluez_object(self, path: str):
        return self.bus.get_object(BLUEZ, path, follow_name_owner_changes=True)

    def load_host_id(self) -> bytes:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            document = json.loads(self.identity_path.read_text())
            return uuid.UUID(document["hostId"]).bytes
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            host_id = uuid.uuid4()
            temporary = self.identity_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"schema": 1, "hostId": str(host_id)}, indent=2) + "\n")
            os.chmod(temporary, 0o600)
            temporary.replace(self.identity_path)
            return host_id.bytes

    def load_cached_weather(self) -> dict:
        try:
            document = json.loads(self.weather_cache_path.read_text())
            if not document.get("valid"):
                return {}
            return document
        except (FileNotFoundError, OSError, TypeError, json.JSONDecodeError):
            return {}

    def current_theme_name(self) -> str:
        try:
            return ascii_label(self.theme_name_path.read_text(), 32)
        except OSError:
            return ""

    def cache_weather(self, weather: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.weather_cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(weather, separators=(",", ":")) + "\n")
        temporary.replace(self.weather_cache_path)

    @staticmethod
    def file_signature(*paths: Path) -> tuple:
        signature = []
        for path in paths:
            try:
                stat = path.stat()
                signature.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                signature.append((0, 0))
        return tuple(signature)

    def refresh_effective_context(self) -> None:
        palette = theme_palette(self.theme_path)
        if palette != self.palette:
            self.palette = palette
            self.context_changed()
        if self.context_refresh_inflight:
            return
        self.context_refresh_inflight = True
        threading.Thread(
            target=self.fetch_weather_context,
            name="watch-weather",
            daemon=True,
        ).start()

    def fetch_weather_context(self) -> None:
        try:
            weather = fetch_weather()
            self.cache_weather(weather)
            GLib.idle_add(self.weather_context_ready, weather, "")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            GLib.idle_add(self.weather_context_ready, None, str(error))

    def weather_context_ready(self, weather: dict | None, error: str) -> bool:
        self.context_refresh_inflight = False
        if weather:
            changed = weather != self.weather
            self.weather = weather
            self.write_state(
                weatherLocation=weather.get("location", ""),
                weatherUpdated=weather.get("updatedAt", 0),
            )
            if changed:
                self.context_changed()
        elif error:
            self.log(f"Weather refresh kept cached data: {error}")
        return False

    def context_changed(self) -> None:
        self.context_dirty = True
        if self.state.get("paired") and self.pending_passkey is None:
            self.connect_and_sync()

    def check_context_files(self) -> bool:
        signature = self.file_signature(
            self.theme_path, self.weather_location_path, self.shell_config_path
        )
        if signature != self.context_signature:
            self.context_signature = signature
            self.context_changed()
            self.refresh_effective_context()
        return True

    def periodic_weather_refresh(self) -> bool:
        self.refresh_effective_context()
        return True

    def write_state(self, **changes) -> None:
        self.state.update(changes)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, separators=(",", ":")) + "\n")
        temporary.replace(self.status_path)

    def fail(self, message: str) -> None:
        if self.pending_passkey is not None:
            self.pair_attempt += 1
        self.cancel_pair_timeout()
        self.pending_passkey = None
        self.pairing_device = ""
        self.write_state(status="error", message=message)

    def cancel_pair_timeout(self) -> None:
        if self.pair_timeout_id:
            GLib.source_remove(self.pair_timeout_id)
            self.pair_timeout_id = 0

    def managed_objects(self):
        return self.objects.GetManagedObjects()

    def device_properties(self, path: str) -> dict:
        objects = self.managed_objects()
        return plain(objects.get(dbus.ObjectPath(path), {}).get(DEVICE, {}))

    @staticmethod
    def is_watch(properties: dict) -> bool:
        uuids = {item.lower() for item in properties.get("UUIDs", [])}
        name = properties.get("Name", "") or properties.get("Alias", "")
        return SERVICE_UUID in uuids or name.startswith("Omarchy Watch")

    def refresh_devices(self) -> bool:
        try:
            objects = self.managed_objects()
        except dbus.DBusException:
            self.write_state(
                status="unavailable", connected=False,
                message="Bluetooth service is restarting",
            )
            return False
        adapters = [str(path) for path, interfaces in objects.items() if ADAPTER in interfaces]
        if not adapters:
            self.write_state(status="unavailable", message="No Bluetooth adapter")
            return False
        self.adapter_path = adapters[0]

        candidates = []
        for path, interfaces in objects.items():
            if DEVICE not in interfaces:
                continue
            properties = plain(interfaces[DEVICE])
            if self.is_watch(properties):
                candidates.append((str(path), properties))

        adapter_properties = plain(objects[dbus.ObjectPath(self.adapter_path)][ADAPTER])
        if not adapter_properties.get("Powered", False):
            self.connect_inflight = False
            if candidates:
                candidates.sort(
                    key=lambda item: bool(item[1].get("Paired")), reverse=True
                )
                self.device_path, properties = candidates[0]
                self.write_state(
                    status="bluetooth-off",
                    name=properties.get("Name") or properties.get("Alias") or "Omarchy Watch",
                    address=properties.get("Address", ""),
                    paired=bool(properties.get("Paired")),
                    connected=False,
                    message="Bluetooth is off",
                )
            else:
                self.write_state(
                    status="bluetooth-off", connected=False,
                    message="Bluetooth is off",
                )
            return False

        if not candidates:
            self.device_path = ""
            self.write_state(
                status="discovering", name="", address="", paired=False,
                connected=False, message="Looking for an Omarchy Watch",
            )
            return True

        candidates.sort(
            key=lambda item: (bool(item[1].get("Paired")), int(item[1].get("RSSI", -999))),
            reverse=True,
        )
        self.device_path, properties = candidates[0]
        paired = bool(properties.get("Paired"))
        connected = bool(properties.get("Connected"))
        previous_status = self.state.get("status")
        same_device = self.state.get("address") == properties.get("Address", "")
        if (not paired and self.pending_passkey is not None and
                self.pairing_device == self.device_path):
            status = "pairing"
            message = self.state.get("message", "Pairing securely")
        elif not paired and same_device and previous_status == "error":
            status = "error"
            message = self.state.get("message", "Pairing failed")
        else:
            status = "ready" if paired and self.state.get("lastSynced", 0) else "paired" if paired else "found"
            message = "Ready to pair" if not paired else "Up to date" if status == "ready" else "Connected" if connected else "Paired"
        self.write_state(
            status=status,
            name=properties.get("Name") or properties.get("Alias") or "Omarchy Watch",
            address=properties.get("Address", ""),
            paired=paired,
            connected=connected,
            message=message,
        )
        if paired:
            if connected and (not self.state.get("lastSynced", 0) or self.context_dirty):
                self.schedule_profile_sync()
            elif (not connected and not self.connect_inflight and
                  (not self.state.get("lastSynced", 0) or self.context_dirty)):
                GLib.idle_add(self.connect_and_sync)
        return True

    def start_discovery(self) -> None:
        if not self.refresh_devices():
            return
        if self.device_path:
            return
        adapter = self.bluez_object(self.adapter_path)
        interface = dbus.Interface(adapter, ADAPTER)
        try:
            interface.SetDiscoveryFilter({
                "UUIDs": dbus.Array([SERVICE_UUID], signature="s"),
                "Transport": dbus.String("le"),
                "DuplicateData": dbus.Boolean(False),
            })
            interface.StartDiscovery()
        except dbus.DBusException as error:
            if error.get_dbus_name() == "org.bluez.Error.InProgress":
                if not self.discovery_retry_pending:
                    self.discovery_retry_pending = True
                    GLib.timeout_add(1500, self.retry_discovery)
            elif error.get_dbus_name() == "org.bluez.Error.NotReady":
                self.write_state(
                    status="bluetooth-off", connected=False,
                    message="Bluetooth is off",
                )
            else:
                self.fail(f"Bluetooth discovery failed: {error.get_dbus_message()}")

    def retry_discovery(self) -> bool:
        self.discovery_retry_pending = False
        self.start_discovery()
        return False

    def register_agent(self) -> None:
        manager_object = self.bluez_object("/org/bluez")
        manager = dbus.Interface(manager_object, AGENT_MANAGER)
        manager.RegisterAgent(AGENT_PATH, "KeyboardOnly")

    def on_interfaces_added(self, path, interfaces) -> None:
        if DEVICE in interfaces and self.is_watch(plain(interfaces[DEVICE])):
            self.refresh_devices()

    def on_properties_changed(self, interface, changed, invalidated, path=None) -> None:
        if interface == ADAPTER:
            self.connect_inflight = False
            adapter_changes = plain(changed)
            if "Powered" not in adapter_changes:
                return
            if bool(adapter_changes["Powered"]):
                GLib.idle_add(self.start_discovery)
            else:
                self.write_state(
                    status="bluetooth-off", connected=False,
                    message="Bluetooth is off",
                )
            return
        if interface != DEVICE or not path:
            return
        if str(path) == self.device_path or self.is_watch(self.device_properties(str(path))):
            self.refresh_devices()
            properties = self.device_properties(str(path))
            if properties.get("ServicesResolved") and properties.get("Paired"):
                self.schedule_profile_sync()

    def on_bluez_owner_changed(self, name, old_owner, new_owner) -> None:
        if not new_owner:
            self.write_state(
                status="unavailable", connected=False,
                message="Bluetooth service is restarting",
            )
            return
        self.connect_inflight = False
        self.sync_timer_active = False
        self.write_inflight = False
        self.discovery_retry_pending = False
        self.root = self.bluez_object("/")
        self.objects = dbus.Interface(self.root, OBJECT_MANAGER)
        try:
            self.register_agent()
        except dbus.DBusException as error:
            self.fail(f"Bluetooth recovery failed: {error.get_dbus_message()}")
            return
        GLib.timeout_add(500, self.restart_discovery)

    def restart_discovery(self) -> bool:
        self.start_discovery()
        return False

    def pair(self, code: int) -> None:
        if not self.device_path:
            self.fail("No Omarchy Watch is nearby")
            return
        if not 100000 <= code <= 999999:
            self.fail("Enter the six-digit code shown on the watch")
            return
        if self.pending_passkey is not None:
            self.fail("A pairing attempt is already in progress")
            return

        self.pair_attempt += 1
        attempt = self.pair_attempt
        self.pending_passkey = code
        self.pairing_device = self.device_path
        self.write_state(status="pairing", message="Pairing securely")
        self.log(f"Starting pairing attempt {attempt} with {self.state.get('address', 'watch')}")

        # Pairing needs the controller for a connection, while discovery keeps
        # it scanning. Stop our open-ended scan before authentication.
        if self.adapter_path:
            try:
                dbus.Interface(self.bluez_object(self.adapter_path), ADAPTER).StopDiscovery()
                self.log("Stopped discovery before pairing")
            except dbus.DBusException as error:
                if error.get_dbus_name() not in {
                    "org.bluez.Error.NotReady",
                    "org.bluez.Error.NotAuthorized",
                }:
                    self.log(f"Stopping discovery returned {error.get_dbus_name()}: {error.get_dbus_message()}")

        # A failed LE pairing can leave an authentication request behind in
        # BlueZ even after the watch disconnects. Clear it before retrying.
        self.ignore_agent_cancel_until = time.monotonic() + 1.0
        device_interface = dbus.Interface(self.bluez_object(self.device_path), DEVICE)
        try:
            device_interface.CancelPairing()
            self.log("Cancelled a stale BlueZ pairing transaction")
        except dbus.DBusException as error:
            if error.get_dbus_name() not in {
                "org.bluez.Error.DoesNotExist",
                "org.bluez.Error.NotReady",
            }:
                self.log(f"Pairing cleanup returned {error.get_dbus_name()}: {error.get_dbus_message()}")

        GLib.timeout_add(PAIRING_CLEANUP_MILLISECONDS, self.begin_pair, attempt)

    def begin_pair(self, attempt: int) -> bool:
        if attempt != self.pair_attempt or self.pending_passkey is None:
            return False

        device = self.bluez_object(self.pairing_device)
        self.pair_timeout_id = GLib.timeout_add_seconds(
            PAIRING_TIMEOUT_SECONDS, self.on_pair_timeout, attempt
        )
        dbus.Interface(device, DEVICE).Pair(
            reply_handler=lambda: self.on_paired(attempt),
            error_handler=lambda error: self.on_pair_error(attempt, error),
            timeout=PAIRING_TIMEOUT_SECONDS + 5,
        )
        return False

    def on_pair_timeout(self, attempt: int) -> bool:
        if attempt != self.pair_attempt or self.pending_passkey is None:
            return False

        pairing_device = self.pairing_device
        self.pair_attempt += 1
        self.pair_timeout_id = 0
        try:
            dbus.Interface(self.bluez_object(pairing_device), DEVICE).CancelPairing()
        except dbus.DBusException:
            pass
        self.log(f"Pairing attempt {attempt} reached the {PAIRING_TIMEOUT_SECONDS}-second deadline")
        self.fail("Code didn't match. Check the watch and try again.")
        return False

    def on_paired(self, attempt: int) -> None:
        if attempt != self.pair_attempt:
            return
        self.log(f"Pairing attempt {attempt} succeeded")
        self.cancel_pair_timeout()
        self.pending_passkey = None
        self.write_state(status="paired", paired=True, message="Securing ownership")
        properties = dbus.Interface(self.bluez_object(self.device_path), PROPERTIES)
        properties.Set(DEVICE, "Trusted", dbus.Boolean(True))
        self.connect_and_sync()

    def on_pair_error(self, attempt: int, error) -> None:
        if attempt != self.pair_attempt:
            return
        self.cancel_pair_timeout()
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        detail = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        self.log(f"Pairing attempt {attempt} failed with {name or 'unknown'}: {detail}")
        if name in {
            "org.bluez.Error.AuthenticationCanceled",
            "org.bluez.Error.AuthenticationFailed",
            "org.bluez.Error.AuthenticationRejected",
            "org.bluez.Error.AuthenticationTimeout",
            "org.bluez.Error.Canceled",
        }:
            self.fail("Code didn't match. Check the watch and try again.")
            return
        self.fail(f"Pairing failed: {detail}")

    def connect_and_sync(self) -> bool:
        if not self.device_path or self.connect_inflight:
            return False
        if self.write_inflight or self.sync_timer_active:
            self.context_dirty = True
            return False
        properties = self.device_properties(self.device_path)
        if properties.get("Connected"):
            self.schedule_profile_sync()
            return False
        self.connect_inflight = True
        self.write_state(status="syncing", message="Connecting to watch")
        device = self.bluez_object(self.device_path)
        dbus.Interface(device, DEVICE).Connect(
            reply_handler=self.on_connected,
            error_handler=self.on_connect_error,
            timeout=30,
        )
        return False

    def on_connected(self) -> None:
        self.connect_inflight = False
        self.schedule_profile_sync()

    def on_connect_error(self, error) -> None:
        self.connect_inflight = False
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        if name == "org.bluez.Error.AlreadyConnected":
            self.schedule_profile_sync()
            return
        if self.handle_transport_error(error):
            return
        message = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        self.fail(f"Connection failed: {message}")

    def handle_transport_error(self, error) -> bool:
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        message = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        if self.state.get("paired") and (name in {
            "org.bluez.Error.Failed",
            "org.bluez.Error.NotAvailable",
            "org.bluez.Error.NotReady",
            "org.bluez.Error.NotConnected",
            "org.freedesktop.DBus.Error.NoReply",
        } or "Did not receive a reply" in message):
            status = "bluetooth-off" if name == "org.bluez.Error.NotReady" else "disconnected"
            friendly = "Bluetooth is off" if status == "bluetooth-off" else "Watch is out of range"
            self.write_state(status=status, connected=False, message=friendly)
            return True
        return False

    def schedule_profile_sync(self) -> None:
        self.connect_inflight = False
        self.sync_deadline = time.monotonic() + 20
        self.write_state(status="syncing", connected=True, message="Sending desktop settings")
        if not self.sync_timer_active and not self.write_inflight:
            self.sync_timer_active = True
            GLib.timeout_add(250, self.try_profile_sync)

    def find_characteristic(self, wanted_uuid: str) -> str:
        for path, interfaces in self.managed_objects().items():
            characteristic = plain(interfaces.get(GATT_CHARACTERISTIC, {}))
            if (str(path).startswith(self.device_path + "/") and
                    characteristic.get("UUID", "").lower() == wanted_uuid):
                return str(path)
        return ""

    def try_profile_sync(self) -> bool:
        identity_path = self.find_characteristic(IDENTITY_UUID)
        control_path = self.find_characteristic(CONTROL_UUID)
        if not identity_path or not control_path:
            if time.monotonic() < self.sync_deadline:
                return True
            self.sync_timer_active = False
            self.fail("The watch connected but its setup service did not appear")
            return False

        self.sync_timer_active = False
        self.write_inflight = True
        characteristic = dbus.Interface(
            self.bluez_object(identity_path), GATT_CHARACTERISTIC
        )
        characteristic.ReadValue(
            dbus.Dictionary({}, signature="sv"),
            reply_handler=self.on_identity_read,
            error_handler=self.on_identity_error,
            timeout=30,
        )
        return False

    def on_identity_read(self, raw_identity) -> None:
        value = bytes(int(item) for item in raw_identity)
        if len(value) != 32:
            self.write_inflight = False
            self.fail("The watch returned an invalid identity")
            return
        magic, protocol_min, protocol_max, owned, _, device_id, capabilities, fw_major, fw_minor, fw_patch, _ = struct.unpack(
            "<2sBBB3s16sIBBBB", value
        )
        if (magic != b"OW" or protocol_min > PROTOCOL_VERSION or
                protocol_max < 1):
            self.write_inflight = False
            self.fail("This watch needs a compatible desktop version")
            return
        self.watch_protocol = min(PROTOCOL_VERSION, protocol_max)
        self.write_state(
            deviceId=str(uuid.UUID(bytes=device_id)),
            protocol=self.watch_protocol,
            firmware=f"{fw_major}.{fw_minor}.{fw_patch}",
            capabilities=capabilities,
            watchOwned=bool(owned & 1),
        )
        self.write_profile()

    def on_identity_error(self, error) -> None:
        self.write_inflight = False
        self.context_dirty = True
        if self.handle_transport_error(error):
            return
        message = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        self.fail(f"Identity check failed: {message}")

    def write_profile(self) -> None:
        control_path = self.find_characteristic(CONTROL_UUID)
        if not control_path:
            self.write_inflight = False
            self.fail("The watch setup service disappeared")
            return
        characteristic = dbus.Interface(
            self.bluez_object(control_path), GATT_CHARACTERISTIC
        )
        characteristic.WriteValue(
            dbus.Array(self.profile_payload(), signature="y"),
            {"type": dbus.String("request")},
            reply_handler=self.on_profile_written,
            error_handler=self.on_profile_error,
            timeout=30,
        )

    def profile_payload(self) -> bytes:
        now = dt.datetime.now().astimezone()
        offset = int((now.utcoffset() or dt.timedelta()).total_seconds() // 60)
        epoch = int(now.timestamp())
        revision = max(epoch & 0xFFFFFFFF, self.last_profile_revision + 1)
        self.last_profile_revision = revision
        cycle = self.desktop_hour_cycle()
        if self.watch_protocol < 2:
            self.context_dirty = False
            return struct.pack(
                "<2sBBIqhBB16s",
                b"OW", 1, 1, revision, epoch, offset, cycle, 0, self.host_id,
            )

        background, foreground = self.palette
        weather = self.weather
        weather_age = epoch - int(weather.get("updatedAt", 0) or 0)
        weather_valid = bool(weather.get("valid")) and 0 <= weather_age <= WEATHER_MAX_AGE_SECONDS
        flags = 0
        if weather_valid:
            flags |= 1
        if weather.get("fahrenheit"):
            flags |= 1 << 1
        if weather.get("night"):
            flags |= 1 << 2

        def bounded_temperature(name: str) -> int:
            return max(-99, min(199, int(weather.get(name, 0) or 0)))

        location = ascii_label(weather.get("location", "")) if weather_valid else ""
        location_bytes = location.encode("ascii")[:23].ljust(24, b"\0")
        self.context_dirty = False
        return struct.pack(
            "<2sBBIqhBB16s3s3sqhhhB24s",
            b"OW", 2, 1, revision, epoch, offset, cycle, flags, self.host_id,
            background, foreground,
            int(weather.get("updatedAt", 0) or 0) if weather_valid else 0,
            bounded_temperature("temperature"),
            bounded_temperature("high"),
            bounded_temperature("low"),
            max(0, min(99, int(weather.get("code", 0) or 0))),
            location_bytes,
        )

    @staticmethod
    def desktop_hour_cycle() -> int:
        shell_config = xdg_path("XDG_CONFIG_HOME", ".config") / "omarchy" / "shell.json"
        try:
            document = json.loads(shell_config.read_text())
            widgets = document["bar"]["layout"]
            for section in ("left", "center", "right"):
                for widget in widgets.get(section, []):
                    if widget.get("id") == "omarchy.clock":
                        clock_format = str(widget.get("format", ""))
                        if "AP" in clock_format or "ap" in clock_format or re.search(r"(^|[^H])h", clock_format):
                            return 12
                        if "H" in clock_format:
                            return 24
        except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError):
            pass
        return 24

    def on_profile_written(self) -> None:
        self.write_inflight = False
        now = int(time.time())
        self.pairing_device = ""
        self.pending_passkey = None
        self.write_state(
            status="ready", paired=True, connected=True, lastSynced=now,
            message="Time, weather, and theme are up to date",
            theme=self.current_theme_name(),
        )
        if self.context_dirty:
            self.schedule_profile_sync()
        else:
            self.disconnect_after_sync()

    def disconnect_after_sync(self) -> None:
        if not self.device_path:
            return
        dbus.Interface(self.bluez_object(self.device_path), DEVICE).Disconnect(
            reply_handler=self.on_disconnected_after_sync,
            error_handler=self.on_disconnect_after_sync_error,
            timeout=10,
        )

    def on_disconnected_after_sync(self) -> None:
        self.write_state(
            status="ready", connected=False,
            message="Up to date; watch radio is idling",
        )

    def on_disconnect_after_sync_error(self, error) -> None:
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        if name not in {"org.bluez.Error.NotConnected", "org.bluez.Error.NotReady"}:
            self.log(f"Post-sync disconnect returned: {error}")

    def on_profile_error(self, error) -> None:
        self.write_inflight = False
        self.context_dirty = True
        if self.handle_transport_error(error):
            return
        message = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        self.fail(f"Profile sync failed: {message}")

    def handle_command(self, command: dict) -> None:
        action = command.get("command")
        if action == "pair":
            self.pair(int(command.get("passkey", 0)))
        elif action == "sync":
            self.connect_and_sync()
        elif action == "rescan":
            self.start_discovery()
        else:
            self.fail("Unknown watch command")

    def socket_server(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    command = json.loads(connection.recv(4096).decode("utf-8"))
                    GLib.idle_add(self.handle_command, command)
                    response = {"ok": True}
                except (ValueError, json.JSONDecodeError) as error:
                    response = {"ok": False, "error": str(error)}
                connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def run(self) -> None:
        self.register_agent()
        self.bus.add_signal_receiver(
            self.on_interfaces_added,
            dbus_interface=OBJECT_MANAGER,
            signal_name="InterfacesAdded",
        )
        self.bus.add_signal_receiver(
            self.on_properties_changed,
            dbus_interface=PROPERTIES,
            signal_name="PropertiesChanged",
            path_keyword="path",
        )
        self.bus.add_signal_receiver(
            self.on_bluez_owner_changed,
            dbus_interface="org.freedesktop.DBus",
            signal_name="NameOwnerChanged",
            arg0=BLUEZ,
        )
        threading.Thread(target=self.socket_server, name="watch-control", daemon=True).start()
        self.start_discovery()
        self.context_signature = self.file_signature(
            self.theme_path, self.weather_location_path, self.shell_config_path
        )
        self.refresh_effective_context()
        GLib.timeout_add_seconds(2, self.check_context_files)
        GLib.timeout_add_seconds(WEATHER_REFRESH_SECONDS, self.periodic_weather_refresh)
        GLib.MainLoop().run()


if __name__ == "__main__":
    WatchDaemon().run()
