import { useState } from "react";

import {
  Download,
  Droplets,
  Radio,
  Thermometer,
  ThermometerSun,
  TriangleAlert,
} from "lucide-react";

import { SensorHealth, ZoneThermalForecast } from "./AnalyticsPanel";
// Zone layout hidden for now; restore this import and the block below to bring it back.
// import LocationCard from "./LocationCard";
import MetricCard from "./MetricCard";
import NodeCard from "./NodeCard";
import TrendTag from "./TrendTag";
import ZoneHistoryCharts from "./ZoneHistoryCharts";
import useZoneAnalytics from "../hooks/useZoneAnalytics";

import {
  downloadCSV,
  formatDateTime,
  formatValue,
  getDemoZoneHistory,
  getTemperatureStatus,
  getWorstNode,
  getZoneSummary,
  isFresh,
} from "../utils/data";

export default function ReadingDetails({
  zone,
  node = null,
  isDemo,
  hours,
  onHoursChange,
  history = [],
  historyLoading,
  historyError,
  breaches = [],
  now,
  onSelectNode,
  upperLimit,
  onLimitChange,
  refreshKey,
}) {
  const [exportView, setExportView] = useState("average");

  const { forecast, health, forecastError, healthError, loading } =
    useZoneAnalytics(zone.zone_id, upperLimit, !isDemo && !node, refreshKey);

  const summary = getZoneSummary(zone, now);
  const current = node || summary;

  // Zone view with per-node data: mean, warmest node and node cards.
  const hasNodes = !node && zone.nodes?.length > 0;
  const worst = hasNodes ? getWorstNode(zone.nodes, now) : null;

  const readings = isDemo
    ? node
      ? node.history || []
      : getDemoZoneHistory(zone)
    : history;

  const relevantBreaches = breaches.filter(
    (entry) =>
      entry.zone.zone_id === zone.zone_id &&
      (!node || entry.node.node_id === node.node_id)
  );

  // Shown in the collapsed card header so the state is visible without opening it.
  const alertBad = isDemo
    ? relevantBreaches.length > 0
    : ["WARNING", "CRITICAL"].includes(zone.status);

  const alertStatus = isDemo
    ? relevantBreaches.length
      ? `${relevantBreaches.length} outside limits`
      : "None"
    : { NORMAL: "Within limits", WARNING: "Warning", CRITICAL: "Critical" }[zone.status] ||
      "Unavailable";

  function exportHistory() {
    let source;

    if (node) {
      source = readings.map((reading) => ({
        ...reading,
        zone_id: zone.zone_id,
        node_id: node.node_id,
      }));
    } else if (exportView === "nodes") {
      if (!isDemo) return;

      source = (zone.nodes || []).flatMap((sensor) =>
        (sensor.history || []).map((reading) => ({
          ...reading,
          zone_id: zone.zone_id,
          node_id: sensor.node_id,
        }))
      );
    } else {
      source = readings.map((reading) => ({
        ...reading,
        zone_id: zone.zone_id,
        node_id: "zone_average",
      }));
    }

    const end = Date.now();
    const start = end - hours * 3600000;

    const rows = source.filter((reading) => {
      const time =
        typeof reading.time === "number"
          ? reading.time
          : new Date(reading.timestamp ?? reading.time).getTime();

      return time >= start && time <= end;
    });

    if (rows.length === 0) return;

    const scope = node
      ? node.node_id
      : exportView === "nodes"
        ? "all-nodes"
        : "zone-average";

    downloadCSV(
      rows,
      `frost-${isDemo ? "DEMO-" : ""}${zone.zone_id}-${scope}-${hours}h.csv`
    );
  }

  return (
    <>
      <div className="metric-grid reading-metrics">
        <MetricCard
          title={
            node
              ? "Temperature"
              : isDemo
                ? "Average temperature"
                : "Zone temperature"
          }
          value={formatValue(current.temp_c, "°C")}
          description={
            <>
              {hasNodes
                ? `${summary.reporting} / ${summary.total} sensors reporting`
                : getTemperatureStatus(current.temp_c, zone.limits)}{" "}
              <TrendTag rate={current.rate_c_per_hour} />
            </>
          }
          icon={Thermometer}
        />

        {hasNodes && (
          <MetricCard
            title="Warmest sensor"
            value={formatValue(worst?.temp_c, "°C")}
            description={
              worst
                ? `${worst.name} · ${worst.location} · ${getTemperatureStatus(
                    worst.temp_c,
                    zone.limits
                  )}`
                : "No recent readings"
            }
            icon={ThermometerSun}
          />
        )}

        <MetricCard
          title={
            node
              ? "Humidity"
              : isDemo
                ? "Average humidity"
                : "Zone humidity"
          }
          value={formatValue(current.humidity, "% RH")}
          icon={Droplets}
        />

        {!hasNodes && (
          <MetricCard
            title={node ? "Reading freshness" : "Reporting nodes"}
            value={
              node
                ? isFresh(node, now)
                  ? "Recent"
                  : "Stale"
                : isDemo
                  ? `${summary.reporting} / ${summary.total}`
                  : "—"
            }
            description={
              node
                ? formatDateTime(node.timestamp)
                : isDemo
                  ? "Recent valid temperature readings"
                  : "Individual nodes unavailable"
            }
            icon={Radio}
          />
        )}
      </div>

      {isDemo && !node && relevantBreaches.length > 0 && (
        <div className="notice danger">
          <TriangleAlert size={19} />
          At least one node is outside its limits.
          The zone average can hide a local temperature breach.
        </div>
      )}

      {hasNodes && (
        <div className="node-grid">
          {zone.nodes.map((sensor) => (
            <NodeCard
              key={sensor.node_id}
              node={sensor}
              limits={zone.limits}
              now={now}
              isWorst={sensor.node_id === worst?.node_id}
              onSelect={onSelectNode}
            />
          ))}
        </div>
      )}

      <div className="detail-grid">
        <div className="detail-main">
          <ZoneHistoryCharts
            key={`${isDemo}:${zone.zone_id}:${node?.node_id || "overview"}`}
            zone={zone}
            node={node}
            isDemo={isDemo}
            readings={readings}
            hours={hours}
            onHoursChange={onHoursChange}
            historyLoading={historyLoading}
            historyError={historyError}
          />

          {!node && (
            <div className="sensor-health-below-chart">
              <SensorHealth
                isDemo={isDemo}
                health={health}
                healthError={healthError}
              />
            </div>
          )}
        </div>

        <div className="detail-sidebar">
          {/* Zone layout hidden for now.
          <LocationCard
            key={`${isDemo}:${zone.zone_id}:${node?.node_id || "overview"}`}
            zone={zone}
            node={node}
            isDemo={isDemo}
            now={now}
            onSelectNode={onSelectNode}
          />
          */}

          {!node && (
            <ZoneThermalForecast
              isDemo={isDemo}
              limit={upperLimit}
              onLimitChange={onLimitChange}
              forecast={forecast}
              forecastError={forecastError}
              loading={loading}
            />
          )}

          <details className="panel">
            <summary>
              <h3>Current limit alerts</h3>
              <span className={`summary-status${alertBad ? " bad" : ""}`}>
                {alertStatus}
              </span>
            </summary>

            {!isDemo ? (
              <p>
                {zone.status === "NORMAL"
                  ? "Zone temperature within limits."
                  : zone.status === "WARNING"
                    ? "Zone temperature warning."
                    : zone.status === "CRITICAL"
                      ? "Zone temperature critical."
                      : "Zone status unavailable."}
              </p>
            ) : relevantBreaches.length === 0 ? (
              <p>No current breaches.</p>
            ) : (
              relevantBreaches.map((entry) => (
                <div key={entry.node.node_id} className="notice danger">
                  {entry.node.name}:{" "}
                  {formatValue(entry.node.temp_c, "°C")} ·{" "}
                  {getTemperatureStatus(entry.node.temp_c, zone.limits)}
                </div>
              ))
            )}
          </details>

          <section className="panel">
            <h3>Export readings</h3>

            {!node && (
              <label className="export-view-field">
                Readings
                <select
                  value={exportView}
                  onChange={(event) => setExportView(event.target.value)}
                >
                  <option value="average">Zone average</option>

                  <option value="nodes" disabled={!isDemo}>
                    Individual node readings
                    {!isDemo ? " — unavailable" : ""}
                  </option>
                </select>
              </label>
            )}

            <button
              type="button"
              className="primary"
              onClick={exportHistory}
              disabled={
                readings.length === 0 ||
                (!isDemo && !node && exportView === "nodes")
              }
            >
              <Download size={17} aria-hidden="true" />
              Download CSV
            </button>

            <p className="muted">
              Last {hours} hours
              {isDemo && " · Sample data"}
            </p>
          </section>
        </div>
      </div>
    </>
  );
}