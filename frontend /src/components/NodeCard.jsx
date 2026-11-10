import { Droplets } from "lucide-react";

import {
  formatValue,
  getTemperatureStatus,
  isFresh,
} from "../utils/data";

export default function NodeCard({
  node,
  limits,
  now,
  onSelect,
}) {
  const recent = isFresh(node, now);

  const status = recent
    ? getTemperatureStatus(node.temp_c, limits)
    : "Stale reading";

  const outsideLimits =
    recent &&
    (status === "Above limit" ||
      status === "Below limit");

  const statusClass = outsideLimits
    ? "breach"
    : status === "Within limits"
      ? "normal"
      : "unavailable";

  return (
    <button
      type="button"
      className={`panel compact-node-card ${
        outsideLimits ? "has-breach" : ""
      }`}
      onClick={() => onSelect?.(node.node_id)}
      aria-label={`View ${node.name}: ${status}`}
    >
      <span className="compact-node-name">
        {node.name}
      </span>

      <span className="compact-node-readings">
        <strong>
          {formatValue(node.temp_c, "°C")}
        </strong>

        <span className="compact-node-humidity">
          <Droplets size={15} aria-hidden="true" />

          {formatValue(node.humidity, "% RH")}
        </span>
      </span>

      <span
        className={`compact-node-status ${statusClass}`}
      >
        {status}
      </span>
    </button>
  );
}