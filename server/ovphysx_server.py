#!/usr/bin/env python3
"""Localhost ovphysx server: ride wear from a wheel-on-rail proxy.

Binds 127.0.0.1 only. Separate venv from ovrtx. Port 8793 so it does not
collide with the container sidecar on 8792.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np
import ovstage
from ovphysx import PhysX
from ovphysx.types import TensorType

HOST = "127.0.0.1"
PORT = int(os.getenv("CUDACYCLE_PHYSX_PORT", "8793"))
SCENE = Path(os.getenv("CUDACYCLE_PHYSX_USD", Path(__file__).resolve().parent.parent / "assets" / "cudacycle_physics.usda"))
WHEEL_R = 0.32
DT = 1.0 / 60.0
DRIVE_OMEGA = 28.0
WEAR_PER_SEC = 0.018


class PhysicsWorker:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = "idle"
        self.error: str | None = None
        self.riding = False
        self.omega = 0.0
        self.speed = 0.0
        self.wear = 0.18
        self.step_index = 0
        self.fps = 0.0

    def start(self) -> None:
        with self.condition:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.state = "starting"
            self.error = None
            self.thread = threading.Thread(target=self._run, name="cudacycle-ovphysx", daemon=True)
            self.thread.start()

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.condition:
            if "riding" in payload:
                self.riding = bool(payload["riding"])
            if payload.get("reset"):
                self.wear = 0.18
                self.omega = 0.0
                self.speed = 0.0
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.condition:
            live = self.state == "running"
            return {
                "live": live,
                "engine": "ovphysx",
                "state": self.state,
                "error": self.error,
                "scene": str(SCENE),
                "fps": round(self.fps, 1),
                "step_index": self.step_index,
                "riding": self.riding,
                "omega": round(self.omega, 3),
                "speed": round(self.speed, 1),
                "rpm": int(abs(self.omega) * 60.0 / (2.0 * np.pi)),
                "wear": self.wear,
                "rul": max(0.0, 1.0 - self.wear),
            }

    def _run(self) -> None:
        PhysX.set_cpu_mode(True)
        physx = PhysX()
        stage = ovstage.Stage("cudacycle-physics")
        bindings: list[Any] = []
        try:
            with self.condition:
                self.state = "loading"
            ovstage.population.open_usd(
                stage,
                str(SCENE),
                ordinal=1,
                domains=ovstage.PopulationDomain.ALL,
            )
            stage.advance_write_floor(1).wait()
            physx.attach_ovstage(stage, read_ordinal=1)
            physx.wait_all()

            velocity = physx.create_tensor_binding(
                pattern="/World/Wheel",
                tensor_type=TensorType.RIGID_BODY_VELOCITY,
            )
            bindings.append(velocity)
            if velocity.count != 1:
                raise RuntimeError(f"Wheel velocity binding count={velocity.count}")

            vel = np.zeros(velocity.shape, dtype=np.float32)
            sample_start = time.monotonic()
            sample_steps = 0

            with self.condition:
                self.state = "running"

            while not self.stop_event.is_set():
                frame_start = time.monotonic()
                with self.condition:
                    riding = self.riding
                target = DRIVE_OMEGA if riding else 0.0
                velocity.write(np.asarray([[0.0, 0.0, 0.0, 0.0, 0.0, target]], dtype=np.float32))
                physx.step_sync(DT)
                velocity.read(vel)
                omega = float(vel[0, 5])
                speed = 118.0 if riding else 0.0
                with self.condition:
                    self.omega = omega
                    self.speed = speed
                    if riding:
                        self.wear = min(1.0, self.wear + DT * WEAR_PER_SEC * (abs(omega) / max(DRIVE_OMEGA, 1e-3)))
                    self.step_index += 1
                    self.condition.notify_all()
                sample_steps += 1
                elapsed = time.monotonic() - sample_start
                if elapsed >= 1.0:
                    self.fps = sample_steps / elapsed
                    sample_start = time.monotonic()
                    sample_steps = 0
                remaining = DT - (time.monotonic() - frame_start)
                if remaining > 0:
                    time.sleep(remaining)
        except Exception as exc:
            with self.condition:
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                self.condition.notify_all()
            print(f"[cudacycle] ovphysx failed: {self.error}", flush=True)
        finally:
            for binding in bindings:
                try:
                    binding.destroy()
                except Exception:
                    pass
            try:
                physx.detach_ovstage()
            except Exception:
                pass
            stage.destroy()
            physx.release()
            with self.condition:
                if self.state != "error":
                    self.state = "stopped"


WORKER = PhysicsWorker()


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/status":
            self._send_json(WORKER.status())
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/api/control", "/control"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._send_json({"ok": True, **WORKER.update(payload)})
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        self.send_error(404)

    def log_message(self, *_: Any) -> None:
        return


def main() -> None:
    WORKER.start()
    print(f"Cudacycle ovphysx server http://{HOST}:{PORT}")
    print(json.dumps(WORKER.status(), indent=2))
    try:
        ThreadingHTTPServer((HOST, PORT), ApiHandler).serve_forever()
    except KeyboardInterrupt:
        WORKER.stop_event.set()


if __name__ == "__main__":
    main()
