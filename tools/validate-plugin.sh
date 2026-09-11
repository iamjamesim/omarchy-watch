#!/usr/bin/env bash

set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
validation_dir=$(mktemp -d)
trap 'rm -rf "$validation_dir"' EXIT

mkdir -p "$validation_dir/desktop/plugin"
install -m 0644 "$repo_dir/manifest.json" "$validation_dir/manifest.json"
install -m 0644 \
  "$repo_dir/desktop/plugin/BarWidget.qml" \
  "$validation_dir/desktop/plugin/BarWidget.qml"

omarchy plugin validate "$validation_dir"
