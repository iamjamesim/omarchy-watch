#!/usr/bin/env bash

set -euo pipefail

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib_dir=$HOME/.local/lib/omarchy-watch
bin_dir=$HOME/.local/bin
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
plugin_dir=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.iamjamesim.omarchy-watch
plugin_id=io.github.iamjamesim.omarchy-watch

if command -v omarchy >/dev/null; then
  omarchy plugin disable "$plugin_id" >/dev/null 2>&1 || true
fi

systemctl --user disable --now omarchy-watch.service >/dev/null 2>&1 || true

rm -f "$bin_dir/omarchy-watchctl"
rm -f "$unit_dir/omarchy-watch.service"
rm -rf "$lib_dir"
rm -rf "$plugin_dir"

systemctl --user daemon-reload
if command -v omarchy-shell >/dev/null; then
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
fi
if command -v omarchy >/dev/null; then
  omarchy restart shell >/dev/null 2>&1 || true
fi

echo "Omarchy Watch was removed."
echo "Pairing, settings, and cached state were preserved for a future reinstall."
