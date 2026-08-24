export type Finish = "black" | "chrome" | "carbon";
export type LightColor = "blue" | "magenta" | "yellow";
export type RiderType = "agibot" | "galbot";
export type CameraMode = "hero" | "chase" | "cockpit" | "aerial";
export type BuildStep = "finish" | "light" | "rider";
export type Page = "build" | "ride";

export const BUILD_STEPS: { id: BuildStep; label: string }[] = [
  { id: "rider", label: "Rider" },
  { id: "light", label: "Light" },
  { id: "finish", label: "Finish" },
];

export const FINISHES: { id: Finish; label: string; swatch: string }[] = [
  { id: "black", label: "Black", swatch: "#111214" },
  { id: "chrome", label: "Chrome", swatch: "#9aa3ab" },
  { id: "carbon", label: "Carbon", swatch: "#5a4e42" },
];

export const PALETTE: Record<LightColor, string> = {
  blue: "#3de6ff",
  magenta: "#ff4fa3",
  yellow: "#ffe14a",
};

export const LIGHT_LABEL: Record<LightColor, string> = {
  blue: "Blue",
  magenta: "Magenta",
  yellow: "Yellow",
};

export const RIDERS: { id: RiderType; label: string }[] = [
  { id: "agibot", label: "AGIBOT" },
  { id: "galbot", label: "GALBOT" },
];

export type TwinState = {
  page: Page;
  finish: Finish;
  color: LightColor;
  rider: RiderType;
  camera: CameraMode;
  build: BuildStep;
  zoom: number;
  riding: boolean;
};
