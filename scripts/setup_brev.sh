#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_version="${CUDACYCLE_PYTHON_VERSION:-3.10}"
uv_bin="${HOME}/.local/bin/uv"

cd "${project_dir}"

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi was not found. Run this on the GPU host, not inside Isaac." >&2
  exit 1
fi

if [[ ! -e /usr/lib/x86_64-linux-gnu/libOpenGL.so.0 || ! -e /usr/lib/x86_64-linux-gnu/libvulkan.so.1 ]]; then
  echo "Installing host OpenGL/Vulkan loader so ovrtx can talk to the NVIDIA driver..."
  sudo apt-get update -y
  sudo apt-get install -y libopengl0 libgl1 libegl1 libvulkan1
fi

if [[ ! -x "${uv_bin}" ]]; then
  python3 -m pip install --user uv
fi

"${uv_bin}" python install "${python_version}"

if [[ ! -x .venv/bin/python ]]; then
  "${uv_bin}" venv --python "${python_version}" .venv
fi

"${uv_bin}" pip install --python .venv/bin/python \
  ovrtx==0.4.0.346409 \
  ovstage==0.1.0.346039 \
  pillow==12.3.0 \
  numpy==2.2.6

echo
echo "Setup complete. Start the renderer with: bash scripts/start_gpu_server.sh"
