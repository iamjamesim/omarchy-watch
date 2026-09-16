#!/usr/bin/python3 -I
"""Install or remove the Omarchy Watch desktop companion safely."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import subprocess
import sys
import tempfile
import time


PLUGIN_ID = "io.github.iamjamesim.omarchy-watch"
SERVICE_NAME = "omarchy-watch.service"
OMARCHY_PATH = "/usr/share/omarchy"

PYTHON = "/usr/bin/python3"
SYSTEMCTL = "/usr/bin/systemctl"
OMARCHY_VERSION = "/usr/bin/omarchy-version"
OMARCHY_SHELL = "/usr/bin/omarchy-shell"
OMARCHY_PLUGIN_ENABLE = "/usr/bin/omarchy-plugin-enable"
OMARCHY_PLUGIN_DISABLE = "/usr/bin/omarchy-plugin-disable"
OMARCHY_PLUGIN_VALIDATE = "/usr/bin/omarchy-plugin-validate"
OMARCHY_RESTART_SHELL = "/usr/bin/omarchy-restart-shell"

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class InstallError(RuntimeError):
    """A local installation boundary was unsafe or invalid."""


@dataclass(frozen=True)
class Layout:
    source_root: Path
    home: Path
    config_home: Path

    @property
    def lib_dir(self) -> Path:
        return self.home / ".local/lib/omarchy-watch"

    @property
    def bin_dir(self) -> Path:
        return self.home / ".local/bin"

    @property
    def unit_dir(self) -> Path:
        return self.config_home / "systemd/user"

    @property
    def plugin_dir(self) -> Path:
        return self.config_home / "omarchy/plugins" / PLUGIN_ID


def absolute_path(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or any(part in ("", ".", "..") for part in path.parts[1:]):
        raise InstallError(f"{label} must be an absolute path without '.' or '..': {path}")
    return path


def default_layout() -> Layout:
    account = pwd.getpwuid(os.getuid())
    home = absolute_path(account.pw_dir, "account home")
    configured = os.environ.get("XDG_CONFIG_HOME", "")
    config_home = absolute_path(configured, "XDG_CONFIG_HOME") if configured else home / ".config"
    source_root = absolute_path(Path(os.path.abspath(__file__)).parent.parent, "source root")
    return Layout(source_root=source_root, home=home, config_home=config_home)


def safe_directory_mode(metadata: os.stat_result, *, final: bool) -> bool:
    if not stat.S_ISDIR(metadata.st_mode):
        return False
    writable_by_others = metadata.st_mode & 0o022
    if not writable_by_others:
        return True
    # Sticky shared ancestors such as /tmp are safe to traverse by descriptor,
    # but never acceptable as the destination directory itself.
    return not final and bool(metadata.st_mode & stat.S_ISVTX)


@contextlib.contextmanager
def pinned_directory(path: Path, *, create: bool = False):
    """Open every component without following links and retain the final fd."""
    path = absolute_path(path, "directory")
    parts = path.parts[1:]
    descriptor = os.open("/", DIRECTORY_FLAGS)
    try:
        root = os.fstat(descriptor)
        if not safe_directory_mode(root, final=not parts):
            raise InstallError("filesystem root has unsafe permissions")
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            try:
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                raise
            except OSError as error:
                raise InstallError(f"refusing unsafe directory component in {path}: {part}") from error
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if not safe_directory_mode(metadata, final=final):
                raise InstallError(f"directory is writable by another user or is not a directory: {path}")
            if final and metadata.st_uid != os.getuid():
                raise InstallError(f"destination directory is not owned by the current user: {path}")
        yield descriptor
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def regular_source(path: Path):
    path = absolute_path(path, "source file")
    with pinned_directory(path.parent) as parent:
        try:
            descriptor = os.open(path.name, READ_FLAGS, dir_fd=parent)
        except OSError as error:
            raise InstallError(f"refusing source file that cannot be opened without following links: {path}") from error
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o022
            ):
                raise InstallError(f"source must be a current-user-owned regular file not writable by others: {path}")
            yield descriptor
        finally:
            os.close(descriptor)


def entry_revision(parent: int, name: str):
    try:
        metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise InstallError(f"refusing unsafe existing destination: {name}")
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise InstallError("short write while installing file")
        view = view[written:]


def install_file_at(source: Path, parent: int, name: str, mode: int) -> None:
    if not name or "/" in name or name in (".", ".."):
        raise InstallError(f"invalid destination basename: {name!r}")
    before = entry_revision(parent, name)
    staging = f".omarchy-watch-install-{secrets.token_hex(12)}"
    destination = os.open(
        staging,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=parent,
    )
    try:
        with regular_source(source) as source_descriptor:
            while True:
                chunk = os.read(source_descriptor, 65536)
                if not chunk:
                    break
                write_all(destination, chunk)
        os.fchmod(destination, mode)
        os.fsync(destination)
        if entry_revision(parent, name) != before:
            raise InstallError(f"destination changed during installation; retry: {name}")
        os.replace(staging, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(destination)
        try:
            os.unlink(staging, dir_fd=parent)
        except FileNotFoundError:
            pass


def install_file(source: Path, destination: Path, mode: int) -> None:
    destination = absolute_path(destination, "destination file")
    with pinned_directory(destination.parent, create=True) as parent:
        install_file_at(source, parent, destination.name, mode)


def unlink_file(path: Path) -> None:
    path = absolute_path(path, "installed file")
    try:
        with pinned_directory(path.parent) as parent:
            try:
                metadata = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISDIR(metadata.st_mode):
                raise InstallError(f"expected a file, found a directory: {path}")
            if not stat.S_ISLNK(metadata.st_mode) and metadata.st_uid != os.getuid():
                raise InstallError(f"refusing to remove a file not owned by the current user: {path}")
            os.unlink(path.name, dir_fd=parent)
            os.fsync(parent)
    except FileNotFoundError:
        return


def remove_directory_contents(descriptor: int, device: int) -> None:
    for name in os.listdir(descriptor):
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child = os.open(name, DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                opened = os.fstat(child)
                if (
                    opened.st_dev != device
                    or opened.st_uid != os.getuid()
                    or opened.st_mode & 0o022
                ):
                    raise InstallError(f"refusing unsafe installed directory entry: {name}")
                remove_directory_contents(child, device)
                current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    raise InstallError(f"installed directory changed during removal; retry: {name}")
                os.rmdir(name, dir_fd=descriptor)
            finally:
                os.close(child)
        elif stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            if not stat.S_ISLNK(metadata.st_mode) and metadata.st_uid != os.getuid():
                raise InstallError(f"refusing installed file not owned by the current user: {name}")
            os.unlink(name, dir_fd=descriptor)
        else:
            raise InstallError(f"refusing special file in installed directory: {name}")
    os.fsync(descriptor)


def remove_tree(path: Path) -> None:
    path = absolute_path(path, "installed directory")
    try:
        with pinned_directory(path.parent) as parent:
            try:
                metadata = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(metadata.st_mode):
                os.unlink(path.name, dir_fd=parent)
                os.fsync(parent)
                return
            if not stat.S_ISDIR(metadata.st_mode):
                raise InstallError(f"expected an installed directory: {path}")
            descriptor = os.open(path.name, DIRECTORY_FLAGS, dir_fd=parent)
            try:
                opened = os.fstat(descriptor)
                parent_metadata = os.fstat(parent)
                if (
                    opened.st_dev != parent_metadata.st_dev
                    or opened.st_uid != os.getuid()
                    or opened.st_mode & 0o022
                ):
                    raise InstallError(f"refusing unsafe installed directory: {path}")
                remove_directory_contents(descriptor, opened.st_dev)
                current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    raise InstallError(f"installed directory changed during removal; retry: {path}")
                os.rmdir(path.name, dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(descriptor)
    except FileNotFoundError:
        return


def install_files(layout: Layout) -> None:
    desktop = layout.source_root / "desktop"
    install_file(desktop / "daemon/omarchy_watchd.py", layout.lib_dir / "omarchy_watchd.py", 0o755)
    install_file(desktop / "bin/omarchy-watchctl", layout.bin_dir / "omarchy-watchctl", 0o755)
    install_file(desktop / "systemd/omarchy-watch.service", layout.unit_dir / SERVICE_NAME, 0o644)
    if layout.source_root != layout.plugin_dir:
        install_file(layout.source_root / "manifest.json", layout.plugin_dir / "manifest.json", 0o644)
        install_file(
            desktop / "plugin/BarWidget.qml",
            layout.plugin_dir / "desktop/plugin/BarWidget.qml",
            0o644,
        )
        unlink_file(layout.plugin_dir / "Panel.qml")
        unlink_file(layout.plugin_dir / "desktop/plugin/Panel.qml")


def uninstall_files(layout: Layout) -> None:
    unlink_file(layout.bin_dir / "omarchy-watchctl")
    unlink_file(layout.unit_dir / SERVICE_NAME)
    remove_tree(layout.lib_dir)
    remove_tree(layout.plugin_dir)


def verify_absolute_executable(path: str) -> None:
    executable = absolute_path(path, "executable")
    current = Path("/")
    for index, part in enumerate(executable.parts[1:]):
        current /= part
        metadata = os.lstat(current)
        final = index == len(executable.parts[1:]) - 1
        if stat.S_ISLNK(metadata.st_mode):
            if not final:
                raise InstallError(f"executable path contains a symbolic link: {current}")
            target_name = os.readlink(current)
            if not target_name or "/" in target_name or target_name in (".", ".."):
                raise InstallError(f"executable has an unsafe symbolic-link target: {current}")
            target = current.parent / target_name
            metadata = os.lstat(target)
            if stat.S_ISLNK(metadata.st_mode):
                raise InstallError(f"executable has a chained symbolic-link target: {current}")
        if final:
            if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
                raise InstallError(f"required executable is not a regular executable file: {current}")
        elif not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"executable parent is not a directory: {current}")
        if metadata.st_mode & 0o022 and not (not final and metadata.st_mode & stat.S_ISVTX):
            raise InstallError(f"executable path is writable by another user: {current}")


def clean_environment(layout: Layout) -> dict[str, str]:
    account = pwd.getpwuid(os.getuid())
    runtime = f"/run/user/{os.getuid()}"
    return {
        "HOME": str(layout.home),
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(layout.config_home),
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        "OMARCHY_PATH": OMARCHY_PATH,
    }


def run_tool(
    layout: Layout,
    executable: str,
    *arguments: str,
    check: bool = True,
    capture: bool = False,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    verify_absolute_executable(executable)
    return subprocess.run(
        [executable, *arguments],
        check=check,
        env=clean_environment(layout),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else (subprocess.DEVNULL if quiet else None),
        stderr=subprocess.DEVNULL if quiet else None,
        text=True,
    )


def validate_source_plugin(layout: Layout) -> None:
    with tempfile.TemporaryDirectory(prefix="omarchy-watch-validation-") as temporary:
        root = Path(temporary)
        install_file(layout.source_root / "manifest.json", root / "manifest.json", 0o644)
        install_file(
            layout.source_root / "desktop/plugin/BarWidget.qml",
            root / "desktop/plugin/BarWidget.qml",
            0o644,
        )
        run_tool(layout, OMARCHY_PLUGIN_VALIDATE, str(root))


def shell_output(layout: Layout, *arguments: str) -> str | None:
    for _ in range(40):
        result = run_tool(
            layout,
            OMARCHY_SHELL,
            "shell",
            *arguments,
            check=False,
            capture=True,
            quiet=True,
        )
        if result.returncode == 0:
            return result.stdout.rstrip("\n")
        time.sleep(0.25)
    return None


def plugin_is_enabled(payload: str | None) -> bool:
    if payload is None:
        return False
    try:
        plugins = json.loads(payload)
    except (TypeError, ValueError):
        return False
    return isinstance(plugins, list) and any(
        isinstance(plugin, dict)
        and plugin.get("id") == PLUGIN_ID
        and plugin.get("enabled") is True
        for plugin in plugins
    )


def restart_shell(layout: Layout) -> None:
    run_tool(layout, OMARCHY_RESTART_SHELL, check=False, quiet=True)


def install(layout: Layout) -> None:
    for executable in (
        PYTHON,
        SYSTEMCTL,
        OMARCHY_VERSION,
        OMARCHY_SHELL,
        OMARCHY_PLUGIN_ENABLE,
        OMARCHY_PLUGIN_VALIDATE,
        OMARCHY_RESTART_SHELL,
    ):
        verify_absolute_executable(executable)

    version = run_tool(layout, OMARCHY_VERSION, capture=True).stdout.strip()
    major = version.split(".", 1)[0]
    if not major.isdigit() or int(major) < 4:
        raise InstallError(f"Omarchy 4.0 or newer is required (found: {version}).")

    dependency = run_tool(
        layout,
        PYTHON,
        "-I",
        "-c",
        "import dbus, gi",
        check=False,
        quiet=True,
    )
    if dependency.returncode != 0:
        raise InstallError("Python dbus-python and PyGObject are required.")

    validate_source_plugin(layout)
    install_files(layout)

    run_tool(layout, SYSTEMCTL, "--user", "daemon-reload")
    run_tool(layout, SYSTEMCTL, "--user", "enable", SERVICE_NAME)
    run_tool(layout, SYSTEMCTL, "--user", "restart", SERVICE_NAME)
    run_tool(layout, SYSTEMCTL, "--user", "is-active", "--quiet", SERVICE_NAME)

    plugins = shell_output(layout, "listPlugins")
    if plugins is None:
        restart_shell(layout)
        plugins = shell_output(layout, "listPlugins")
        if plugins is None:
            raise InstallError("Omarchy shell did not become ready before plugin refresh.")
    if shell_output(layout, "rescanPlugins") is None:
        raise InstallError("Omarchy shell did not accept the plugin refresh.")
    plugins = shell_output(layout, "listPlugins")
    if plugins is None:
        raise InstallError("Omarchy shell did not return its plugin registry.")
    if not plugin_is_enabled(plugins):
        for _ in range(40):
            run_tool(
                layout,
                OMARCHY_PLUGIN_ENABLE,
                PLUGIN_ID,
                "--section",
                "right",
                check=False,
                quiet=True,
            )
            if plugin_is_enabled(shell_output(layout, "listPlugins")):
                break
            time.sleep(0.25)
        else:
            raise InstallError("Omarchy shell did not enable the watch plugin.")

    restart_shell(layout)
    if shell_output(layout, "listPlugins") is None:
        raise InstallError("Omarchy shell did not become ready after restart.")
    print("Omarchy Watch panel reloaded.")


def uninstall(layout: Layout) -> None:
    run_tool(
        layout,
        OMARCHY_PLUGIN_DISABLE,
        PLUGIN_ID,
        check=False,
        quiet=True,
    )
    run_tool(
        layout,
        SYSTEMCTL,
        "--user",
        "disable",
        "--now",
        SERVICE_NAME,
        check=False,
        quiet=True,
    )

    uninstall_files(layout)

    run_tool(layout, SYSTEMCTL, "--user", "daemon-reload")
    run_tool(
        layout,
        OMARCHY_SHELL,
        "shell",
        "rescanPlugins",
        check=False,
        quiet=True,
    )
    restart_shell(layout)
    print("Omarchy Watch was removed.")
    print("Pairing, settings, and cached state were preserved for a future reinstall.")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("install", "uninstall"):
        print("usage: manage_local.py install | uninstall", file=sys.stderr)
        return 2
    try:
        layout = default_layout()
        if sys.argv[1] == "install":
            install(layout)
        else:
            uninstall(layout)
    except (InstallError, OSError, subprocess.SubprocessError) as error:
        print(f"Omarchy Watch {sys.argv[1]} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
