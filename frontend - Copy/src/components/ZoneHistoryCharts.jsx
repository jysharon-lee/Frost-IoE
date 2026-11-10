import { useState } from "react";

import { Droplets, Thermometer } from "lucide-react";

import HistoryChart from "./HistoryChart";

import {
  addHistoryGaps,
  getComparisonHistory,
} from "../utils/data";

import "../styles/zoneHistoryCharts.css";

function ChartSection({
  title,
  icon: Icon,
  humidity = false,
  view,
  onViewChange,
  canCompare,
  readings,
  zone,
}) {
  const comparing =
    canCompare && view === "comparison";

  const data = comparing
    ? getComparisonHistory(
        zone,
        humidity ? "humidity" : "temp_c"
      )
    : addHistoryGaps(readings);

  return (
    <section className="panel history-switch-panel">
      <div className="history-switch-heading">
        <h3>
          <Icon size={22} aria-hidden="true" />
          {title}
        </h3>

        {canCompare && (
          <div
            className="history-view-switch"
            role="group"
            aria-label={`${title} display`}
          >
            <button
              type="button"
              className={
                view === "average" ? "active" : ""
              }
              aria-pressed={view === "average"}
              onClick={() => onViewChange("average")}
            >
              Zone average
            </button>

            <button
              type="button"
              className={
                view === "comparison" ? "active" : ""
              }
              aria-pressed={view === "comparison"}
              onClick={() => onViewChange("comparison")}
            >
              Node comparison
            </button>
          </div>
        )}
      </div>

      <div className="history-switch-chart">
        <HistoryChart
          title={title}
          data={data}
          humidity={humidity}
          limits={humidity ? undefined : zone.limits}
          nodes={comparing ? zone.nodes : undefined}
        />
      </div>
    </section>
  );
}

export default function ZoneHistoryCharts({
  zone,
  node = null,
  isDemo,
  readings = [],
  hours,
  onHoursChange,
  historyLoading,
  historyError,
}) {
  const [temperatureView, setTemperatureView] =
    useState("comparison");

  const [humidityView, setHumidityView] =
    useState("comparison");

  // The current API provides zone history only.
  const canCompare =
    isDemo && !node && zone.nodes?.length > 0;

  return (
    <div className="zone-history-charts">
      <div className="history-range-toolbar">
        <label htmlFor="zone-history-range">
          History period
        </label>

        <select
          id="zone-history-range"
          value={hours}
          onChange={(event) =>
            onHoursChange(Number(event.target.value))
          }
        >
          {[1, 6, 24, 72, 168].map((value) => (
            <option key={value} value={value}>
              Last {value} hours
            </option>
          ))}
        </select>
      </div>

      {historyError && (
        <div className="notice danger" role="alert">
          {historyError}

          {readings.length > 0 &&
            " Showing previous chart data."}
        </div>
      )}

      {historyLoading && (
        <p className="muted" role="status">
          Refreshing history…
        </p>
      )}

      <ChartSection
        title="Temperature"
        icon={Thermometer}
        view={temperatureView}
        onViewChange={setTemperatureView}
        canCompare={canCompare}
        readings={readings}
        zone={zone}
      />

      <ChartSection
        title="Humidity"
        icon={Droplets}
        humidity
        view={humidityView}
        onViewChange={setHumidityView}
        canCompare={canCompare}
        readings={readings}
        zone={zone}
      />
    </div>
  );
}