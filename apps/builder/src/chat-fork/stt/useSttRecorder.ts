import { useCallback, useEffect, useRef, useState } from 'react';

export type SttPayload = {
  audioBase64: string;
  mimeType: string;
};

const DEFAULT_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'];

const toBase64 = async (blob: Blob): Promise<string> => {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
};

const pickMimeType = (): string => {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return 'audio/webm';
  }
  const supported = DEFAULT_MIME_TYPES.find((mime) => MediaRecorder.isTypeSupported(mime));
  return supported || 'audio/webm';
};

export function useSttRecorder(onReady: (payload: SttPayload) => Promise<void> | void) {
  const [isRecording, setIsRecording] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const releaseStream = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    stream.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      releaseStream();
      mediaRecorderRef.current = null;
    };
  }, [releaseStream]);

  const start = useCallback(async () => {
    setError('');
    if (isRecording || isBusy) return;
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setError('MediaRecorder is not available in this browser');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        setError('Audio recording failed');
        setIsRecording(false);
        setIsBusy(false);
        releaseStream();
      };

      recorder.onstop = async () => {
        try {
          setIsBusy(true);
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || mimeType });
          if (!blob.size) {
            setError('Recorded audio is empty');
            return;
          }
          const audioBase64 = await toBase64(blob);
          await onReady({ audioBase64, mimeType: blob.type || mimeType });
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to process audio');
        } finally {
          setIsRecording(false);
          setIsBusy(false);
          releaseStream();
        }
      };

      recorder.start();
      setIsRecording(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to start recording');
      setIsRecording(false);
      setIsBusy(false);
      releaseStream();
    }
  }, [isRecording, isBusy, onReady, releaseStream]);

  const stop = useCallback(() => {
    if (!isRecording || !mediaRecorderRef.current) return;
    mediaRecorderRef.current.stop();
  }, [isRecording]);

  const toggle = useCallback(async () => {
    if (isRecording) {
      stop();
      return;
    }
    await start();
  }, [isRecording, start, stop]);

  return {
    isRecording,
    isBusy,
    error,
    start,
    stop,
    toggle,
    setError
  };
}
