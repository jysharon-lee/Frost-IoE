import { useState } from "react";
import { Download } from "lucide-react";
import { downloadReport, getZoneTrend } from "../api";

import {
  downloadCSV,
  getDemoZoneHistory,
} from "../utils/data";

export default function ReportsPage({
  zones,
  isDemo,
  hours,
  onHoursChange,
  getLimit,
}) {
  const [selectedZone, setSelectedZone] = useState("");
  const [exporting, setExporting] = useState("");
  const [error, setError] = useState("");
  const [exportView, setExportView] = useState("average");

  const zoneId = zones.some(
    (zone) => zone.zone_id === selectedZone
  )
    ? selectedZone : zones[0]?.zone_id || "";

  const zone = zones.find(
    (item) => item.zone_id === zoneId
  );

  const busy = Boolean(exporting);

  async function exportBackend(format) {
    setError("");
    setExporting(format);

    try {
      const limit = zone ? getLimit(zone) : null;

      if (!Number.isFinite(limit)) {
        throw new Error(
          "This zone has no configured temperature limit."
        );
      }

      const end = new Date();

      await downloadReport({
        zoneId,
        limit,
        facility: "",
        format,
        start: new Date(
          end.getTime() - hours * 3600000
        ).toISOString(),
        end: end.toISOString(),
      });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setExporting("");
    }
  }

  async function exportCSV() {
    setError("");
    setExporting("csv");

    try {
      if (!zone) {
        throw new Error("Select an available zone.");
      }

      let rows;

      if (isDemo) {
        rows =
          exportView === "nodes"
            ? (zone.nodes || []).flatMap((sensor) =>
                (sensor.history || []).map((reading) => ({
                  ...reading, 
                  zone_id: zoneId, 
                  node_id: sensor.node_id,
                }))
              )
            : getDemoZoneHistory(zone).map((reading) => ({
                ...reading,
                zone_id: zoneId,
                node_id: "zone_average",
              }));

        const end = Date.now();
        const start = end - hours * 3600000;

        rows = rows.filter((reading) => {
          const time =
            typeof reading.time === "number"
              ? reading.time
              : new Date(
                  reading.timestamp ?? reading.time
                ).getTime();

          return time >= start && time <= end;
        });
      } else {
        if (exportView === "nodes") {
          throw new Error(
            "Individual node history is not available from the current API."
          );
        }

        const history = await getZoneTrend(
          zoneId,
          hours
        );

        rows = history.map((reading) => ({
          ...reading,
          zone_id: zoneId,
          node_id: "zone_average",
        }));
      }

      if (rows.length === 0) {
        throw new Error(
          "No readings available for this reporting period."
        );
      }

      downloadCSV(
        rows,
        `frost-${isDemo ? "DEMO-" : ""}${zoneId}-${
          exportView === "nodes"
            ? "all-nodes"
            : "zone-average"
        }-${hours}h.csv`
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setExporting("");
    }
  }

  return (
    <section className="panel report-panel">
      <h2>Download monitoring reports</h2>

      <p>
        Select a zone, reporting period and download format.
      </p>

      <label>
        Zone
        <select
          value={zoneId}
          disabled={busy}
          onChange={(event) => {
            setSelectedZone(event.target.value);
            setError("");
          }}
        >
          <option value="" disabled>
            Select zone
          </option>

          {zones.map((item) => (
            <option
              key={item.zone_id}
              value={item.zone_id}
            >
              {item.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        Readings
        <select
          value={exportView}
          disabled={busy}
          onChange={(event) => {
            setExportView(event.target.value);
            setError("");
          }}
        >
          <option value="average">
            Zone average
          </option>

          <option
            value="nodes"
            disabled={!isDemo}
          >
            All nodes
            {!isDemo ? " — unavailable" : ""}
          </option>
        </select>
      </label>

      <label>
        Reporting period
        <select
          value={hours}
          disabled={busy}
          onChange={(event) => {
            onHoursChange(Number(event.target.value));
            setError("");
          }}
        >
          {[1, 6, 24, 72, 168].map((value) => (
            <option key={value} value={value}>
              Last {value} {value === 1 ? "hour" : "hours"}
            </option>
          ))}
        </select>
      </label>

      {isDemo && (
        <p className="notice">
          Demo mode supports CSV downloads.
          Select Backend mode for PDF and Excel.
        </p>
      )}

      <div className="report-download-actions">
        <button
          type="button"
          className="primary"
          disabled={busy || !zoneId || isDemo}
          onClick={() => exportBackend("pdf")}
        >
          <Download size={17} aria-hidden="true" />

          {exporting === "pdf"
            ? "Preparing PDF…"
            : "Download PDF"}
        </button>

        <button
          type="button"
          disabled={busy || !zoneId || isDemo}
          onClick={() => exportBackend("excel")}
        >
          <Download size={17} aria-hidden="true" />

          {exporting === "excel"
            ? "Preparing Excel…"
            : "Download Excel"}
        </button>

        <button
          type="button"
          disabled={busy || !zoneId}
          onClick={exportCSV}
        >
          <Download size={17} aria-hidden="true" />

          {exporting === "csv"
            ? "Preparing CSV…"
            : "Download CSV"}
        </button>
      </div>

      {error && (
        <p className="notice danger" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}