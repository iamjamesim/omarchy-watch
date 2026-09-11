#!/usr/bin/env bash

set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
omarchy_path=${OMARCHY_PATH:-/usr/share/omarchy}

if command -v qmllint >/dev/null; then
  qmllint_command=$(command -v qmllint)
elif [[ -x /usr/lib/qt6/bin/qmllint ]]; then
  qmllint_command=/usr/lib/qt6/bin/qmllint
else
  echo "qmllint was not found. Install the Qt 6 declarative tools." >&2
  exit 1
fi

if [[ ! -d $omarchy_path/shell ]]; then
  echo "Omarchy shell imports were not found at $omarchy_path/shell." >&2
  exit 1
fi

import_root=$(mktemp -d)
trap 'rm -rf "$import_root"' EXIT
ln -s "$omarchy_path/shell" "$import_root/qs"

"$qmllint_command" \
  -I "$import_root" \
  "$repo_dir/desktop/plugin/BarWidget.qml"
