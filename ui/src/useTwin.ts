import { useEffect, useRef, useState } from "react";
import type { TwinState } from "./types";

export type TwinLive = {
  live: boolean;
  physx: boolean;
  gpu?: string;
  error?: string;
  stage?: string;
  runtimeState?: string;
  rpm: number;
  wear: number;
  speed: number;
  rul: number;
};

export function useTwin(state: TwinState): TwinLive {
  const [live, setLive] = useState(false);
  const [physx, setPhysx] = useState(false);
  const [gpu, setGpu] = useState<string | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [stage, setStage] = useState<string | undefined>();
  const [runtimeState, setRuntimeState] = useState<string | undefined>();
  const [telem, setTelem] = useState({ rpm: 0, wear: 0, speed: 0, rul: 1 });
  const lastControl = useRef("");

  useEffect(() => {
    let active = true;
    const tick = async () => {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        const status = await response.json();
        if (!active) return;
        setLive(Boolean(status.hasFrame || (status.live && status.runtime?.state === "rendering")));
        setGpu(status.gpu?.name);
        setError(status.runtime?.error);
        setStage(status.stage);
        setRuntimeState(status.runtime?.state);
        if (status.runtime?.state === "idle" || status.runtime?.state === "stopped") {
          await fetch("/api/render/start", { method: "POST" });
        }
      } catch {
        if (!active) return;
        setLive(false);
        setError(undefined);
        setRuntimeState("connecting");
      }

      try {
        const physRes = await fetch("/physics/api/status", { cache: "no-store" });
        const physics = physRes.ok ? await physRes.json() : null;
        if (!active) return;
        const physxLive = Boolean(physics && (physics.live || physics.state === "running"));
        setPhysx(physxLive);
        if (physxLive && typeof physics?.wear === "number") {
          setTelem({
            rpm: physics.rpm ?? 0,
            wear: physics.wear,
            speed: physics.speed ?? 0,
            rul: physics.rul ?? Math.max(0, 1 - physics.wear),
          });
        }
      } catch {
        if (!active) return;
        setPhysx(false);
      }
    };
    void tick();
    const id = window.setInterval(tick, 1000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    const body = {
      finish: state.finish,
      color: state.color,
      rider: state.rider,
      camera: state.camera,
      zoom: Number(state.zoom.toFixed(3)),
      riding: state.riding,
      page: state.page,
      build: state.build,
    };
    const key = JSON.stringify(body);
    if (key === lastControl.current) return;
    lastControl.current = key;
    void fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => {});
    void fetch("/physics/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ riding: state.riding }),
    }).catch(() => {});
  }, [state.finish, state.color, state.rider, state.camera, state.zoom, state.riding, state.page, state.build]);

  return { live, physx, gpu, error, stage, runtimeState, ...telem };
}
