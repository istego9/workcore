export type CanvasPoint = {
  x: number;
  y: number;
};

export const CANVAS_SCALE_MIN = 0.5;
export const CANVAS_SCALE_MAX = 2;
export const CANVAS_SCALE_STEP = 0.1;
export const CANVAS_WHEEL_ZOOM_SENSITIVITY = 0.001;

export const clampCanvasScale = (value: number): number =>
  Math.min(CANVAS_SCALE_MAX, Math.max(CANVAS_SCALE_MIN, value));

type ComputeZoomedOffsetParams = {
  anchor: CanvasPoint;
  offset: CanvasPoint;
  previousScale: number;
  nextScale: number;
};

export const computeZoomedOffset = ({
  anchor,
  offset,
  previousScale,
  nextScale
}: ComputeZoomedOffsetParams): CanvasPoint => {
  if (!Number.isFinite(previousScale) || !Number.isFinite(nextScale) || previousScale <= 0 || nextScale <= 0) {
    return offset;
  }

  const worldX = (anchor.x - offset.x) / previousScale;
  const worldY = (anchor.y - offset.y) / previousScale;

  return {
    x: anchor.x - worldX * nextScale,
    y: anchor.y - worldY * nextScale
  };
};
