#!/usr/bin/env python3
"""Localhost RTX server: load the Cudacycle USDA, stream frames, apply UI control."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib.metadata
import importlib.util
import io
import json
import math
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Track path for the live ride. The USDA is the scene; this only moves the cycle.
RIDE_T = 0.18
TRACK_A, TRACK_B = 13.5, 8.5


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a):
    return math.sqrt(dot(a, a))


def norm(a):
    L = length(a)
    return (0.0, 1.0, 0.0) if L < 1e-9 else mul(a, 1.0 / L)


def track_height(angle: float) -> float:
    y = 1.85 + 0.72 * math.sin(angle - 0.55) + 0.32 * math.sin(2 * angle + 0.4)
    return max(1.15, y)


def track_point(t: float):
    a = t * math.pi * 2
    return (math.cos(a) * TRACK_A, track_height(a), math.sin(a) * TRACK_B)


def ride_xform(t: float):
    p = track_point(t)
    tangent = norm(sub(track_point((t + 0.002) % 1.0), p))
    right = cross(tangent, (0.0, 1.0, 0.0))
    right = (1.0, 0.0, 0.0) if length(right) < 1e-6 else norm(right)
    up = norm(cross(right, tangent))
    return p, tangent, right, up

HOST = "127.0.0.1"
PORT = 8791
DEFAULT_USD = str(ROOT / "assets" / "cudacycle_visual.usda")
DEFAULT_PRODUCT = os.getenv("OVRTX_RENDER_PRODUCT", "/Render/Camera")
FINISH = {
    "black": ((0.031, 0.031, 0.039), 0.35, 0.22),
    "chrome": ((0.706, 0.737, 0.769), 0.82, 0.32),
    "carbon": ((0.431, 0.384, 0.337), 0.22, 0.52),
}
LIGHT = {
    "blue": (0.239, 0.902, 1.0),
    "magenta": (1.0, 0.310, 0.639),
    "yellow": (1.0, 0.882, 0.290),
}
RIDER = {
    "agibot": {
        "RidePlate": ((0.945, 0.953, 0.965), 0.08, 0.32),
        "RideJoint": ((0.102, 0.110, 0.125), 0.62, 0.38),
        "RideHead": ((0.043, 0.047, 0.055), 0.72, 0.22),
    },
    "galbot": {
        "RidePlate": ((0.925, 0.910, 0.886), 0.08, 0.32),
        "RideJoint": ((0.773, 0.800, 0.827), 0.62, 0.38),
        "RideHead": ((0.925, 0.910, 0.886), 0.08, 0.32),
    },
}


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def gpu_diagnostics() -> dict[str, Any]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            text=True,
            timeout=4,
        )
        name, memory = [part.strip() for part in out.split(",", 1)]
        return {"ready": True, "name": name, "memory": memory}
    except Exception as exc:
        return {"ready": False, "error": str(exc)}


def look_matrix(np, eye, target, up=(0.0, 1.0, 0.0)):
    position = np.asarray(eye, dtype=np.float64)
    forward = np.asarray(target, dtype=np.float64) - position
    forward /= np.linalg.norm(forward)
    world_up = np.asarray(up, dtype=np.float64)
    right = np.cross(forward, world_up)
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    matrix = np.eye(4, dtype=np.float64)
    matrix[0, 0:3] = right
    matrix[1, 0:3] = true_up
    matrix[2, 0:3] = -forward
    matrix[3, 0:3] = position
    return matrix


def basis_matrix(np, origin, right, up, fwd):
    matrix = np.eye(4, dtype=np.float64)
    matrix[0, 0:3] = right
    matrix[1, 0:3] = up
    matrix[2, 0:3] = fwd
    matrix[3, 0:3] = origin
    return matrix


def hidden_matrix(np):
    return basis_matrix(np, (0.0, -80.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def origin_matrix(np, origin=(0.0, 0.0, 0.0)):
    return basis_matrix(np, origin, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class RendererWorker:
    def __init__(self):
        self.usd_url = os.getenv("OVRTX_USD_URL", DEFAULT_USD)
        self.render_product = os.getenv("OVRTX_RENDER_PRODUCT", DEFAULT_PRODUCT)
        self.jpeg_quality = max(1, min(95, int(os.getenv("OVRTX_JPEG_QUALITY", "86"))))
        self.condition = threading.Condition()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.latest_frame: bytes | None = None
        self.frame_index = 0
        self.fps = 0.0
        self.state = "idle"
        self.last_error: str | None = None
        self.progress = RIDE_T
        self.controls = {
            "finish": "black",
            "color": "blue",
            "rider": "agibot",
            "camera": "hero",
            "zoom": 1.0,
            "riding": False,
            "page": "build",
            "build": "rider",
        }

    def status(self) -> dict[str, Any]:
        wear = min(1.0, 0.18 + (self.progress - RIDE_T) % 1.0)
        speed = 118.0 if self.controls["riding"] else 0.0
        with self.condition:
            live = self.state == "rendering" and self.latest_frame is not None
            runtime = {
                "state": self.state,
                "frame_index": self.frame_index,
                "fps": round(self.fps, 1),
                "error": self.last_error,
                "scene": self.usd_url,
                "render_product": self.render_product,
            }
        return {
            "live": live,
            "ovrtx_available": importlib.util.find_spec("ovrtx") is not None,
            "ovrtx_version": package_version("ovrtx"),
            "ovstage_version": package_version("ovstage"),
            "gpu": gpu_diagnostics(),
            "runtime": runtime,
            "finish": self.controls["finish"],
            "color": self.controls["color"],
            "rider": self.controls["rider"],
            "camera": self.controls["camera"],
            "riding": self.controls["riding"],
            "rpm": int(speed * 48),
            "wear": wear,
            "speed": speed,
            "rul": max(0.0, 1.0 - wear),
        }

    def start(self):
        with self.condition:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.latest_frame = None
            self.frame_index = 0
            self.last_error = None
            self.state = "starting"
            self.thread = threading.Thread(target=self._render_loop, daemon=True)
            self.thread.start()

    def update_controls(self, payload: dict[str, Any]):
        with self.condition:
            for key in self.controls:
                if key not in payload:
                    continue
                if key == "zoom":
                    self.controls[key] = max(0.0, min(1.0, float(payload[key])))
                else:
                    self.controls[key] = payload[key]
            if self.controls["page"] == "build":
                self.controls["riding"] = False
                self.progress = RIDE_T
            return dict(self.controls)

    def _write_vec3(self, stage, ovstage, paths, query, token, rgb, ordinal, np):
        value = np.asarray([rgb], dtype=np.float32)
        stage.write_attribute(
            query,
            paths.intern_token(token),
            ordinal=ordinal,
            tensors=ovstage.make_dltensor(
                value,
                dtype=ovstage.numpy_to_dldatatype(value.dtype, lanes=3),
                shape=[1],
                ndim=1,
            ),
            is_array=False,
        ).wait()

    def _write_float(self, stage, ovstage, paths, query, token, number, ordinal, np):
        value = np.asarray([number], dtype=np.float32)
        stage.write_attribute(
            query,
            paths.intern_token(token),
            ordinal=ordinal,
            tensors=ovstage.make_dltensor(
                value,
                dtype=ovstage.numpy_to_dldatatype(value.dtype, lanes=1),
                shape=[1],
                ndim=1,
            ),
            is_array=False,
        ).wait()

    def _write_matrix(self, stage, ovstage, paths, query, matrix, ordinal, np):
        value = np.asarray(matrix, dtype=np.float64).reshape(1, 4, 4)
        stage.write_attribute(
            query,
            paths.intern_token("omni:xform"),
            ordinal=ordinal,
            tensors=ovstage.make_dltensor(
                value,
                dtype=ovstage.numpy_to_dldatatype(value.dtype, lanes=16),
                shape=[1],
                ndim=1,
            ),
            is_array=False,
            semantic=ovstage.AttributeSemantic.MATRIX,
        ).wait()

    def _camera_matrix(self, np, controls):
        p, tangent, right, up = ride_xform(self.progress)
        z = mul(tangent, -1.0)
        if controls["page"] == "build":
            if controls["build"] == "rider":
                return look_matrix(np, (1.55, 1.48, 2.45), (0.0, 0.95, 0.0))
            eye = add(p, {"finish": (2.35, 1.15, 2.15), "light": (2.15, 1.25, 2.35)}[controls["build"]])
            return look_matrix(np, eye, add(p, (0.0, 0.4, 0.0)))
        if controls["camera"] == "aerial":
            t = max(0.0, min(1.0, float(controls.get("zoom", 0.0))))
            s = t * t * (3.0 - 2.0 * t)
            eye = (
                0.0 + (7.5 - 0.0) * s,
                52.0 + (2.6 - 52.0) * s,
                96.0 + (13.0 - 96.0) * s,
            )
            tgt = (
                0.0,
                12.0 + (2.1 - 12.0) * s,
                0.0,
            )
            return look_matrix(np, eye, tgt)
        if controls["camera"] == "chase":
            eye = add(p, add(mul(up, 1.55), mul(z, 5.2)))
            tgt = add(p, add(mul(up, 0.5), mul(z, -1.4)))
            return look_matrix(np, eye, tgt, up)
        if controls["camera"] == "cockpit":
            eye = add(p, add(mul(up, 0.88), mul(z, -0.12)))
            tgt = add(p, add(mul(up, 0.52), mul(z, -2.8)))
            return look_matrix(np, eye, tgt, up)
        return look_matrix(np, (7.5, 2.6, 13.0), (0.0, 2.1, 0.0))

    def _cycle_matrix(self, np, offset):
        p, tangent, right, up = ride_xform((self.progress + offset) % 1.0)
        return basis_matrix(np, p, right, up, mul(tangent, -1.0))

    def _publish_products(self, products, np, Image) -> bool:
        import ovrtx

        encoded = None
        for product in products.values():
            for frame in product.frames:
                mapped = frame.render_vars["LdrColor"].map(device=ovrtx.Device.CPU)
                pixels = np.from_dlpack(mapped).copy()
                mapped.unmap()
                buf = io.BytesIO()
                Image.fromarray(pixels.astype("uint8")).convert("RGB").save(
                    buf, format="JPEG", quality=self.jpeg_quality
                )
                encoded = buf.getvalue()
        if not encoded:
            return False
        with self.condition:
            self.latest_frame = encoded
            self.frame_index += 1
            self.state = "rendering"
            self.condition.notify_all()
        return True

    def _render_loop(self):
        try:
            import numpy as np
            import ovrtx
            import ovstage
            from PIL import Image

            with self.condition:
                self.state = "loading-scene"
            print("[cudacycle] creating ovrtx.Renderer", flush=True)
            renderer = ovrtx.Renderer()
            print("[cudacycle] renderer ready, opening USDA", flush=True)
            with self.condition:
                self.state = "opening-usd"
            stage = ovstage.Stage("cudacycle.rtx")
            renderer.attach_ovstage(stage)
            ordinal = 1
            ovstage.population.open_usd(stage, self.usd_url, ordinal=ordinal)
            stage.advance_write_floor(ordinal, ovstage.Scope.ALL).wait()
            print("[cudacycle] USDA loaded, stepping", flush=True)
            with self.condition:
                self.state = "first-frame"
            products = renderer.step(
                render_products={self.render_product},
                delta_time=1.0 / 30.0,
                ordinal=ordinal,
            )
            print(f"[cudacycle] first step keys={list(products)}", flush=True)
            self._publish_products(products, np, Image)

            with ovstage.PathDictionary(stage) as paths:
                camera_q = stage.query_from_path_list(
                    paths.create_path_list_from_strings(["/World/Cameras/Live"])
                )
                cycle_q = stage.query_from_path_list(
                    paths.create_path_list_from_strings(["/World/Cudacycle"])
                )
                a_q = stage.query_from_path_list(
                    paths.create_path_list_from_strings(["/World/CompanionA"])
                )
                b_q = stage.query_from_path_list(
                    paths.create_path_list_from_strings(["/World/CompanionB"])
                )
                plaza_q = stage.query_from_path_list(
                    paths.create_path_list_from_strings(["/World/Plaza"])
                )
                studio_q = stage.query_from_path_list(
                    paths.create_path_list_from_strings(["/World/StudioHumanoid"])
                )
                shaders = {
                    name: stage.query_from_path_list(
                        paths.create_path_list_from_strings([f"/World/Looks/{name}/Shader"])
                    )
                    for name in (
                        "FinishBlack",
                        "LightBlue",
                        "LightBlueSoft",
                        "RidePlate",
                        "RideJoint",
                        "RideHead",
                    )
                }
                with ExitStack() as stack:
                    stack.enter_context(camera_q)
                    stack.enter_context(cycle_q)
                    stack.enter_context(a_q)
                    stack.enter_context(b_q)
                    stack.enter_context(plaza_q)
                    stack.enter_context(studio_q)
                    for query in shaders.values():
                        stack.enter_context(query)
                    last = time.monotonic()
                    sample_start = last
                    sample_frames = 0
                    while not self.stop_event.is_set():
                        now = time.monotonic()
                        dt = min(0.05, now - last)
                        last = now
                        with self.condition:
                            controls = dict(self.controls)
                            if controls["riding"]:
                                self.progress = (self.progress + dt * 0.12) % 1.0
                            progress = self.progress
                        ordinal += 1
                        finish = FINISH[controls["finish"]]
                        light = LIGHT[controls["color"]]
                        rider = RIDER[controls["rider"]]
                        self._write_vec3(
                            stage, ovstage, paths, shaders["FinishBlack"], "inputs:diffuse_color_constant", finish[0], ordinal, np
                        )
                        self._write_float(
                            stage, ovstage, paths, shaders["FinishBlack"], "inputs:metallic_constant", finish[1], ordinal, np
                        )
                        self._write_float(
                            stage, ovstage, paths, shaders["FinishBlack"], "inputs:reflection_roughness_constant", finish[2], ordinal, np
                        )
                        for name in ("LightBlue", "LightBlueSoft"):
                            self._write_vec3(
                                stage, ovstage, paths, shaders[name], "inputs:diffuse_color_constant", light, ordinal, np
                            )
                            self._write_vec3(
                                stage, ovstage, paths, shaders[name], "inputs:emissive_color", light, ordinal, np
                            )
                        for name, spec in rider.items():
                            self._write_vec3(
                                stage, ovstage, paths, shaders[name], "inputs:diffuse_color_constant", spec[0], ordinal, np
                            )
                            self._write_float(
                                stage, ovstage, paths, shaders[name], "inputs:metallic_constant", spec[1], ordinal, np
                            )
                            self._write_float(
                                stage, ovstage, paths, shaders[name], "inputs:reflection_roughness_constant", spec[2], ordinal, np
                            )
                        self._write_matrix(stage, ovstage, paths, camera_q, self._camera_matrix(np, controls), ordinal, np)
                        rider_studio = controls["page"] == "build" and controls["build"] == "rider"
                        if rider_studio:
                            parked = hidden_matrix(np)
                            self._write_matrix(stage, ovstage, paths, cycle_q, parked, ordinal, np)
                            self._write_matrix(stage, ovstage, paths, a_q, parked, ordinal, np)
                            self._write_matrix(stage, ovstage, paths, b_q, parked, ordinal, np)
                            self._write_matrix(stage, ovstage, paths, plaza_q, parked, ordinal, np)
                            self._write_matrix(stage, ovstage, paths, studio_q, origin_matrix(np), ordinal, np)
                        else:
                            self._write_matrix(stage, ovstage, paths, cycle_q, self._cycle_matrix(np, 0.0), ordinal, np)
                            self._write_matrix(stage, ovstage, paths, a_q, self._cycle_matrix(np, 0.14), ordinal, np)
                            self._write_matrix(stage, ovstage, paths, b_q, self._cycle_matrix(np, 0.28), ordinal, np)
                            self._write_matrix(stage, ovstage, paths, plaza_q, origin_matrix(np), ordinal, np)
                            self._write_matrix(stage, ovstage, paths, studio_q, hidden_matrix(np), ordinal, np)
                        stage.advance_write_floor(ordinal, ovstage.Scope.ALL).wait()
                        products = renderer.step(
                            render_products={self.render_product},
                            delta_time=1.0 / 30.0,
                            ordinal=ordinal,
                        )
                        if self._publish_products(products, np, Image):
                            sample_frames += 1
                            elapsed = now - sample_start
                            if elapsed >= 1:
                                self.fps = sample_frames / elapsed
                                sample_start = now
                                sample_frames = 0
                            with self.condition:
                                self.progress = progress
        except Exception as exc:
            with self.condition:
                self.state = "error"
                self.last_error = str(exc)
                self.condition.notify_all()
            print(f"[cudacycle] RTX server failed: {exc}", flush=True)


WORKER = RendererWorker()


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, value: Any, status: int = 200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            self._send_json(WORKER.status())
            return
        if path in ("/api/frame.jpg", "/frame.jpg"):
            with WORKER.condition:
                frame = WORKER.latest_frame
            if not frame:
                self._send_json({"error": "No RTX frame yet"}, 503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return
        if path == "/api/stream.mjpg":
            self._stream()
            return
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/render/start", "/api/render/pause", "/api/render/stop"):
            if path.endswith("start"):
                WORKER.start()
            self._send_json(WORKER.status(), 202)
            return
        if path in ("/api/control", "/control"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._send_json({"ok": True, "controls": WORKER.update_controls(payload)})
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        self.send_error(404)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=ovxframe")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        seen = -1
        try:
            while True:
                with WORKER.condition:
                    WORKER.condition.wait_for(
                        lambda: WORKER.frame_index != seen or WORKER.state in {"error", "stopped"},
                        timeout=2,
                    )
                    frame = WORKER.latest_frame
                    seen = WORKER.frame_index
                    terminal = WORKER.state in {"error", "stopped"}
                if frame:
                    self.wfile.write(
                        b"--ovxframe\r\nContent-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                    )
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                if terminal:
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, *_args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--auto-start", action="store_true")
    args = parser.parse_args()
    if args.auto_start:
        WORKER.start()
    print(f"Cudacycle RTX server http://{args.host}:{args.port}")
    print(json.dumps(WORKER.status(), indent=2))
    try:
        ThreadingHTTPServer((args.host, args.port), ApiHandler).serve_forever()
    except KeyboardInterrupt:
        WORKER.stop_event.set()


if __name__ == "__main__":
    main()
