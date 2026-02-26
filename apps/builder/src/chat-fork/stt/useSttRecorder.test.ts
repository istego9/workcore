import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useSttRecorder } from './useSttRecorder';

describe('useSttRecorder', () => {
  it('sets error when media devices are unavailable', async () => {
    const originalMediaDevices = navigator.mediaDevices;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: undefined
    });

    try {
      const { result } = renderHook(() => useSttRecorder(async () => undefined));
      await act(async () => {
        await result.current.start();
      });
      expect(result.current.error).toContain('MediaRecorder is not available');
    } finally {
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: originalMediaDevices
      });
    }
  });
});
