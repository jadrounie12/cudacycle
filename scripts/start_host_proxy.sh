#!/usr/bin/env bash
# Run on ubuntu@brev (host SSH), not in noVNC.
# Brev port-forward hits the host. The RTX server listens on
# 127.0.0.1:8791 inside the Isaac container. This publishes that
# onto the host loopback only (not the public EC2 interface).
set -euo pipefail

container="${CUDACYCLE_CONTAINER:-isaac-lab-ex-ros2-isaac-sim-ex-1}"
listen_host="${CUDACYCLE_PROXY_HOST:-127.0.0.1}"
listen_port="${CUDACYCLE_PROXY_PORT:-8791}"
side_port="${CUDACYCLE_SIDE_PORT:-8792}"
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sidecar="${project_dir}/scripts/container_loopback_sidecar.py"

if ! command -v docker >/dev/null 2>&1; then
  echo "Run this on the Brev host (ubuntu@brev), where docker exists." >&2
  exit 1
fi

if ! docker inspect "${container}" >/dev/null 2>&1; then
  echo "Container ${container} is not running." >&2
  exit 1
fi

if [[ ! -f "${sidecar}" ]]; then
  echo "Missing ${sidecar}" >&2
  exit 1
fi

container_ip="$(docker inspect "${container}" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
if [[ -z "${container_ip}" ]]; then
  echo "Could not read container IP for ${container}." >&2
  exit 1
fi

container_root="${CUDACYCLE_CONTAINER_ROOT:-/workspace}"
sidecar_in_container="${container_root}${project_dir}/scripts/container_loopback_sidecar.py"
docker exec -d "${container}" python3 "${sidecar_in_container}" "${side_port}"
echo "Container sidecar :${side_port} -> 127.0.0.1:8791"
echo "Host proxy ${listen_host}:${listen_port} -> ${container_ip}:${side_port}"

exec python3 - "${listen_host}" "${listen_port}" "${container_ip}" "${side_port}" <<'PY'
import socket
import sys
import threading

listen_host, listen_port, dest_host, dest_port = (
    sys.argv[1],
    int(sys.argv[2]),
    sys.argv[3],
    int(sys.argv[4]),
)
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((listen_host, listen_port))
server.listen(64)
print(f"listening {listen_host}:{listen_port}", flush=True)


def pump(src, dst):
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


while True:
    client, _ = server.accept()
    try:
        upstream = socket.create_connection((dest_host, dest_port), timeout=5)
    except OSError:
        client.close()
        continue
    threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pump, args=(upstream, client), daemon=True).start()
PY
