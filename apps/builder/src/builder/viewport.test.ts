import { describe, expect, it } from 'vitest';
import { CANVAS_SCALE_MAX, CANVAS_SCALE_MIN, clampCanvasScale, computeZoomedOffset } from './viewport';

describe('clampCanvasScale', () => {
  it('keeps scale inside supported range', () => {
    expect(clampCanvasScale(CANVAS_SCALE_MIN - 0.2)).toBe(CANVAS_SCALE_MIN);
    expect(clampCanvasScale(CANVAS_SCALE_MAX + 0.4)).toBe(CANVAS_SCALE_MAX);
    expect(clampCanvasScale(1.25)).toBe(1.25);
  });
});

describe('computeZoomedOffset', () => {
  it('keeps anchor point stable while zooming', () => {
    const anchor = { x: 480, y: 260 };
    const offset = { x: 120, y: 50 };
    const previousScale = 1;
    const nextScale = 1.4;
    const nextOffset = computeZoomedOffset({ anchor, offset, previousScale, nextScale });

    const worldBefore = {
      x: (anchor.x - offset.x) / previousScale,
      y: (anchor.y - offset.y) / previousScale
    };
    const worldAfter = {
      x: (anchor.x - nextOffset.x) / nextScale,
      y: (anchor.y - nextOffset.y) / nextScale
    };

    expect(worldAfter.x).toBeCloseTo(worldBefore.x, 6);
    expect(worldAfter.y).toBeCloseTo(worldBefore.y, 6);
  });

  it('returns previous offset for invalid scale values', () => {
    const offset = { x: 10, y: 20 };
    expect(
      computeZoomedOffset({
        anchor: { x: 100, y: 100 },
        offset,
        previousScale: 0,
        nextScale: 1
      })
    ).toEqual(offset);
  });
});
