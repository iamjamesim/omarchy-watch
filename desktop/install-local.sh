#!/usr/bin/env bash

set -euo pipefail

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib_dir=$HOME/.local/lib/omarchy-watch
bin_dir=$HOME/.local/bin
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
plugin_dir=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.iamjamesim.omarchy-watch
plugin_id=io.github.iamjamesim.omarchy-watch

omarchy plugin validate "$source_dir/plugin"
mkdir -p "$lib_dir" "$bin_dir" "$unit_dir" "$plugin_dir"
install -m 0755 "$source_dir/daemon/omarchy_watchd.py" "$lib_dir/omarchy_watchd.py"
install -m 0755 "$source_dir/bin/omarchy-watchctl" "$bin_dir/omarchy-watchctl"
install -m 0755 "$source_dir/bin/omarchy-watch-agent-hook" "$bin_dir/omarchy-watch-agent-hook"
install -m 0644 "$source_dir/systemd/omarchy-watch.service" "$unit_dir/omarchy-watch.service"
install -m 0644 "$source_dir/plugin/manifest.json" "$plugin_dir/manifest.json"
install -m 0644 "$source_dir/plugin/Panel.qml" "$plugin_dir/Panel.qml"
"$source_dir/install-codex-hooks.py"

systemctl --user daemon-reload
systemctl --user enable omarchy-watch.service
systemctl --user restart omarchy-watch.service
systemctl --user is-active --quiet omarchy-watch.service

# File watching normally reloads user plugins. The explicit rescan provides a
# completion boundary for installs and upgrades after every file is in place.
omarchy-shell shell rescanPlugins >/dev/null
plugins=$(omarchy-shell shell listPlugins)
if ! jq -e --arg id "$plugin_id" \
  'any(.[]; .id == $id and .enabled == true)' <<<"$plugins" >/dev/null; then
  omarchy plugin enable "$plugin_id" --section right
fi

echo "Omarchy Watch panel reloaded."
echo "Codex activity hooks installed. Review and trust them with /hooks in Codex."
