import {
  ChevronRight,
  FileText,
  LayoutDashboard,
  Radio,
  Snowflake,
  Warehouse,
} from "lucide-react";

import { getLimitState } from "../utils/data";

export default function Sidebar({
  zones,
  now,
  page,
  onNavigate,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <Snowflake size={35} />

        <div>
          FROST-IoE
          <small>
            Poultry cold-storage monitoring
          </small>
        </div>
      </div>

      <p className="navigation-label">
        WORKSPACE
      </p>

      <nav aria-label="Main navigation">
        <button
          className={
            page === "overview" ? "active" : ""
          }
          onClick={() => onNavigate("overview")}
        >
          <LayoutDashboard size={19} />
          Overview
        </button>

        {zones.map((zone) => {
          const { tone, outside, total } = getLimitState(zone, now);

          return (
            <button
              key={zone.zone_id}
              className={
                page === zone.zone_id ? "active" : ""
              }
              onClick={() => onNavigate(zone.zone_id)}
            >
              <Warehouse size={19} />

              <span>{zone.name}</span>

              {tone && (
                <i
                  className={`zone-dot ${tone}`}
                  role="img"
                  aria-label={`${outside} of ${total} nodes outside limits`}
                  title={`${outside} of ${total} nodes outside limits`}
                />
              )}

              <ChevronRight size={16} />
            </button>
          );
        })}

        <button
          className={
            page === "reports" ? "active" : ""
          }
          onClick={() => onNavigate("reports")}
        >
          <FileText size={19} />
          Reports
        </button>
      </nav>

      <div className="sidebar-footer">
        <Radio size={18} />

        <div>
          10-second refresh
          <small>MYT · UTC+08:00</small>
        </div>
      </div>
    </aside>
  );
}