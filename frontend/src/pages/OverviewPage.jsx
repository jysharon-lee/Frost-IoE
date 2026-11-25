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
  getLimitState,
  getTemperatureStatus,
  getZoneSummary,
  isDown,
  isFresh,
  FRESHNESS_LIMIT,
} from "../utils/data";

export default function OverviewPage({
  zones,
  breaches,
  faulty,
  now,
  onOpenZone,
  onOpenNode,
}) {
  /* Offline sensors; a zone with every sensor down becomes one row. */
  const offlineRows = zones.flatMap((zone) => {
    const nodes = zone.nodes || [];
    const down = nodes.filter((node) => isDown(node, now));

    return nodes.length && down.length === nodes.length
      ? [{ zone, node: nodes[0], label: "All sensors" }]
      : down.map((node) => ({ zone, node, label: node.name }));
  });

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
          value={breaches.length}
          description="Based on individual nodes"
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

          const limit = getLimitState(zone, now);

          const offline = (zone.nodes || []).filter((node) =>
            isDown(node, now)
          ).length;

          const check = (zone.nodes || []).filter(
            (node) =>
              !isDown(node, now) &&
              faulty.has(`${zone.zone_id}/${node.node_id}`)
          ).length;

          const tone = !recent
            ? "amber"
            : limit.tone || "green";

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

              <Badge tone={tone}>
                {!recent
                  ? "Stale reading"
                  : limit.outside
                    ? `${limit.outside} of ${limit.total} nodes outside limits`
                    : offline
                      ? "Reporting nodes within limits"
                      : "All nodes within limits"}
              </Badge>

              {recent && offline > 0 && (
                <Badge tone="amber">
                  <i className="zone-dot amber" />
                  {offline} {offline === 1 ? "sensor" : "sensors"} offline
                </Badge>
              )}

              {recent && check > 0 && (
                <Badge tone="amber">
                  <i className="zone-dot amber" />
                  {check} {check === 1 ? "sensor" : "sensors"} to check
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

        {breaches.length === 0 && offlineRows.length === 0 && (
          <p>No current node breaches or offline sensors.</p>
        )}

        {offlineRows.map(({ zone, node, label }) => (
          <button
            className="alert-row offline"
            key={`off-${zone.zone_id}-${node.node_id}`}
            onClick={() => onOpenNode(zone.zone_id, node.node_id)}
          >
            <TriangleAlert size={20} />

            <span>
              <b>
                {zone.name} · {label}
              </b>

              <small>
                Offline
                {node.timestamp
                  ? ` · last report ${formatDateTime(node.timestamp)}`
                  : ""}
              </small>
            </span>

            <ChevronRight size={18} />
          </button>
        ))}

        {(
          breaches.map((entry) => (
            <button
              className={`alert-row${
                getTemperatureStatus(
                  entry.node.temp_c,
                  entry.zone.limits
                ) === "Below limit"
                  ? " cold"
                  : ""
              }`}
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