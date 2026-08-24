#!/usr/bin/env bash
# Isolated ovphysx venv. Do not install ovphysx into the ovrtx .venv.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_version="${CUDACYCLE_PYTHON_VERSION:-3.10}"
uv_bin="${HOME}/.local/bin/uv"

cd "${project_dir}"

if [[ ! -x "${uv_bin}" ]]; then
  python3 -m pip install --user uv
fi

"${uv_bin}" python install "${python_version}"
if [[ ! -x .venv-physx/bin/python ]]; then
  "${uv_bin}" venv --python "${python_version}" .venv-physx
fi
"${uv_bin}" pip install --python .venv-physx/bin/python \
  ovphysx==0.5.9 \
  ovstage==0.1.0.346039 \
  numpy==2.2.6

echo "ovphysx venv ready. Start with: bash scripts/start_physics_server.sh"
