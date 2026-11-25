import { formatDateTime, formatValue } from "../utils/data";
import { Activity } from "lucide-react";

const rate = (value) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3)
    : "—";

const reason = (value) =>
  value ? value.replaceAll("_", " ") : "No result available";

const flag = (value) =>
  value === true
    ? "Suspected anomaly"
    : value === false
      ? "Not detected"
      : "Unavailable";

export function ZoneThermalForecast({
  isDemo,
  limit,
  onLimitChange,
  forecast,
  forecastError,
  loading,
}) {
  const available = forecast && forecast.status !== "unavailable";

  return (
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
              event.target.value === "" ? null : Number(event.target.value)
            )
          }
        />
      </label>

      {!isDemo && (
        <>
          {loading && <p role="status">Loading analytics…</p>}

          {forecastError && (
            <p role="alert" className="notice danger">
              {forecastError}
            </p>
          )}

          {forecast && (
            <>
              <p
                className={
                  forecast.status === "breached" || forecast.early_warning
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
                  <dd>{rate(forecast.rate_c_per_minute)} °C/min</dd>

                  <dt>Hourly rate</dt>
                  <dd>{rate(forecast.rate_c_per_hour)} °C/hour</dd>

                  <dt>Time to upper limit</dt>
                  <dd>
                    {forecast.status === "breached"
                      ? "Already above limit"
                      : forecast.minutes_to_limit == null
                        ? "No projected crossing"
                        : formatValue(forecast.minutes_to_limit, " min")}
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
  );
}

function getSensorHealthStatus(sensor) {
  const { flatline_suspected: flatline, drift_suspected: drift } = sensor;

  if (flatline === true || drift === true) {
    return "flagged";
  }

  if (flatline === false && drift === false) {
    return "healthy";
  }

  return "incomplete";
}

export function SensorHealth({ isDemo, health, healthError }) {
  const sensors = health?.sensors ?? [];
  const results = sensors.map((sensor) => ({
    sensor,
    status: getSensorHealthStatus(sensor),
  }));

  const healthyCount = results.filter(({ status }) => status === "healthy").length;
  const flaggedCount = results.filter(({ status }) => status === "flagged").length;
  const incompleteCount = results.length - healthyCount - flaggedCount;

  const statusLabels = {
    healthy: "Healthy",
    flagged: "Flagged",
    incomplete: "Incomplete checks",
  };

  return (
    <section className="panel analytics-panel sensor-health-panel">
      <header className="sensor-health-header">
        <h3>
          <Activity size={22} aria-hidden="true" />
          Sensor health
        </h3>

        {!isDemo && health && (
          <small className="sensor-health-updated">
            Updated: {formatDateTime(health.generated_at)}
          </small>
        )}
      </header>

      {isDemo ? (
        <p>Diagnostics unavailable in demo mode.</p>
      ) : (
        <>
          {healthError && (
            <p role="alert" className="notice danger">
              {healthError}
            </p>
          )}

          {health && results.length === 0 && (
            <p>No sensor health data available.</p>
          )}

          {results.length > 0 && (
            <>
              <div className="sensor-health-summary">
                <span className="sensor-health-badge">
                  {results.length} {results.length === 1 ? "result" : "results"}
                </span>

                <span className="sensor-health-badge" data-status="healthy">
                  {healthyCount} healthy
                </span>

                <span className="sensor-health-badge" data-status="flagged">
                  {flaggedCount} flagged
                </span>

                {incompleteCount > 0 && (
                  <span className="sensor-health-badge" data-status="incomplete">
                    {incompleteCount} incomplete
                  </span>
                )}
              </div>

              <div className="sensor-health-grid">
                {results.map(({ sensor, status }) => (
                  <div className="health-result" key={sensor.sensor_id}>
                    <div className="sensor-health-tile-header">
                      <h4>
                        {sensor.scope === "zone"
                          ? "Zone aggregate"
                          : sensor.sensor_id}
                      </h4>

                      <span className="sensor-health-badge" data-status={status}>
                        {statusLabels[status]}
                      </span>
                    </div>

                    <dl className="sensor-health-checks">
                      <div className="sensor-health-check">
                        <dt>Flatline</dt>
                        <dd>{flag(sensor.flatline_suspected)}</dd>

                        {sensor.flatline_suspected == null && (
                          <dd className="sensor-health-reason">
                            {reason(sensor.flatline_reason)}
                          </dd>
                        )}
                      </div>

                      <div className="sensor-health-check">
                        <dt>Drift</dt>
                        <dd>{flag(sensor.drift_suspected)}</dd>

                        {sensor.drift_suspected == null && (
                          <dd className="sensor-health-reason">
                            {reason(sensor.drift_reason)}
                          </dd>
                        )}
                      </div>
                    </dl>

                    {sensor.uploaded_later > 0 && (
                      <small className="late-note">
                        {sensor.uploaded_later}{" "}
                        {sensor.uploaded_later === 1 ? "reading" : "readings"}{" "}
                        logged on the board and uploaded after an outage,{" "}
                        {formatDateTime(sensor.uploaded_later_from)} to{" "}
                        {formatDateTime(sensor.uploaded_later_to)}
                      </small>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      <p className="muted sensor-health-note">
        Flags indicate suspected sensor issues.
      </p>
    </section>
  );
}