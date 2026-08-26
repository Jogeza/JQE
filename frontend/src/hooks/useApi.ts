import { useState, useEffect, useCallback, useRef } from 'react';

export function useInterval(callback: () => void, delay: number | null) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (delay === null) return;
    const id = setInterval(() => savedCallback.current(), delay);
    return () => clearInterval(id);
  }, [delay]);
}

export function useApiQuery<T>(
  queryFn: () => Promise<T>,
  deps: unknown[] = [],
  options: { pollIntervalMs?: number; enabled?: boolean } = {}
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const requestIdRef = useRef(0);
  const inFlightRef = useRef(false);

  const fetchData = useCallback(async (isPolling: boolean = false) => {
    if (options.enabled === false) return;
    if (inFlightRef.current) return;
    const requestId = ++requestIdRef.current;
    inFlightRef.current = true;
    if (!isPolling) setLoading(true);
    try {
      const result = await queryFn();
      if (requestId !== requestIdRef.current) return;
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      setData(null);
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (requestId === requestIdRef.current) {
        inFlightRef.current = false;
        if (!isPolling) setLoading(false);
      }
    }
  }, [options.enabled, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchData(false);
    return () => {
      requestIdRef.current += 1;
      inFlightRef.current = false;
    };
  }, [fetchData]);

  useInterval(
    () => {
      fetchData(true);
    },
    options.pollIntervalMs ? options.pollIntervalMs : null
  );

  return { data, loading, error, refetch: () => fetchData(false), lastUpdated };
}
