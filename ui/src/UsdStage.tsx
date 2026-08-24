import { useEffect, useState } from "react";

export function UsdStage({
  live,
  error,
  runtimeState,
}: {
  live: boolean;
  error?: string;
  runtimeState?: string;
}) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 250);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="viewport stage">
      <img
        className="stage-frame"
        src={`/api/frame.jpg?t=${tick}`}
        alt="Cudacycle OpenUSD stage"
      />
      {!live && (
        <div className="stage-wait">
          <p>ovrtx</p>
          <span>{error || `Waiting for a frame from ovrtx (${runtimeState || "connecting"}).`}</span>
        </div>
      )}
    </div>
  );
}
