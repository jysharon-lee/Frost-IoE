import { RefreshCw } from "lucide-react";

import { formatDateTime } from "../utils/data";

export default function Header({
  title,
  subtitle,
  mode,
  onModeChange,
  onRefresh,
  loading,
  lastRefresh,
}) {
  return (
    <header className="page-header">
      <div className="header-title">
        <p className="eyebrow">
          FROST-IoE / MONITORING
        </p>

        <h1>{title}</h1>
      </div>

      <div className="header-controls">
        <label
          className="sr-only"
          htmlFor="data-source"
        >
          Data source
        </label>

        <select
          id="data-source"
          value={mode}
          onChange={(event) =>
            onModeChange(event.target.value)
          }
        >
          <option value="demo">Demo</option>
          <option value="api">Backend</option>
        </select>

        <button
          type="button"
          aria-label="Refresh readings"
          onClick={onRefresh}
        >
          <RefreshCw
            size={18}
            className={loading ? "spinning" : ""}
          />
        </button>
      </div>

      <p className="subtitle header-subtitle">
        {subtitle}
      </p>

      <p className="header-refresh-time">
        Last successful refresh:{" "}
        {lastRefresh
          ? formatDateTime(lastRefresh)
          : "Waiting for response"}
      </p>
    </header>
  );
}