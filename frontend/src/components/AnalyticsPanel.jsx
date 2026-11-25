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

const checkState = (value) =>
  value === true ? "bad" : value === false ? "ok" : "na";

const stateText = { bad: "suspected", ok: "clear", na: "n/a" };

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

  // One-line states for the collapsed headers, so problems stay visible without opening a card.
  const forecastBad =
    forecast?.status === "breached" || forecast?.early_warning;

  const forecastStatus = isDemo
    ? ""
    : forecastError || (forecast && !available)
      ? "Unavailable"
      : !forecast
        ? loading ? "Loading…" : ""
        : forecast.status === "breached"
          ? "Above limit"
          : forecast.early_warning
            ? "Early warning"
            : forecast.status === "warming"
              ? "Warming"
              : "Not rising";

  const suspected = (health?.sensors || []).filter(
    (sensor) =>
      sensor.flatline_suspected === true ||
      sensor.drift_suspected === true ||
      sensor.erratic_suspected === true
  ).length;

  const healthStatus = isDemo
    ? "Demo mode"
    : healthError
      ? "Unavailable"
      : !health
        ? ""
        : suspected
          ? `${suspected} suspected`
          : "None suspected";

  return (
    <>
      <details className="panel analytics-panel">
        <summary>
          <h3>Zone thermal forecast</h3>
          <span
            className={`summary-status${forecastBad ? " bad" : ""}`}
          >
            {forecastStatus}
          </span>
        </summary>

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
      </details>

      <details className="panel analytics-panel">
        <summary>
          <h3>Sensor health</h3>
          <span
            className={`summary-status${suspected ? " bad" : ""}`}
          >
            {healthStatus}
          </span>
        </summary>

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

                <ul className="health-checks">
                  {[
                    ["Flatline", sensor.flatline_suspected, sensor.flatline_reason],
                    ["Drift", sensor.drift_suspected, sensor.drift_reason],
                    ["Erratic", sensor.erratic_suspected, null],
                  ].map(([name, value, why]) => {
                    const state = checkState(value);

                    return (
                      <li
                        key={name}
                        className={`health-check ${state}`}
                        // Why a check could not run is in the tooltip, not on screen.
                        title={state === "na" && why ? reason(why) : undefined}
                      >
                        {name} <span>{stateText[state]}</span>
                      </li>
                    );
                  })}
                </ul>

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
      </details>
    </>
  );
}