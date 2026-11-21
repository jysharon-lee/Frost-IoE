import { useState } from "react";
import { Droplets } from "lucide-react";

import Badge from "./Badge";
import TrendTag from "./TrendTag";

import {
  formatLimits,
  formatValue,
  getTemperatureStatus,
  isFresh,
} from "../utils/data";

/* Click the face: readings shrink up, details slide in. Card size never changes. */
export default function NodeCard({
  node,
  limits,
  now,
  isWorst,
  onSelect,
}) {
  const [open, setOpen] = useState(false);

  const recent = isFresh(node, now);

  const status = recent
    ? getTemperatureStatus(node.temp_c, limits)
    : "Stale reading";

  const outsideLimits =
    recent &&
    (status === "Above limit" ||
      status === "Below limit");

  const statusClass = !recent
    ? "stale"
    : outsideLimits
      ? "breach"
      : status === "Within limits"
        ? "normal"
        : "unavailable";

  return (
    <div
      className={[
        "panel compact-node-card",
        outsideLimits ? "has-breach" : "",
        isWorst ? "is-worst" : "",
        open ? "open" : "",
      ].join(" ")}
    >
      <button
        type="button"
        className="node-card-face"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="compact-node-name">
          {node.name}

          {isWorst && <Badge tone="amber">Warmest</Badge>}
        </span>

        <span className="compact-node-readings">
          <strong>
            {formatValue(node.temp_c, "°C")}
          </strong>

          <span className="compact-node-humidity">
            <Droplets size={15} aria-hidden="true" />

            {formatValue(node.humidity, "% RH")}
          </span>

          {recent && <TrendTag rate={node.rate_c_per_hour} />}
        </span>

        <span
          className={`compact-node-status ${statusClass}`}
        >
          {status}
        </span>
      </button>

      <div className="node-card-details" aria-hidden={!open}>
        <dl>
          <div>
            <dt>Location</dt>
            <dd>{node.location || "Not set"}</dd>
          </div>

          <div>
            <dt>Limit</dt>
            <dd>{formatLimits(limits)}</dd>
          </div>
        </dl>

        <button
          type="button"
          onClick={() => onSelect?.(node.node_id)}
        >
          View {node.name} →
        </button>
      </div>
    </div>
  );
}
