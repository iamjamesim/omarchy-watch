#!/usr/bin/env bash

set -euo pipefail

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib_dir=$HOME/.local/lib/omarchy-watch
bin_dir=$HOME/.local/bin
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
plugin_dir=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.iamjamesim.omarchy-watch

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
omarchy plugin enable io.github.iamjamesim.omarchy-watch --section right
echo "Codex activity hooks installed. Review and trust them with /hooks in Codex."
