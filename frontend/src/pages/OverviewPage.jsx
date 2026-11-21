import {
  ChevronRight,
  Radio,
  TriangleAlert,
  Warehouse,
} from "lucide-react";

import Badge from "../components/Badge";
import MetricCard from "../components/MetricCard";
import TrendTag from "../components/TrendTag";

import {
  formatDateTime,
  formatValue,
  getTemperatureStatus,
  getZoneSummary,
  isFresh,
  FRESHNESS_LIMIT,
} from "../utils/data";

export default function OverviewPage({
  zones,
  isDemo,
  breaches,
  now,
  onOpenZone,
  onOpenNode,
}) {
  return (
    <div className="overview-page">
      <div className="metric-grid overview-metrics">
        <MetricCard
          title="Monitored zones"
          value={zones.length}
          icon={Warehouse}
        />

        <MetricCard
          title="Recent zone readings"
          value={
            zones.filter((zone) =>
              isFresh(zone, now)
            ).length
          }
          description={`Freshness window: ${FRESHNESS_LIMIT / 1000} seconds`}
          icon={Radio}
        />

        <MetricCard
          title="Node limit breaches"
          value={isDemo ? breaches.length : "—"}
          description={
            isDemo
              ? "Based on individual nodes"
              : "Node data unavailable"
          }
          icon={TriangleAlert}
        />
      </div>

      <div className="section-heading">
        <h2>Your storage zones</h2>

        <span>
          Select a zone to inspect its readings
        </span>
      </div>

      <div className="zone-grid">
        {zones.map((zone) => {
          const values = getZoneSummary(zone, now);
          const recent = isFresh(zone, now);

          const count = breaches.filter(
            (entry) =>
              entry.zone.zone_id === zone.zone_id
          ).length;

          const tone = !recent
            ? "amber"
            : isDemo
              ? count > 0
                ? "red"
                : "green"
              : "";

          return (
            <button
              key={zone.zone_id}
              className="panel zone-card"
              onClick={() =>
                onOpenZone(zone.zone_id)
              }
            >
              <div className="panel-heading">
                <h3>{zone.name}</h3>
                <ChevronRight size={19} />
              </div>

              <p>{zone.type}</p>

              <div className="zone-readings">
                <strong>
                  {formatValue(values.temp_c, "°C")}
                </strong>

                <span>
                  {formatValue(values.humidity, "% RH")}
                </span>

                <TrendTag rate={values.rate_c_per_hour} />
              </div>

              {(!recent || isDemo) && (
                <Badge tone={tone}>
                  {!recent
                    ? "Stale reading"
                    : count > 0
                      ? `${count} node(s) outside limits`
                      : "All nodes within limits"}
                </Badge>
              )}

              <small>
                Last reading:{" "}
                {formatDateTime(zone.timestamp)}
              </small>
            </button>
          );
        })}
      </div>

      <section className="panel">
        <h3>Attention required</h3>

        {!isDemo ? (
          <p className="muted">
            Alert history is not available from the current API.
          </p>
        ) : breaches.length === 0 ? (
          <p>No current node breaches.</p>
        ) : (
          breaches.map((entry) => (
            <button
              className="alert-row"
              key={
                entry.zone.zone_id +
                entry.node.node_id
              }
              onClick={() =>
                onOpenNode(
                  entry.zone.zone_id,
                  entry.node.node_id
                )
              }
            >
              <TriangleAlert size={20} />

              <span>
                <b>
                  {entry.zone.name} · {entry.node.name}
                </b>

                <small>
                  {getTemperatureStatus(
                    entry.node.temp_c,
                    entry.zone.limits
                  )}{" "}
                  · {formatValue(entry.node.temp_c, "°C")}
                </small>
              </span>

              <ChevronRight size={18} />
            </button>
          ))
        )}
      </section>
    </div>
  );
}