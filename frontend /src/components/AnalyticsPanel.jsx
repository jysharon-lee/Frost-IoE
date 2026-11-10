import useZoneAnalytics from "../hooks/useZoneAnalytics";
import { formatDateTime, formatValue } from "../utils/data";

const rate = (value) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3)
    : "—";

const reason = (value) =>
  value
    ? value.replaceAll("_", " ")
    : "No result available";

const flag = (value) =>
  value === true
    ? "Suspected anomaly"
    : value === false
      ? "Not detected"
      : "Unavailable";

export default function AnalyticsPanel({
  zone,
  isDemo,
  limit,
  onLimitChange,
  refreshKey,
}) {
  const {
    forecast,
    health,
    forecastError,
    healthError,
    loading,
  } = useZoneAnalytics(
    zone.zone_id,
    limit,
    !isDemo,
    refreshKey
  );

  const available =
    forecast && forecast.status !== "unavailable";

  return (
    <>
      <section className="panel analytics-panel">
        <h3>Zone thermal forecast</h3>

        <label>
          Select upper temperature limit (°C)
          <input
            type="number"
            min="-100"
            max="100"
            step="0.1"
            value={Number.isFinite(limit) ? limit : ""}
            onChange={(event) =>
              onLimitChange(
                event.target.value === ""
                  ? null
                  : Number(event.target.value)
              )
            }
          />
        </label>

        {!isDemo && (
          <>
            {loading && (
              <p role="status">Loading analytics…</p>
            )}

            {forecastError && (
              <p role="alert" className="notice danger">
                {forecastError}
              </p>
            )}

            {forecast && (
              <>
                <p
                  className={
                    forecast.status === "breached" ||
                    forecast.early_warning
                      ? "notice danger"
                      : "notice"
                  }
                >
                  {!available
                    ? `Unavailable: ${reason(forecast.reason)}`
                    : forecast.status === "breached"
                      ? "Latest temperature is already above the selected upper limit."
                      : forecast.early_warning
                        ? "Early warning: projected crossing within 20 minutes."
                        : forecast.status === "warming"
                          ? "Warming; No early warning"
                          : "Recent temperature trend is not rising."}
                </p>

                {available && (
                  <dl className="analytics-values">
                    <dt>Rise rate</dt>
                    <dd>
                      {rate(forecast.rate_c_per_minute)} °C/min
                    </dd>

                    <dt>Hourly rate</dt>
                    <dd>
                      {rate(forecast.rate_c_per_hour)} °C/hour
                    </dd>

                    <dt>Time to upper limit</dt>
                    <dd>
                      {forecast.status === "breached"
                        ? "Already above limit"
                        : forecast.minutes_to_limit == null
                          ? "No projected crossing"
                          : formatValue(
                              forecast.minutes_to_limit,
                              " min"
                            )}
                    </dd>
                  </dl>
                )}

                <small>
                  Updated: {formatDateTime(forecast.generated_at)}
                </small>
              </>
            )}
          </>
        )}

        <p className="muted">
          10-minute trend · 20-minute warning window
        </p>
      </section>

      <section className="panel analytics-panel">
        <h3>Sensor health</h3>

        {isDemo ? (
          <p>Diagnostics unavailable in demo mode.</p>
        ) : (
          <>
            {healthError && (
              <p role="alert" className="notice danger">
                {healthError}
              </p>
            )}

            {health && !health.sensors?.length && (
              <p>No sensor health data available.</p>
            )}

            {health?.sensors?.map((sensor) => (
              <div
                className="health-result"
                key={sensor.sensor_id}
              >
                <h4>
                  {sensor.scope === "zone"
                    ? "Zone aggregate"
                    : sensor.sensor_id}
                </h4>

                <p
                  className={
                    sensor.flatline_suspected === true
                      ? "notice danger"
                      : ""
                  }
                >
                  Flatline: {flag(sensor.flatline_suspected)}
                </p>

                {sensor.flatline_suspected == null && (
                  <small>
                    {reason(sensor.flatline_reason)}
                  </small>
                )}

                <p
                  className={
                    sensor.drift_suspected === true
                      ? "notice danger"
                      : ""
                  }
                >
                  Drift: {flag(sensor.drift_suspected)}
                </p>

                {sensor.drift_suspected == null && (
                  <small>
                    {reason(sensor.drift_reason)}
                  </small>
                )}
              </div>
            ))}

            {health && (
              <small>
                Updated: {formatDateTime(health.generated_at)}
              </small>
            )}
          </>
        )}

        <p className="muted">
          Flags indicate suspected sensor issues.
        </p>
      </section>
    </>
  );
}