import { useEffect, useState } from "react";

import { getLiveZones, getSite, getZoneTrend } from "../api";
import { createDemoZones } from "../utils/data";

/* Client site config, loaded once. Null if the backend is unreachable. */

export function useSite() {
  const [site, setSite] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    getSite(controller.signal)
      .then(setSite)
      .catch(() => {});

    return () => controller.abort();
  }, []);

  return site;
}

/* Live zone readings */

export function useLiveZones(mode, hours, refreshKey) {
  const [data, setData] = useState({ mode, zones: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer;

    const controller = new AbortController();

    setData({ mode, zones: [] });
    setError("");
    setLastRefresh(null);

    async function poll() {
      setLoading(true);

      try {
        const result =
          mode === "demo"
            ? { zones: createDemoZones(hours) }
            : await getLiveZones(controller.signal);

        if (!cancelled) {
          setData({ mode, zones: result.zones });
          setLastRefresh(Date.now());
          setError("");
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            requestError.name === "TimeoutError"
              ? "The API request timed out."
              : requestError.message
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(poll, 10_000);
        }
      }
    }

    poll();

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [mode, hours, refreshKey]);

  // Effects run after render, so on a mode switch the first render still
  // holds the old mode's zones (no node.history in demo). Hide them.
  return {
    zones: data.mode === mode ? data.zones : [],
    loading,
    error,
    lastRefresh,
  };
}

/* Zone history */

export function useZoneHistory(
  mode,
  zoneId,
  hours,
  refreshKey
) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setHistory([]);
    setError("");
    setLoading(false);

    if (mode !== "api" || !zoneId) {
      return;
    }

    let cancelled = false;
    let timer;

    const controller = new AbortController();

    async function poll() {
      setLoading(true);

      try {
        const readings = await getZoneTrend(
          zoneId,
          hours,
          controller.signal
        );

        if (!cancelled) {
          setHistory(readings);
          setError("");
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            requestError.name === "TimeoutError"
              ? "The history request timed out."
              : requestError.message
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(poll, 10_000);
        }
      }
    }

    poll();

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [mode, zoneId, hours, refreshKey]);

  return {
    history,
    loading,
    error,
  };
}

/* Current time for reading freshness */

export function useCurrentTime() {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 10_000);

    return () => clearInterval(timer);
  }, []);

  return now;
}