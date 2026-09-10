#!/usr/bin/env python3
"""Bluetooth owner and profile bridge for Omarchy Watch."""

from __future__ import annotations

import datetime as dt
import hashlib
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
from gi.repository import Gio, GLib


BLUEZ = "org.bluez"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
GATT_CHARACTERISTIC = "org.bluez.GattCharacteristic1"
GATT_MANAGER = "org.bluez.GattManager1"
GATT_PROFILE = "org.bluez.GattProfile1"
AGENT_MANAGER = "org.bluez.AgentManager1"
AGENT = "org.bluez.Agent1"

SERVICE_UUID = "7f510001-1b15-4f0d-b7a5-4cf3a2c98ee1"
CONTROL_UUID = "7f510002-1b15-4f0d-b7a5-4cf3a2c98ee1"
IDENTITY_UUID = "7f510003-1b15-4f0d-b7a5-4cf3a2c98ee1"
ACTIVITY_UUID = "7f510004-1b15-4f0d-b7a5-4cf3a2c98ee1"
AGENT_PATH = "/io/github/omarchy/watch/agent"
GATT_APPLICATION_PATH = "/io/github/omarchy/watch/gatt"
GATT_PROFILE_PATH = f"{GATT_APPLICATION_PATH}/profile0"
PROTOCOL_VERSION = 3
PAIRING_TIMEOUT_SECONDS = 20
PAIRING_CLEANUP_MILLISECONDS = 750
WEATHER_REFRESH_SECONDS = 15 * 60
WEATHER_MAX_AGE_SECONDS = 6 * 60 * 60
DISPLAY_PREVIEW_SECONDS = 30
CONTEXT_RECONCILE_SECONDS = 60
CONTEXT_DEBOUNCE_MILLISECONDS = 200
MIN_BRIGHTNESS = 20
MAX_BRIGHTNESS = 100
DEFAULT_BRIGHTNESS = 50
DEFAULT_COMPLETION_SOUND = True
DEFAULT_BACKGROUND = bytes((0x10, 0x13, 0x15))
DEFAULT_FOREGROUND = bytes((0xCA, 0xCC, 0xCC))
DEFAULT_ACCENT = bytes((0x79, 0x81, 0x86))
AGENT_COMPLETION_DEBOUNCE_MILLISECONDS = 1500
AGENT_ALERT_FRESH_SECONDS = 2 * 60 * 60
AGENT_LEDGER_MAX_AGE_SECONDS = 24 * 60 * 60
ACTIVITY_NONE = 0
ACTIVITY_WORKING = 1
ACTIVITY_ATTENTION = 2
ACTIVITY_ALERT = 1 << 0
ACTIVITY_SOUND = 1 << 1
CAP_COMPLETION_SOUND = 1 << 7


def parse_hex_color(value: object, fallback: bytes) -> bytes:
    text = str(value or "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return fallback
    return bytes.fromhex(text[1:])


def relative_luminance(color: bytes) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: bytes, second: bytes) -> float:
    light, dark = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def readable_accent(background: bytes, foreground: bytes, accent: bytes) -> bytes:
    return accent if contrast_ratio(background, accent) >= 3 else foreground


def theme_palette(
    path: Path | None = None, shell_path: Path | None = None
) -> tuple[bytes, bytes, bytes]:
    colors_path = path or Path.home() / ".local/state/omarchy/current/theme/colors.toml"
    try:
        document = tomllib.loads(colors_path.read_text())
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return DEFAULT_BACKGROUND, DEFAULT_FOREGROUND, DEFAULT_ACCENT
    background = parse_hex_color(document.get("background"), DEFAULT_BACKGROUND)
    foreground = parse_hex_color(document.get("foreground"), DEFAULT_FOREGROUND)
    accent = parse_hex_color(document.get("accent"), DEFAULT_ACCENT)
    resolved_shell_path = shell_path or colors_path.with_name("shell.toml")
    try:
        bar = tomllib.loads(resolved_shell_path.read_text()).get("bar", {})
        background = parse_hex_color(bar.get("background"), background)
        foreground = parse_hex_color(bar.get("text"), foreground)
    except (FileNotFoundError, OSError, AttributeError, tomllib.TOMLDecodeError):
        pass
    return background, foreground, readable_accent(background, foreground, accent)


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
        headers={"User-Agent": "omarchy-watch/0.4"},
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


