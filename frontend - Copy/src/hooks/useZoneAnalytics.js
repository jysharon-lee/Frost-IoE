import { useEffect, useState } from "react";

import {
  getForecast,
  getSensorHealth,
} from "../api";

export default function useZoneAnalytics(
  zoneId,
  limit,
  enabled,
  refreshKey
) {
  const [state, setState] = useState({});

  const key =
    `${zoneId}:${limit}:${enabled}:${refreshKey}`;

  useEffect(() => {
    let cancelled = false;
    let timer;

    const controller = new AbortController();

    setState({
      key,
      loading: enabled,
    });

    if (!enabled || !zoneId) {
      return () => controller.abort();
    }

    async function poll() {
      const results = await Promise.allSettled([
        Number.isFinite(limit) &&
        limit >= -100 &&
        limit <= 100
          ? getForecast(
              zoneId,
              limit,
              controller.signal
            )
          : Promise.reject(
              new Error(
                "Select an upper limit between −100 and 100°C."
              )
            ),

        getSensorHealth(
          zoneId,
          controller.signal
        ),
      ]);

      if (cancelled) return;

      const next = {
        key,
        loading: false,
      };

      results.forEach((result, index) => {
        const name =
          index === 0 ? "forecast" : "health";

        if (result.status === "fulfilled") {
          next[name] = result.value;
        } else {
          next[`${name}Error`] =
            result.reason.message;
        }
      });

      setState(next);
      timer = setTimeout(poll, 10_000);
    }

    poll();

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [zoneId, limit, enabled, refreshKey, key]);

  return state.key === key
    ? state
    : { loading: enabled };
}