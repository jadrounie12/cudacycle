#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${project_dir}/.venv/bin/python"
system_libstdcpp="/usr/lib/x86_64-linux-gnu/libstdc++.so.6"

if [[ ! -x "${python_bin}" ]]; then
  echo "Missing .venv. Run: bash scripts/setup_brev.sh" >&2
  exit 1
fi

if [[ ! -f "${project_dir}/assets/cudacycle_visual.usda" ]]; then
  echo "Missing assets/cudacycle_visual.usda" >&2
  exit 1
fi

if [[ -f "${system_libstdcpp}" ]]; then
  export LD_PRELOAD="${system_libstdcpp}${LD_PRELOAD:+:${LD_PRELOAD}}"
fi

# noVNC XFCE is DISPLAY=:0 (Xtigervnc). The ubuntu SSH session has no DISPLAY.
# ovrtx first step hangs unless it can talk to this X server.
if [[ -z "${DISPLAY:-}" && -e /tmp/.X11-unix/X0 ]]; then
  export DISPLAY=:0
fi
if [[ -n "${DISPLAY:-}" && -f /root/.Xauthority ]]; then
  export XAUTHORITY="${XAUTHORITY:-/root/.Xauthority}"
fi

# Headless L40S: the packaged nvidia_icd.json points at libGLX_nvidia and
# fails vkCreateInstance. libEGL_nvidia is the working ICD on this host.
export VK_ICD_FILENAMES="${project_dir}/scripts/nvidia_icd_egl.json"
export VK_DRIVER_FILES="${VK_ICD_FILENAMES}"
export VK_LOADER_LAYERS_DISABLE="VK_LAYER_MESA_device_select"
export __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
export NVIDIA_DRIVER_CAPABILITIES="${NVIDIA_DRIVER_CAPABILITIES:-all}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-cudacycle}"
mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}" || true

export OVRTX_USD_URL="${project_dir}/assets/cudacycle_visual.usda"
exec "${python_bin}" "${project_dir}/server/ovrtx_server.py" --port 8791 --auto-start "$@"
