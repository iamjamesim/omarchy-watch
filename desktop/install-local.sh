#!/usr/bin/env bash

set -euo pipefail

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd "$source_dir/.." && pwd)
lib_dir=$HOME/.local/lib/omarchy-watch
bin_dir=$HOME/.local/bin
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
plugin_dir=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.iamjamesim.omarchy-watch
plugin_id=io.github.iamjamesim.omarchy-watch

shell_output() {
  local output
  for _ in {1..40}; do
    if output=$(omarchy-shell shell "$@" 2>/dev/null); then
      printf '%s\n' "$output"
      return 0
    fi
    sleep 0.25
  done
  return 1
}

wait_for_shell() {
  shell_output listPlugins >/dev/null
}

ensure_plugin_enabled() {
  local plugins
  for _ in {1..40}; do
    if plugins=$(omarchy-shell shell listPlugins 2>/dev/null) &&
      jq -e --arg id "$plugin_id" \
        'any(.[]; .id == $id and .enabled == true)' <<<"$plugins" >/dev/null; then
      return 0
    fi
    omarchy plugin enable "$plugin_id" --section right >/dev/null 2>&1 || true
    sleep 0.25
  done
  return 1
}

for command in omarchy omarchy-shell jq systemctl python3; do
  command -v "$command" >/dev/null || {
    echo "Required command not found: $command" >&2
    exit 1
  }
done

omarchy_version=$(omarchy version)
omarchy_major=${omarchy_version%%.*}
if [[ ! $omarchy_major =~ ^[0-9]+$ ]] || ((omarchy_major < 4)); then
  echo "Omarchy 4.0 or newer is required (found: $omarchy_version)." >&2
  exit 1
fi

python3 -c 'import dbus, gi' >/dev/null || {
  echo "Python dbus-python and PyGObject are required." >&2
  exit 1
}

"$repo_dir/tools/validate-plugin.sh"
mkdir -p "$lib_dir" "$bin_dir" "$unit_dir" "$plugin_dir/desktop/plugin"
install -m 0755 "$source_dir/daemon/omarchy_watchd.py" "$lib_dir/omarchy_watchd.py"
install -m 0755 "$source_dir/bin/omarchy-watchctl" "$bin_dir/omarchy-watchctl"
install -m 0755 "$source_dir/bin/omarchy-watch-agent-hook" "$bin_dir/omarchy-watch-agent-hook"
install -m 0644 "$source_dir/systemd/omarchy-watch.service" "$unit_dir/omarchy-watch.service"
if [[ $repo_dir != "$plugin_dir" ]]; then
  install -m 0644 "$repo_dir/manifest.json" "$plugin_dir/manifest.json"
  install -m 0644 "$source_dir/plugin/BarWidget.qml" "$plugin_dir/desktop/plugin/BarWidget.qml"
  rm -f "$plugin_dir/Panel.qml"
  rm -f "$plugin_dir/desktop/plugin/Panel.qml"
fi
"$source_dir/install-codex-hooks.py"

systemctl --user daemon-reload
systemctl --user enable omarchy-watch.service
systemctl --user restart omarchy-watch.service
systemctl --user is-active --quiet omarchy-watch.service

# Refresh the registry after every file is in place, then use Omarchy's
# supported shell restart to discard compiled QML from the previous install.
if ! wait_for_shell; then
  omarchy restart shell || true
  wait_for_shell || {
    echo "Omarchy shell did not become ready before plugin refresh." >&2
    exit 1
  }
fi
if ! shell_output rescanPlugins >/dev/null; then
  echo "Omarchy shell did not accept the plugin refresh." >&2
  exit 1
fi
if ! plugins=$(shell_output listPlugins); then
  echo "Omarchy shell did not return its plugin registry." >&2
  exit 1
fi
if ! jq -e --arg id "$plugin_id" \
  'any(.[]; .id == $id and .enabled == true)' <<<"$plugins" >/dev/null; then
  if ! ensure_plugin_enabled; then
    echo "Omarchy shell did not enable the watch plugin." >&2
    exit 1
  fi
fi
omarchy restart shell || true

if ! wait_for_shell; then
  echo "Omarchy shell did not become ready after restart." >&2
  exit 1
fi

echo "Omarchy Watch panel reloaded."
echo "Codex activity hooks installed. Review and trust them with /hooks in Codex."