class AgentActivityLedger:
    """Minimal durable attention state; Codex remains the session authority."""

    def __init__(self, path: Path, epoch: int | None = None):
        self.path = path
        self.sessions: dict[str, dict] = {}
        self.revision = max(1, int(time.time()) if epoch is None else epoch)
        self.load(epoch)

    @staticmethod
    def key(source: str, session: str) -> str:
        return f"{source}:{session}"

    def load(self, epoch: int | None = None) -> None:
        now = int(time.time()) if epoch is None else epoch
        try:
            document = json.loads(self.path.read_text())
            if document.get("schema") != 1:
                return
            self.revision = max(self.revision, int(document.get("revision", 0) or 0))
            for record in document.get("completions", []):
                completed_at = int(record.get("completedAt", 0) or 0)
                revision = int(record.get("revision", 0) or 0)
                source = str(record.get("source", ""))
                session = str(record.get("session", ""))
                turn = str(record.get("turn", ""))
                if (not source or not session or not turn or revision <= 0 or
                        now - completed_at > AGENT_LEDGER_MAX_AGE_SECONDS):
                    continue
                self.sessions[self.key(source, session)] = {
                    "source": source,
                    "session": session,
                    "turn": turn,
                    "state": "attention",
                    "revision": revision,
                    "completedAt": completed_at,
                    "delivered": bool(record.get("delivered")),
                }
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        completions = [
            record for record in self.sessions.values()
            if record["state"] == "attention"
        ]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "schema": 1,
            "revision": self.revision,
            "completions": completions,
        }, separators=(",", ":")) + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def next_revision(self, epoch: int | None = None) -> int:
        now = int(time.time()) if epoch is None else epoch
        self.revision = max(now, self.revision + 1)
        return self.revision

    def working(self, source: str, session: str, turn: str) -> bool:
        key = self.key(source, session)
        previous = self.sessions.get(key)
        if previous and previous["state"] == "working" and previous["turn"] == turn:
            return False
        self.sessions[key] = {
            "source": source,
            "session": session,
            "turn": turn,
            "state": "working",
            "revision": self.next_revision(),
        }
        self.save()
        return True

    def completed(self, source: str, session: str, turn: str,
                  completed_at: int | None = None) -> bool:
        key = self.key(source, session)
        previous = self.sessions.get(key)
        if previous and previous["state"] == "attention" and previous["turn"] == turn:
            return False
        if previous and previous["state"] == "working" and previous["turn"] != turn:
            # A delayed completion from an older turn must not replace newer work.
            return False
        self.sessions[key] = {
            "source": source,
            "session": session,
            "turn": turn,
            "state": "attention",
            "revision": self.next_revision(),
            "completedAt": int(time.time()) if completed_at is None else completed_at,
            # Every distinct completion gets one alert. Successful delivery is
            # persisted so reconnects and repeated snapshots remain silent.
            "delivered": False,
        }
        self.save()
        return True

    def remove(self, source: str, session: str) -> bool:
        if self.sessions.pop(self.key(source, session), None) is None:
            return False
        self.next_revision()
        self.save()
        return True

    def acknowledge_through(self, revision: int) -> bool:
        changed = False
        for key, record in list(self.sessions.items()):
            if record["state"] == "attention" and record["revision"] <= revision:
                del self.sessions[key]
                changed = True
        if changed:
            self.next_revision()
        elif revision >= self.revision:
            # A watch may retain its acknowledgement after the desktop state
            # file is restored or replaced. Keep future events above it.
            self.revision = revision + 1
            changed = True
        if changed:
            self.save()
        return changed

    def mark_delivered_through(self, revision: int) -> None:
        changed = False
        for record in self.sessions.values():
            if (record["state"] == "attention" and
                    record["revision"] <= revision and not record["delivered"]):
                record["delivered"] = True
                changed = True
        if changed:
            self.save()

    def aggregate(self, epoch: int | None = None) -> tuple[int, int, bool]:
        now = int(time.time()) if epoch is None else epoch
        attention = [
            record for record in self.sessions.values()
            if record["state"] == "attention"
        ]
        if attention:
            fresh_undelivered = any(
                not record["delivered"] and
                0 <= now - record["completedAt"] <= AGENT_ALERT_FRESH_SECONDS
                for record in attention
            )
            return ACTIVITY_ATTENTION, self.revision, fresh_undelivered
        if any(record["state"] == "working" for record in self.sessions.values()):
            return ACTIVITY_WORKING, self.revision, False
        return ACTIVITY_NONE, self.revision, False

    def counts(self) -> tuple[int, int]:
        working = sum(record["state"] == "working" for record in self.sessions.values())
        attention = sum(record["state"] == "attention" for record in self.sessions.values())
        return working, attention


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


