import { useCallback, useEffect, useState } from 'react';

type VisualReviewStatus = 'ready' | 'failed';

/**
 * A visual decision is reviewable only after every required image has rendered.
 * URL presence is intentionally insufficient because protected or expired assets
 * can resolve to a non-image placeholder without throwing at the request layer.
 */
export function useVisualReviewReadiness(scopeKey: string) {
  const [statusByKey, setStatusByKey] = useState<ReadonlyMap<string, VisualReviewStatus>>(
    () => new Map(),
  );

  useEffect(() => {
    setStatusByKey(new Map());
  }, [scopeKey]);

  const markReady = useCallback((key: string | null): void => {
    if (key === null) return;
    setStatusByKey((current) => {
      if (current.get(key) === 'ready') return current;
      const next = new Map(current);
      next.set(key, 'ready');
      return next;
    });
  }, []);

  const markFailed = useCallback((key: string | null): void => {
    if (key === null) return;
    setStatusByKey((current) => {
      if (current.get(key) === 'failed') return current;
      const next = new Map(current);
      next.set(key, 'failed');
      return next;
    });
  }, []);

  const isReady = useCallback((key: string | null): boolean => (
    key !== null && statusByKey.get(key) === 'ready'
  ), [statusByKey]);

  const allReady = useCallback((keys: readonly (string | null)[]): boolean => (
    keys.length > 0 && keys.every((key) => key !== null && statusByKey.get(key) === 'ready')
  ), [statusByKey]);

  const anyFailed = useCallback((keys: readonly (string | null)[]): boolean => (
    keys.some((key) => key === null || statusByKey.get(key) === 'failed')
  ), [statusByKey]);

  return { allReady, anyFailed, isReady, markFailed, markReady } as const;
}
