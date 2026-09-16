#!/usr/bin/bash

set -euo pipefail
IFS=$'\n\t'
unset BASH_ENV ENV CDPATH GLOBIGNORE LD_PRELOAD LD_LIBRARY_PATH PYTHONHOME PYTHONPATH

script_path=${BASH_SOURCE[0]}
if [[ $script_path == */* ]]; then
  source_dir=${script_path%/*}
else
  source_dir=.
fi
source_dir=$(builtin cd -P -- "$source_dir" && builtin pwd -P)

environment=(PATH=/usr/bin)
[[ -z ${XDG_CONFIG_HOME:-} ]] || environment+=("XDG_CONFIG_HOME=$XDG_CONFIG_HOME")

exec /usr/bin/env -i "${environment[@]}" \
  /usr/bin/python3 -I "$source_dir/manage_local.py" uninstall
