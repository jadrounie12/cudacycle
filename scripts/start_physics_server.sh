#!/usr/bin/env bash
# Run on the Brev host (ubuntu SSH), not inside noVNC / Isaac.
# Separate venv from ovrtx. Binds 127.0.0.1:8793 only.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${project_dir}/.venv-physx/bin/python"
system_libstdcpp="/usr/lib/x86_64-linux-gnu/libstdc++.so.6"

if [[ ! -x "${python_bin}" ]]; then
  echo "Missing ${python_bin}. Run: bash scripts/setup_physx.sh" >&2
  exit 1
fi

if [[ ! -f "${project_dir}/assets/cudacycle_physics.usda" ]]; then
  echo "Missing assets/cudacycle_physics.usda" >&2
  exit 1
fi

site_packages="$("${python_bin}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export LD_LIBRARY_PATH="${site_packages}/ovstage/bin:${site_packages}/ovstage/bin/plugins${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
if [[ -f "${system_libstdcpp}" ]]; then
  export LD_PRELOAD="${system_libstdcpp}${LD_PRELOAD:+:${LD_PRELOAD}}"
fi

export CUDACYCLE_PHYSX_PORT="${CUDACYCLE_PHYSX_PORT:-8793}"
exec "${python_bin}" "${project_dir}/server/ovphysx_server.py"
