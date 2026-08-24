import { useState } from "react";
import { useTwin } from "./useTwin";
import { UsdStage } from "./UsdStage";
import {
  BUILD_STEPS,
  FINISHES,
  LIGHT_LABEL,
  PALETTE,
  RIDERS,
  type BuildStep,
  type TwinState,
} from "./types";

const initial: TwinState = {
  page: "build",
  finish: "black",
  color: "blue",
  rider: "agibot",
  camera: "hero",
  zoom: 1,
  build: "rider",
  riding: false,
};

const CAMERAS: { id: TwinState["camera"]; label: string }[] = [
  { id: "hero", label: "Overview" },
  { id: "chase", label: "Follow" },
  { id: "cockpit", label: "Cabin" },
];

const NEXT: Record<BuildStep, BuildStep | "ride"> = {
  rider: "light",
  light: "finish",
  finish: "ride",
};

function metric(value: number | null, digits = 0) {
  if (value == null || Number.isNaN(value)) return "—";
  return digits ? value.toFixed(digits) : Math.round(value).toLocaleString();
}

export default function App() {
  const [state, setState] = useState<TwinState>(initial);
  const twin = useTwin(state);
  const building = state.page === "build";
  const finish = FINISHES.find((f) => f.id === state.finish);
  const wear = twin.physx ? twin.wear : null;
  const speed = twin.physx ? twin.speed : null;
  const rpm = twin.physx ? twin.rpm : null;
  const rul = twin.physx ? twin.rul * 100 : null;
  const motor = twin.physx && speed != null && wear != null ? 48 + speed * 0.32 + wear * 22 : null;
  const load = twin.physx && speed != null ? 8 + speed * 0.18 + (state.riding ? 12 : 0) : null;
  const alert = wear != null && wear > 0.72;

  const goNext = () => {
    const next = NEXT[state.build];
    if (next === "ride") {
      setState((s) => ({ ...s, page: "ride", camera: "hero", riding: false }));
      return;
    }
    setState((s) => ({ ...s, build: next }));
  };

  return (
    <div className="app">
      <UsdStage live={twin.live} error={twin.error} runtimeState={twin.runtimeState} />
      <div className="hud">
        <header className="top">
          <div className="wordmark">
            Cudacycle
            {twin.live && <span className="usd-live">ovrtx</span>}
            {twin.physx && (
              <span className={`usd-live ${state.riding ? "" : "idle"}`.trim()}>ovphysx</span>
            )}
          </div>
          {building && (
            <button className="pill" onClick={goNext}>
              {state.build === "finish" ? "Go to ride" : "Next"}
            </button>
          )}
          {!building && (
            <>
              <button
                className="pill"
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    page: "build",
                    riding: false,
                    camera: "hero",
                    build: "rider",
                  }))
                }
              >
                Design
              </button>
              <nav className="pills">
                {CAMERAS.map((cam) => (
                  <button
                    key={cam.id}
                    className={`pill ${state.camera === cam.id ? "active" : ""}`}
                    onClick={() => setState((s) => ({ ...s, camera: cam.id }))}
                  >
                    {cam.label}
                  </button>
                ))}
              </nav>
              <button
                className={`cta ${state.riding ? "stop" : ""}`}
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    riding: !s.riding,
                    camera: s.riding ? "hero" : "chase",
                  }))
                }
              >
                {state.riding ? "Stop" : "Launch ride"}
              </button>
            </>
          )}
        </header>

        {building && (
          <nav className="steps">
            {BUILD_STEPS.map((s, i) => (
              <button
                key={s.id}
                className={`step ${state.build === s.id ? "active" : ""}`}
                onClick={() => setState((st) => ({ ...st, build: s.id }))}
              >
                <span className="n">0{i + 1}</span>
                {s.label}
              </button>
            ))}
          </nav>
        )}

        {building && (
          <div className="chip">
            <span>
              {state.rider === "agibot" ? "AGIBOT" : "GALBOT"} · {LIGHT_LABEL[state.color]} · {finish?.label}
            </span>
          </div>
        )}

        {!building && (
          <aside className="card metrics">
            <label>
              Condition
              <span>{!twin.physx ? "Waiting" : alert ? "Service" : "Nominal"}</span>
            </label>
            <div className="metric">
              <span>Wheel speed</span>
              <span>{rpm == null ? "—" : `${metric(rpm)} rpm`}</span>
              <div className="bar">
                <i style={{ width: `${rpm == null ? 0 : Math.min(100, (rpm / 7000) * 100)}%` }} />
              </div>
            </div>
            <div className="metric">
              <span>Motor temp</span>
              <span>{motor == null ? "—" : `${metric(motor)}°`}</span>
              <div className={`bar ${motor != null && motor > 85 ? "warn" : ""}`}>
                <i style={{ width: `${motor == null ? 0 : Math.min(100, motor)}%` }} />
              </div>
            </div>
            <div className="metric">
              <span>Chassis load</span>
              <span>{load == null ? "—" : `${metric(load)}%`}</span>
              <div className="bar">
                <i style={{ width: `${load == null ? 0 : Math.min(100, load)}%` }} />
              </div>
            </div>
            <div className="metric">
              <span>Remaining life</span>
              <span>{rul == null ? "—" : `${metric(rul)}%`}</span>
              <div className={`bar ${alert ? "alert" : wear != null && wear > 0.45 ? "warn" : ""}`}>
                <i style={{ width: `${rul ?? 0}%`, background: PALETTE[state.color] }} />
              </div>
            </div>
            <p className={`status ${alert ? "hot" : ""}`}>
              {!twin.physx
                ? "Waiting for ovphysx."
                : alert
                  ? "Service recommended after this run."
                  : "Operating within expected load."}
            </p>
          </aside>
        )}

        {building && (
          <aside className="card">
            {state.build === "finish" && (
              <>
                <label>
                  Finish
                  <span>{finish?.label}</span>
                </label>
                <div className="swatches">
                  {FINISHES.map((f) => (
                    <button
                      key={f.id}
                      className={`swatch ${f.id} ${state.finish === f.id ? "active" : ""}`}
                      style={f.id === "black" ? { background: f.swatch } : undefined}
                      aria-label={f.label}
                      onClick={() => setState((s) => ({ ...s, finish: f.id }))}
                    />
                  ))}
                </div>
              </>
            )}
            {state.build === "light" && (
              <>
                <label>
                  Light
                  <span>{LIGHT_LABEL[state.color]}</span>
                </label>
                <div className="swatches">
                  {(["blue", "magenta", "yellow"] as const).map((c) => (
                    <button
                      key={c}
                      className={`swatch ${state.color === c ? "active" : ""}`}
                      style={{ background: PALETTE[c] }}
                      aria-label={LIGHT_LABEL[c]}
                      onClick={() => setState((s) => ({ ...s, color: c }))}
                    />
                  ))}
                </div>
              </>
            )}
            {state.build === "rider" && (
              <>
                <label>
                  Rider
                  <span>{state.rider === "agibot" ? "AGIBOT" : "GALBOT"}</span>
                </label>
                <div className="pills tight">
                  {RIDERS.map((r) => (
                    <button
                      key={r.id}
                      className={`pill ${state.rider === r.id ? "active" : ""}`}
                      onClick={() => setState((s) => ({ ...s, rider: r.id }))}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