class WatchGattProfile(dbus.service.Object):
    """BlueZ client profile requesting native auto-connect for our service."""

    def __init__(self, daemon: "WatchDaemon"):
        self.daemon = daemon
        super().__init__(daemon.bus, GATT_PROFILE_PATH)

    @staticmethod
    def properties() -> dict:
        return {
            "UUIDs": dbus.Array([SERVICE_UUID], signature="s"),
        }

    @dbus.service.method(GATT_PROFILE, in_signature="", out_signature="")
    def Release(self):
        GLib.idle_add(self.daemon.on_gatt_profile_released)

    @dbus.service.method(PROPERTIES, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        if interface != GATT_PROFILE or name not in self.properties():
            raise dbus.DBusException(
                f"Unknown property {interface}.{name}",
                name="org.freedesktop.DBus.Error.UnknownProperty",
            )
        return self.properties()[name]

    @dbus.service.method(PROPERTIES, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.properties() if interface == GATT_PROFILE else {}

    @dbus.service.method(PROPERTIES, in_signature="ssv", out_signature="")
    def Set(self, interface, name, value):
        del value
        raise dbus.DBusException(
            f"Property {interface}.{name} is read-only",
            name="org.freedesktop.DBus.Error.PropertyReadOnly",
        )


class WatchGattApplication(dbus.service.Object):
    def __init__(self, daemon: "WatchDaemon"):
        self.profile = WatchGattProfile(daemon)
        super().__init__(daemon.bus, GATT_APPLICATION_PATH)

    @dbus.service.method(
        OBJECT_MANAGER, in_signature="", out_signature="a{oa{sa{sv}}}"
    )
    def GetManagedObjects(self):
        return {
            dbus.ObjectPath(GATT_PROFILE_PATH): {
                GATT_PROFILE: self.profile.properties(),
            },
        }


class WatchDaemon:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.root = self.bluez_object("/")
        self.objects = dbus.Interface(self.root, OBJECT_MANAGER)
        self.adapter_path = ""
        self.device_path = ""
        self.current_device_properties = {}
        self.property_signal_matches = []
        self.property_signal_paths = ()
        self.pairing_device = ""
        self.pending_passkey: int | None = None
        self.pair_attempt = 0
        self.pair_timeout_id = 0
        self.ignore_agent_cancel_until = 0.0
        self.connect_inflight = False
        self.gatt_registration_inflight = False
        self.gatt_registered_adapter = ""
        self.write_inflight = False
        self.activity_dirty = True
        self.activity_inflight_revision = 0
        self.activity_notify_path = ""
        self.activity_notify_match = None
        self.activity_notifications_started = False
        self.pending_agent_completions: dict[str, int] = {}
        self.identity_verified = False
        self.discovery_active = False
        self.context_refresh_inflight = False
        self.context_refresh_source = 0
        self.context_monitors = []
        self.network_monitor = None
        self.watch_protocol = 1
        self.preview_until = 0.0
        self.preview_sent_until = 0.0
        self.force_sync_requested = False
        self.inflight_fingerprint = ""
        self.inflight_theme = ""
        self.inflight_was_forced = False
        self.agent = PairingAgent(self)
        self.gatt_application = WatchGattApplication(self)

        self.runtime_dir = xdg_path("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.state_dir = xdg_path("XDG_STATE_HOME", ".local/state") / "omarchy-watch"
        self.config_dir = xdg_path("XDG_CONFIG_HOME", ".config") / "omarchy-watch"
        self.socket_path = self.runtime_dir / "omarchy-watch.sock"
        self.status_path = self.state_dir / "status.json"
        self.sync_state_path = self.state_dir / "sync.json"
        self.identity_path = self.config_dir / "identity.json"
        self.settings_path = self.config_dir / "settings.json"
        self.activity_ledger_path = self.state_dir / "agent-activity.json"
        self.cache_dir = xdg_path("XDG_CACHE_HOME", ".cache") / "omarchy-watch"
        self.weather_cache_path = self.cache_dir / "weather.json"
        self.theme_path = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
        self.theme_shell_path = self.theme_path.with_name("shell.toml")
        self.weather_location_path = Path.home() / ".local/state/omarchy/settings/weather.json"
        self.theme_name_path = Path.home() / ".local/state/omarchy/current/theme.name"
        self.shell_config_path = xdg_path("XDG_CONFIG_HOME", ".config") / "omarchy" / "shell.json"
        self.context_signature = ()
        self.palette = theme_palette(self.theme_path, self.theme_shell_path)
        self.weather = self.load_cached_weather()
        self.brightness = self.load_brightness()
        self.completion_sound = self.load_completion_sound()
        self.host_id = self.load_host_id()
        self.agent_activity = AgentActivityLedger(self.activity_ledger_path)
        agent_working, agent_attention = self.agent_activity.counts()
        sync_state = self.load_sync_state()
        self.last_profile_revision = int(sync_state.get("profileRevision", 0) or 0)
        self.synced_fingerprint = str(sync_state.get("syncedRevision", ""))
        self.desired_fingerprint = self.profile_fingerprint()
        self.state = {
            "schema": 1,
            "status": "starting",
            "name": "",
            "address": "",
            "paired": False,
            "connected": False,
            "lastSynced": int(sync_state.get("lastSynced", 0) or 0),
            "message": "Starting Bluetooth bridge",
            "theme": str(sync_state.get("theme", "")) or self.current_theme_name(),
            "weatherLocation": self.weather.get("location", ""),
            "weatherUpdated": self.weather.get("updatedAt", 0),
            "brightness": self.brightness,
            "completionSound": self.completion_sound,
            "deviceId": str(sync_state.get("deviceId", "")),
            "protocol": int(sync_state.get("protocol", 0) or 0),
            "firmware": str(sync_state.get("firmware", "")),
            "capabilities": int(sync_state.get("capabilities", 0) or 0),
            "watchOwned": bool(sync_state.get("watchOwned", False)),
            "agentState": (
                "attention" if agent_attention else "working" if agent_working else "idle"
            ),
            "agentsWorking": agent_working,
            "agentsAwaitingAttention": agent_attention,
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

    def load_brightness(self) -> int:
        try:
            document = json.loads(self.settings_path.read_text())
            brightness = int(document["brightness"])
            if MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
                return brightness
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return DEFAULT_BRIGHTNESS

    def load_completion_sound(self) -> bool:
        try:
            document = json.loads(self.settings_path.read_text())
            enabled = document["completionSound"]
            if isinstance(enabled, bool):
                return enabled
        except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError):
            pass
        return DEFAULT_COMPLETION_SOUND

    def load_sync_state(self) -> dict:
        try:
            document = json.loads(self.sync_state_path.read_text())
            return document if document.get("schema") == 1 else {}
        except (FileNotFoundError, OSError, TypeError, json.JSONDecodeError):
            return {}

    def save_sync_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.sync_state_path.with_suffix(".tmp")
        document = {
            "schema": 1,
            "syncedRevision": self.synced_fingerprint,
            "lastSynced": int(self.state.get("lastSynced", 0) or 0),
            "profileRevision": self.last_profile_revision,
            "theme": self.state.get("theme", ""),
            "deviceId": self.state.get("deviceId", ""),
            "protocol": int(self.state.get("protocol", 0) or 0),
            "firmware": self.state.get("firmware", ""),
            "capabilities": int(self.state.get("capabilities", 0) or 0),
            "watchOwned": bool(self.state.get("watchOwned", False)),
        }
        temporary.write_text(json.dumps(document, separators=(",", ":")) + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(self.sync_state_path)

    def effective_weather(self, epoch: int | None = None) -> dict:
        now = int(time.time()) if epoch is None else epoch
        weather = self.weather
        weather_age = now - int(weather.get("updatedAt", 0) or 0)
        valid = bool(weather.get("valid")) and 0 <= weather_age <= WEATHER_MAX_AGE_SECONDS
        if not valid:
            return {"valid": False}
        return {
            "valid": True,
            "updatedAt": int(weather.get("updatedAt", 0) or 0),
            "temperature": max(-99, min(199, int(weather.get("temperature", 0) or 0))),
            "high": max(-99, min(199, int(weather.get("high", 0) or 0))),
            "low": max(-99, min(199, int(weather.get("low", 0) or 0))),
            "code": max(0, min(99, int(weather.get("code", 0) or 0))),
            "night": bool(weather.get("night")),
            "fahrenheit": bool(weather.get("fahrenheit")),
            "location": ascii_label(weather.get("location", "")),
        }

    def profile_fingerprint(self) -> str:
        now = dt.datetime.now().astimezone()
        offset = int((now.utcoffset() or dt.timedelta()).total_seconds() // 60)
        background, foreground, accent = self.palette
        document = {
            "schema": PROTOCOL_VERSION,
            "owner": self.host_id.hex(),
            "utcOffsetMinutes": offset,
            "hourCycle": self.desktop_hour_cycle(),
            "background": background.hex(),
            "foreground": foreground.hex(),
            "accent": accent.hex(),
            "brightness": self.brightness,
            "weather": self.effective_weather(),
        }
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def sync_pending(self) -> bool:
        return self.desired_fingerprint != self.synced_fingerprint

    def sync_needed(self) -> bool:
        return self.force_sync_requested or self.sync_pending()

    def on_gatt_profile_released(self) -> bool:
        self.gatt_registration_inflight = False
        self.gatt_registered_adapter = ""
        return False

    def ensure_gatt_profile_registered(self) -> None:
        if (not self.adapter_path or self.gatt_registration_inflight or
                self.gatt_registered_adapter == self.adapter_path):
            return
        adapter_path = self.adapter_path
        self.gatt_registration_inflight = True
        try:
            manager = dbus.Interface(
                self.bluez_object(adapter_path), GATT_MANAGER
            )
            manager.RegisterApplication(
                GATT_APPLICATION_PATH,
                dbus.Dictionary({}, signature="sv"),
                reply_handler=lambda: self.on_gatt_profile_registered(adapter_path),
                error_handler=lambda error: self.on_gatt_profile_error(
                    adapter_path, error
                ),
            )
        except dbus.DBusException as error:
            self.on_gatt_profile_error(adapter_path, error)

    def on_gatt_profile_registered(self, adapter_path: str) -> None:
        self.gatt_registration_inflight = False
        self.gatt_registered_adapter = adapter_path
        self.log("Registered BlueZ auto-connect profile")

    def on_gatt_profile_error(self, adapter_path: str, error) -> None:
        self.gatt_registration_inflight = False
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        if name == "org.bluez.Error.AlreadyExists":
            self.gatt_registered_adapter = adapter_path
            return
        detail = (
            error.get_dbus_message()
            if isinstance(error, dbus.DBusException) else str(error)
        )
        self.log(
            f"BlueZ auto-connect profile registration failed with "
            f"{name or 'unknown'}: {detail}"
        )

    def refresh_desired_profile(self, preview: bool = False) -> bool:
        fingerprint = self.profile_fingerprint()
        changed = fingerprint != self.desired_fingerprint
        self.desired_fingerprint = fingerprint
        if changed and preview:
            self.preview_until = time.monotonic() + DISPLAY_PREVIEW_SECONDS
        if changed:
            self.write_state()
        if (self.sync_pending() and self.state.get("paired") and
                self.state.get("connected") and self.pending_passkey is None):
            self.ensure_connection("profile update")
        return changed

    def save_settings(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "schema": 1,
            "brightness": self.brightness,
            "completionSound": self.completion_sound,
        }, indent=2) + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(self.settings_path)

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
                signature.append(hashlib.sha256(path.read_bytes()).digest())
            except OSError:
                signature.append(b"")
        return tuple(signature)

    def refresh_effective_context(self, refresh_weather: bool = True) -> None:
        palette = theme_palette(self.theme_path, self.theme_shell_path)
        if palette != self.palette:
            self.palette = palette
            self.context_changed(preview=True)
        if not refresh_weather or self.context_refresh_inflight:
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
            self.refresh_desired_profile()
        return False

    def context_changed(self, preview: bool = False) -> None:
        self.refresh_desired_profile(preview)

    def check_context_files(self) -> bool:
        signature = self.file_signature(
            self.theme_path, self.theme_shell_path, self.theme_name_path,
            self.weather_location_path, self.shell_config_path,
        )
        if signature != self.context_signature:
            previous_signature = self.context_signature
            self.context_signature = signature
            shell_changed = bool(previous_signature) and signature[4] != previous_signature[4]
            weather_context_changed = bool(previous_signature) and (
                signature[3] != previous_signature[3] or shell_changed
            )
            if shell_changed:
                self.context_changed()
            self.refresh_effective_context(refresh_weather=weather_context_changed)
            self.refresh_desired_profile()
            if not self.sync_pending():
                self.write_state(theme=self.current_theme_name())
        else:
            self.refresh_desired_profile()
        return True

    def schedule_context_check(self) -> None:
        if self.context_refresh_source:
            GLib.source_remove(self.context_refresh_source)
        self.context_refresh_source = GLib.timeout_add(
            CONTEXT_DEBOUNCE_MILLISECONDS, self.run_scheduled_context_check
        )

    def run_scheduled_context_check(self) -> bool:
        self.context_refresh_source = 0
        self.check_context_files()
        return False

    def on_context_path_changed(self, monitor, file, other_file, event_type) -> None:
        del monitor, other_file, event_type
        path = Path(file.get_path())
        watched = {
            self.theme_path.parent,
            self.theme_name_path,
            self.weather_location_path,
            self.shell_config_path,
        }
        if path in watched:
            self.schedule_context_check()

    def start_context_monitors(self) -> None:
        roots = {
            self.theme_name_path.parent,
            self.weather_location_path.parent,
            self.shell_config_path.parent,
        }
        for root in roots:
            if not root.is_dir():
                continue
            try:
                monitor = Gio.File.new_for_path(str(root)).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None
                )
                monitor.connect("changed", self.on_context_path_changed)
                self.context_monitors.append(monitor)
            except GLib.Error as error:
                self.log(f"Could not watch desktop context at {root}: {error}")

    def on_prepare_for_sleep(self, sleeping) -> None:
        if not bool(sleeping):
            self.ensure_gatt_profile_registered()
            self.schedule_context_check()
            self.refresh_effective_context()

    def on_network_changed(self, monitor, available: bool) -> None:
        del monitor
        if available:
            self.refresh_effective_context()

    def periodic_weather_refresh(self) -> bool:
        self.refresh_effective_context()
        return True

    def write_state(self, **changes) -> None:
        self.state.update(changes)
        self.state["desiredRevision"] = self.desired_fingerprint
        self.state["syncedRevision"] = self.synced_fingerprint
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
            self.adapter_path = ""
            self.device_path = ""
            self.current_device_properties = {}
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
            self.discovery_active = False
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
            self.current_device_properties = {}
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
        self.current_device_properties = properties
        paired = bool(properties.get("Paired"))
        if paired:
            self.stop_discovery()
        connected = bool(properties.get("Connected"))
        if not connected:
            self.identity_verified = False
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
            status = (
                "ready" if paired and connected and self.state.get("lastSynced", 0)
                else "paired" if paired and connected
                else "disconnected" if paired
                else "found"
            )
            message = (
                "Ready to pair" if not paired else
                "Changes waiting to sync" if status == "ready" and self.sync_pending() else
                "Up to date" if status == "ready" else
                "Connected" if connected else
                "Waiting for watch to reconnect"
            )
        self.write_state(
            status=status,
            name=properties.get("Name") or properties.get("Alias") or "Omarchy Watch",
            address=properties.get("Address", ""),
            paired=paired,
            connected=connected,
            message=message,
        )
        if paired:
            if connected:
                if properties.get("ServicesResolved"):
                    if self.sync_needed():
                        self.sync_connected_profile()
                    elif self.activity_dirty:
                        self.sync_connected_activity()
        return True

    def start_discovery(self) -> None:
        if not self.refresh_devices():
            self.update_property_receivers()
            return
        self.ensure_gatt_profile_registered()
        if self.device_path and self.current_device_properties.get("Paired"):
            self.update_property_receivers()
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
            self.discovery_active = True
            self.update_property_receivers()
        except dbus.DBusException as error:
            if error.get_dbus_name() == "org.bluez.Error.InProgress":
                # Another discovery session already supplies the same BlueZ
                # events. Retrying would only create a wake-up loop.
                pass
            elif error.get_dbus_name() == "org.bluez.Error.NotReady":
                self.write_state(
                    status="bluetooth-off", connected=False,
                    message="Bluetooth is off",
                )
            else:
                self.fail(f"Bluetooth discovery failed: {error.get_dbus_message()}")

    def stop_discovery(self) -> None:
        if not self.discovery_active or not self.adapter_path:
            return
        self.discovery_active = False
        try:
            dbus.Interface(self.bluez_object(self.adapter_path), ADAPTER).StopDiscovery()
        except dbus.DBusException as error:
            if error.get_dbus_name() not in {
                "org.bluez.Error.NotReady",
                "org.bluez.Error.NotAuthorized",
            }:
                self.log(
                    f"Stopping discovery returned {error.get_dbus_name()}: "
                    f"{error.get_dbus_message()}"
                )

    def register_agent(self) -> None:
        manager_object = self.bluez_object("/org/bluez")
        manager = dbus.Interface(manager_object, AGENT_MANAGER)
        manager.RegisterAgent(AGENT_PATH, "KeyboardOnly")

    def update_property_receivers(self) -> None:
        paths = tuple(path for path in (self.adapter_path, self.device_path) if path)
        if paths == self.property_signal_paths:
            return
        for match in self.property_signal_matches:
            match.remove()
        self.property_signal_matches = [
            self.bus.add_signal_receiver(
                self.on_properties_changed,
                dbus_interface=PROPERTIES,
                signal_name="PropertiesChanged",
                path=path,
                path_keyword="path",
            )
            for path in paths
        ]
        self.property_signal_paths = paths

    def on_interfaces_added(self, path, interfaces) -> None:
        if ADAPTER in interfaces:
            self.start_discovery()
        elif DEVICE in interfaces and self.is_watch(plain(interfaces[DEVICE])):
            self.refresh_devices()
            self.update_property_receivers()

    def on_interfaces_removed(self, path, interfaces) -> None:
        removed = {str(interface) for interface in interfaces}
        device_removed = DEVICE in removed and str(path) == self.device_path
        adapter_removed = ADAPTER in removed and str(path) == self.adapter_path
        if device_removed or adapter_removed:
            can_discover = self.refresh_devices()
            self.update_property_receivers()
            if device_removed and can_discover and not self.device_path:
                GLib.idle_add(self.start_discovery)

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
        device_path = str(path)
        if device_path == self.device_path:
            device_changes = plain(changed)
            for property_name in ("Connected", "ServicesResolved"):
                if property_name in device_changes:
                    self.log(
                        f"BlueZ {property_name}="
                        f"{str(bool(device_changes[property_name])).lower()}"
                    )
            if "Connected" in device_changes and not device_changes["Connected"]:
                self.identity_verified = False
                self.activity_dirty = True
                self.activity_notifications_started = False
            connection_keys = {
                "Connected", "Paired", "ServicesResolved", "Trusted",
                "UUIDs", "Name", "Alias",
            }
            connection_change = bool(connection_keys.intersection(device_changes))
            if not connection_change:
                return
            self.refresh_devices()

    def on_bluez_owner_changed(self, name, old_owner, new_owner) -> None:
        if not new_owner:
            for match in self.property_signal_matches:
                match.remove()
            self.property_signal_matches = []
            self.property_signal_paths = ()
            self.write_state(
                status="unavailable", connected=False,
                message="Bluetooth service is restarting",
            )
            return
        self.connect_inflight = False
        self.write_inflight = False
        self.identity_verified = False
        self.activity_dirty = True
        self.activity_notifications_started = False
        self.discovery_active = False
        self.gatt_registration_inflight = False
        self.gatt_registered_adapter = ""
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
        self.update_property_receivers()
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
        self.stop_discovery()

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
        self.force_sync_requested = True
        self.ensure_gatt_profile_registered()
        self.write_state(status="paired", paired=True, message="Securing ownership")
        properties = dbus.Interface(self.bluez_object(self.device_path), PROPERTIES)
        properties.Set(DEVICE, "Trusted", dbus.Boolean(True))
        self.ensure_connection("pairing")

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

    def ensure_connection(self, reason: str = "unspecified") -> bool:
        if not self.device_path or self.connect_inflight:
            return False
        if self.write_inflight:
            return False
        properties = self.device_properties(self.device_path)
        if properties.get("Connected"):
            self.refresh_devices()
            return False
        self.connect_inflight = True
        self.identity_verified = False
        self.log(f"Starting explicit connection attempt ({reason})")
        self.write_state(status="syncing", message="Connecting to watch")
        device = self.bluez_object(self.device_path)
        try:
            dbus.Interface(device, DEVICE).Connect(
                reply_handler=self.on_connected,
                error_handler=self.on_connect_error,
                timeout=30,
            )
        except dbus.DBusException as error:
            self.on_connect_error(error)
        return False

    def on_connected(self) -> None:
        self.log("Explicit connection request completed")
        self.connect_inflight = False
        self.identity_verified = False
        self.refresh_devices()

    def on_connect_error(self, error) -> None:
        self.connect_inflight = False
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        detail = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        self.log(f"Connection attempt failed with {name or 'unknown'}: {detail}")
        if name == "org.bluez.Error.AlreadyConnected":
            self.refresh_devices()
            return
        if name == "org.bluez.Error.InProgress":
            self.write_state(status="syncing", message="Connecting to watch")
            return
        if self.handle_transport_error(error):
            return
        self.fail(f"Connection failed: {detail}")

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
            self.log(f"Bluetooth transport error {name or 'unknown'}: {message}")
            self.identity_verified = False
            status = "bluetooth-off" if name == "org.bluez.Error.NotReady" else "disconnected"
            friendly = (
                "Bluetooth is off" if status == "bluetooth-off" else
                "Waiting for watch to reconnect"
            )
            self.write_state(status=status, connected=False, message=friendly)
            return True
        return False

    def sync_connected_profile(self) -> None:
        self.connect_inflight = False
        if self.write_inflight:
            return
        if not self.sync_needed():
            self.sync_connected_activity()
            return
        identity_path = self.find_characteristic(IDENTITY_UUID)
        control_path = self.find_characteristic(CONTROL_UUID)
        if not identity_path or not control_path:
            self.fail("The watch connected but its setup service did not appear")
            return

        self.write_state(status="syncing", connected=True, message="Sending desktop settings")
        self.write_inflight = True
        if self.identity_verified:
            self.write_profile()
            return
        characteristic = dbus.Interface(
            self.bluez_object(identity_path), GATT_CHARACTERISTIC
        )
        characteristic.ReadValue(
            dbus.Dictionary({}, signature="sv"),
            reply_handler=self.on_identity_read,
            error_handler=self.on_identity_error,
            timeout=30,
        )

    def find_characteristic(self, wanted_uuid: str) -> str:
        for path, interfaces in self.managed_objects().items():
            characteristic = plain(interfaces.get(GATT_CHARACTERISTIC, {}))
            if (str(path).startswith(self.device_path + "/") and
                    characteristic.get("UUID", "").lower() == wanted_uuid):
                return str(path)
        return ""

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
        resolved_device_id = str(uuid.UUID(bytes=device_id))
        previous_device_id = str(self.state.get("deviceId", ""))
        if self.synced_fingerprint and previous_device_id != resolved_device_id:
            self.synced_fingerprint = ""
            self.state["lastSynced"] = 0
        self.write_state(
            deviceId=resolved_device_id,
            protocol=self.watch_protocol,
            firmware=f"{fw_major}.{fw_minor}.{fw_patch}",
            capabilities=capabilities,
            watchOwned=bool(owned & 1),
        )
        self.identity_verified = True
        self.write_profile()

    def on_identity_error(self, error) -> None:
        self.write_inflight = False
        if self.inflight_was_forced:
            self.force_sync_requested = True
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
        self.desired_fingerprint = self.profile_fingerprint()
        self.inflight_fingerprint = self.desired_fingerprint
        self.inflight_theme = self.current_theme_name()
        self.inflight_was_forced = self.force_sync_requested
        self.force_sync_requested = False
        revision = max(epoch & 0xFFFFFFFF, self.last_profile_revision + 1)
        self.last_profile_revision = revision
        cycle = self.desktop_hour_cycle()
        if self.watch_protocol < 2:
            return struct.pack(
                "<2sBBIqhBB16s",
                b"OW", 1, 1, revision, epoch, offset, cycle, 0, self.host_id,
            )

        background, foreground, accent = self.palette
        weather = self.effective_weather(epoch)
        weather_valid = weather.get("valid", False)
        flags = 0
        if weather_valid:
            flags |= 1
        if weather.get("fahrenheit"):
            flags |= 1 << 1
        if weather.get("night"):
            flags |= 1 << 2
        if self.watch_protocol >= 3 and time.monotonic() <= self.preview_until:
            flags |= 1 << 3
            self.preview_sent_until = self.preview_until
        else:
            self.preview_sent_until = 0.0

        location = weather.get("location", "") if weather_valid else ""
        location_bytes = location.encode("ascii")[:23].ljust(24, b"\0")
        values = (
            b"OW", self.watch_protocol, 1, revision, epoch, offset, cycle, flags,
            self.host_id, background, foreground,
            int(weather.get("updatedAt", 0) or 0) if weather_valid else 0,
            int(weather.get("temperature", 0)),
            int(weather.get("high", 0)),
            int(weather.get("low", 0)),
            int(weather.get("code", 0)),
            location_bytes,
        )
        if self.watch_protocol == 2:
            return struct.pack(
                "<2sBBIqhBB16s3s3sqhhhB24s",
                *values,
            )
        return struct.pack(
            "<2sBBIqhBB16s3s3sqhhhB24s3sB",
            *values, accent, self.brightness,
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
        if self.preview_sent_until == self.preview_until:
            self.preview_until = 0.0
        self.preview_sent_until = 0.0
        now = int(time.time())
        self.pairing_device = ""
        self.pending_passkey = None
        self.synced_fingerprint = self.inflight_fingerprint
        pending = self.sync_pending()
        self.write_state(
            status="ready", paired=True, connected=True, lastSynced=now,
            message=("New changes are waiting to sync" if pending else
                     "Time, weather, and theme are up to date"),
            theme=self.inflight_theme,
        )
        self.save_sync_state()
        self.inflight_fingerprint = ""
        self.inflight_theme = ""
        self.inflight_was_forced = False
        if self.sync_needed():
            self.sync_connected_profile()
        elif getattr(self, "activity_dirty", False):
            self.sync_connected_activity()

    def on_profile_error(self, error) -> None:
        self.write_inflight = False
        if self.inflight_was_forced:
            self.force_sync_requested = True
        self.inflight_fingerprint = ""
        self.inflight_theme = ""
        self.inflight_was_forced = False
        if self.handle_transport_error(error):
            return
        message = error.get_dbus_message() if isinstance(error, dbus.DBusException) else str(error)
        self.fail(f"Profile sync failed: {message}")

    def sync_connected_activity(self) -> None:
        if self.write_inflight or not self.activity_dirty:
            return
        if not self.state.get("connected"):
            return
        activity_path = self.find_characteristic(ACTIVITY_UUID)
        if not activity_path:
            # Firmware before agent activity simply ignores this optional feature.
            self.activity_dirty = False
            return
        self.write_inflight = True
        if self.activity_notify_path != activity_path:
            if self.activity_notify_match is not None:
                self.activity_notify_match.remove()
            self.activity_notify_path = activity_path
            self.activity_notify_match = self.bus.add_signal_receiver(
                self.on_activity_properties_changed,
                dbus_interface=PROPERTIES,
                signal_name="PropertiesChanged",
                path=activity_path,
            )
            self.activity_notifications_started = False
        if self.activity_notifications_started:
            self.read_activity_ack()
            return
        characteristic = dbus.Interface(
            self.bluez_object(activity_path), GATT_CHARACTERISTIC
        )
        characteristic.StartNotify(
            reply_handler=self.on_activity_notify_started,
            error_handler=self.on_activity_notify_error,
            timeout=10,
        )

    def on_activity_notify_started(self) -> None:
        self.activity_notifications_started = True
        self.read_activity_ack()

    def on_activity_notify_error(self, error) -> None:
        name = error.get_dbus_name() if isinstance(error, dbus.DBusException) else ""
        if name not in {
            "org.bluez.Error.InProgress",
            "org.bluez.Error.AlreadyExists",
        }:
            self.log(f"Activity notifications unavailable: {error}")
        else:
            self.activity_notifications_started = True
        # Reads on reconnect still reconcile offline watch acknowledgements.
        self.read_activity_ack()

    def read_activity_ack(self) -> None:
        activity_path = self.find_characteristic(ACTIVITY_UUID)
        if not activity_path:
            self.write_inflight = False
            return
        characteristic = dbus.Interface(
            self.bluez_object(activity_path), GATT_CHARACTERISTIC
        )
        characteristic.ReadValue(
            dbus.Dictionary({}, signature="sv"),
            reply_handler=self.on_activity_read,
            error_handler=self.on_activity_error,
            timeout=10,
        )

    @staticmethod
    def parse_activity_packet(raw_activity) -> tuple[int, int, int] | None:
        value = bytes(int(item) for item in raw_activity)
        if len(value) != 14:
            return None
        magic, version, state, flags, _, revision, acknowledged = struct.unpack(
            "<2sBBBBII", value
        )
        if magic != b"OA" or version != 1 or state > ACTIVITY_ATTENTION:
            return None
        return revision, acknowledged, flags

    def on_activity_read(self, raw_activity) -> None:
        parsed = self.parse_activity_packet(raw_activity)
        if parsed is None:
            self.write_inflight = False
            self.log("Watch returned an invalid activity acknowledgement")
            return
        _, acknowledged, _ = parsed
        if self.agent_activity.acknowledge_through(acknowledged):
            self.update_agent_status()
        self.write_activity()

    def activity_payload(self) -> bytes:
        state, revision, alert = self.agent_activity.aggregate()
        flags = ACTIVITY_ALERT if alert else 0
        if (alert and self.completion_sound and
                int(self.state.get("capabilities", 0) or 0) & CAP_COMPLETION_SOUND):
            flags |= ACTIVITY_SOUND
        self.activity_inflight_revision = revision
        return struct.pack("<2sBBBBII", b"OA", 1, state, flags, 0, revision, 0)

    def write_activity(self) -> None:
        activity_path = self.find_characteristic(ACTIVITY_UUID)
        if not activity_path:
            self.write_inflight = False
            return
        characteristic = dbus.Interface(
            self.bluez_object(activity_path), GATT_CHARACTERISTIC
        )
        characteristic.WriteValue(
            dbus.Array(self.activity_payload(), signature="y"),
            {"type": dbus.String("request")},
            reply_handler=self.on_activity_written,
            error_handler=self.on_activity_error,
            timeout=10,
        )

    def on_activity_written(self) -> None:
        self.write_inflight = False
        self.agent_activity.mark_delivered_through(self.activity_inflight_revision)
        self.activity_dirty = self.agent_activity.revision != self.activity_inflight_revision
        if self.sync_needed():
            self.sync_connected_profile()
        elif self.activity_dirty:
            self.sync_connected_activity()

    def on_activity_error(self, error) -> None:
        self.write_inflight = False
        self.activity_dirty = True
        if self.handle_transport_error(error):
            return
        self.log(f"Agent activity sync failed: {error}")

    def on_activity_properties_changed(self, interface, changed, invalidated) -> None:
        del invalidated
        if interface != GATT_CHARACTERISTIC or "Value" not in changed:
            return
        parsed = self.parse_activity_packet(changed["Value"])
        if parsed is None:
            return
        _, acknowledged, _ = parsed
        if self.agent_activity.acknowledge_through(acknowledged):
            self.activity_dirty = True
            self.update_agent_status()
            self.sync_connected_activity()

    @staticmethod
    def valid_agent_identifier(value: object) -> str:
        text = str(value or "")
        if not text or len(text) > 160 or any(ord(character) < 0x20 for character in text):
            return ""
        return text

    def update_agent_status(self) -> None:
        working, attention = self.agent_activity.counts()
        self.write_state(
            agentState="attention" if attention else "working" if working else "idle",
            agentsWorking=working,
            agentsAwaitingAttention=attention,
        )

    def agent_activity_changed(self) -> None:
        self.activity_dirty = True
        self.update_agent_status()
        if not self.state.get("paired"):
            return
        if self.state.get("connected"):
            self.sync_connected_activity()

    def cancel_pending_completion(self, source: str, session: str) -> None:
        key = AgentActivityLedger.key(source, session)
        source_id = self.pending_agent_completions.pop(key, 0)
        if source_id:
            GLib.source_remove(source_id)

    def finish_agent_completion(self, source: str, session: str,
                                turn: str, completed_at: int) -> bool:
        self.pending_agent_completions.pop(
            AgentActivityLedger.key(source, session), None
        )
        if self.agent_activity.completed(source, session, turn, completed_at):
            self.agent_activity_changed()
        return False

    def handle_agent_event(self, command: dict) -> None:
        source = self.valid_agent_identifier(command.get("source"))
        session = self.valid_agent_identifier(command.get("session"))
        turn = self.valid_agent_identifier(command.get("turn"))
        event = str(command.get("event", ""))
        if not source or not session or event not in {
            "working", "completed", "interrupted", "ended",
        }:
            self.log("Ignored invalid agent activity event")
            return

        self.cancel_pending_completion(source, session)
        if event == "working":
            if not turn:
                return
            if self.agent_activity.working(source, session, turn):
                self.agent_activity_changed()
            return
        if event == "completed":
            if not turn:
                return
            completed_at = int(command.get("timestamp", 0) or time.time())
            key = AgentActivityLedger.key(source, session)
            self.pending_agent_completions[key] = GLib.timeout_add(
                AGENT_COMPLETION_DEBOUNCE_MILLISECONDS,
                self.finish_agent_completion,
                source, session, turn, completed_at,
            )
            return
        if self.agent_activity.remove(source, session):
            self.agent_activity_changed()

    def handle_command(self, command: dict) -> None:
        action = command.get("command")
        if action == "pair":
            self.pair(int(command.get("passkey", 0)))
        elif action == "sync":
            self.force_sync_requested = True
            self.ensure_connection("manual sync")
        elif action == "rescan":
            self.start_discovery()
        elif action == "brightness":
            try:
                brightness = int(command.get("value"))
            except (TypeError, ValueError):
                self.fail("Brightness must be a whole percentage")
                return
            if not MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
                self.fail(f"Brightness must be between {MIN_BRIGHTNESS} and {MAX_BRIGHTNESS}")
                return
            self.brightness = brightness
            self.save_settings()
            self.write_state(brightness=brightness)
            self.context_changed(preview=True)
        elif action == "sound":
            enabled = command.get("enabled")
            if not isinstance(enabled, bool):
                self.fail("Completion sound must be on or off")
                return
            self.completion_sound = enabled
            self.save_settings()
            self.write_state(completionSound=enabled)
        elif action == "agent-event":
            self.handle_agent_event(command)
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
            self.on_interfaces_removed,
            dbus_interface=OBJECT_MANAGER,
            signal_name="InterfacesRemoved",
        )
        self.bus.add_signal_receiver(
            self.on_bluez_owner_changed,
            dbus_interface="org.freedesktop.DBus",
            signal_name="NameOwnerChanged",
            arg0=BLUEZ,
        )
        self.bus.add_signal_receiver(
            self.on_prepare_for_sleep,
            dbus_interface="org.freedesktop.login1.Manager",
            signal_name="PrepareForSleep",
        )
        threading.Thread(target=self.socket_server, name="watch-control", daemon=True).start()
        self.start_context_monitors()
        self.network_monitor = Gio.NetworkMonitor.get_default()
        self.network_monitor.connect("network-changed", self.on_network_changed)
        self.start_discovery()
        self.context_signature = self.file_signature(
            self.theme_path, self.theme_shell_path, self.theme_name_path,
            self.weather_location_path, self.shell_config_path,
        )
        self.refresh_effective_context()
        GLib.timeout_add_seconds(CONTEXT_RECONCILE_SECONDS, self.check_context_files)
        GLib.timeout_add_seconds(WEATHER_REFRESH_SECONDS, self.periodic_weather_refresh)
        GLib.MainLoop().run()


if __name__ == "__main__":
    WatchDaemon().run()
