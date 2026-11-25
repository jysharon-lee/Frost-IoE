import { useState } from "react";
import { TriangleAlert } from "lucide-react";

import Header from "./components/Header";
import Sidebar from "./components/Sidebar";

import NodePage from "./pages/NodePage";
import OverviewPage from "./pages/OverviewPage";
import ReportsPage from "./pages/ReportsPage";
import ZonePage from "./pages/ZonePage";

import {
  useCurrentTime,
  useFaultySensors,
  useLiveZones,
  useSite,
  useZoneHistory,
} from "./hooks/useDashboardData";

import {
  getOutages,
  getTemperatureStatus,
  isDown,
  isFresh,
  isNumber,
} from "./utils/data";

export default function App() {
  /* Navigation and display settings */
  const [mode, setMode] = useState("api");
  const [page, setPage] = useState("overview");
  const [selectedNode, setSelectedNode] = useState("overview");
  const [hours, setHours] = useState(24);
  const [refreshKey, setRefreshKey] = useState(0);

  /* Temperature limit settings */
  const [zoneLimits, setZoneLimits] = useState({});

  function getLimit(item) {
    return Object.hasOwn(zoneLimits, item.zone_id)
      ? zoneLimits[item.zone_id]
      : item.limits?.max ?? null;
  }

  function setLimit(zoneId, limit) {
    setZoneLimits((previous) => ({
      ...previous,
      [zoneId]: limit,
    }));
  }

  /* Live readings and selected zone */
  const now = useCurrentTime();
  const isDemo = mode === "demo";

  const live = useLiveZones(mode, hours, refreshKey);
  const site = useSite();
  const faulty = useFaultySensors(mode, refreshKey);
  const outages = getOutages(live.zones, now);

  const rawZone = live.zones.find(
    (item) => item.zone_id === page
  );

  const zone = rawZone
    ? {
        ...rawZone,
        limits: Number.isFinite(getLimit(rawZone))
          ? {
              ...rawZone.limits,
              max: getLimit(rawZone),
            }
          : rawZone.limits,
      }
    : null;

  const node = zone?.nodes.find(
    (item) => item.node_id === selectedNode
  );

  const trend = useZoneHistory(
    mode,
    zone?.zone_id,
    hours,
    refreshKey,
    node?.node_id
  );

  /* Nodes currently outside their zone limits */
  const breaches = live.zones.flatMap((item) =>
    item.nodes
      .filter(
        (sensor) =>
          isFresh(sensor, now) &&
          isNumber(sensor.temp_c) &&
          getTemperatureStatus(
            sensor.temp_c,
            item.limits
          ) !== "Within limits"
      )
      .map((sensor) => ({
        zone: item,
        node: sensor,
      }))
  );

  /* Navigation handlers */
  function navigate(nextPage) {
    setPage(nextPage);
    setSelectedNode("overview");
  }

  function openNode(zoneId, nodeId) {
    setPage(zoneId);
    setSelectedNode(nodeId);
  }

  function changeMode(nextMode) {
    setMode(nextMode);
    setSelectedNode("overview");
  }

  /* Page title and shared detail properties */
  const title =
    page === "overview"
      ? "Cold Storage Overview"
      : page === "reports"
        ? "Monitoring Reports"
        : zone?.name || "Zone unavailable";

  const detailProps = {
    zone,
    isDemo,
    hours,
    onHoursChange: setHours,
    history: trend.history,
    historyLoading: trend.loading,
    historyError: trend.error,
    breaches,
    now,
    onSelectNode: setSelectedNode,
    upperLimit: zone ? getLimit(zone) : null,
    onLimitChange: (value) =>
      setLimit(zone.zone_id, value),
    refreshKey,
  };

  return (
    <div className="app">
      <Sidebar
        zones={live.zones}
        now={now}
        page={page}
        onNavigate={navigate}
      />

      <main>
        <Header
          company={site?.company}
          title={title}
          subtitle={
            zone?.type ||
            "Monitor conditions and identify zones needing attention."
          }
          mode={mode}
          onModeChange={changeMode}
          onRefresh={() =>
            setRefreshKey((value) => value + 1)
          }
          loading={live.loading}
          lastRefresh={live.lastRefresh}
        />

        {/* Loading and request errors */}
        {live.error && (
          <div className="notice danger" role="alert">
            {live.error}{" "}
            {live.lastRefresh
              ? "Showing last available readings. Check their timestamps."
              : "No readings loaded."}
          </div>
        )}

        {outages.length > 0 && (
          <div className="notice danger" role="alert">
            <TriangleAlert size={19} />
            <span>
              {outages.join(" · ")}. Nodes may be logging
              locally and will sync when the link returns.
            </span>
          </div>
        )}

        {live.loading && live.zones.length === 0 && (
          <div className="empty" role="status">
            Loading readings…
          </div>
        )}

        {/* Dashboard overview */}
        {page === "overview" && (
          <OverviewPage
            zones={live.zones}
            isDemo={isDemo}
            breaches={breaches}
            faulty={faulty}
            now={now}
            onOpenZone={navigate}
            onOpenNode={openNode}
          />
        )}

        {/* Zone overview and individual node views */}
        {zone && (
          <>
            <div
              className="tabs"
              aria-label="Zone views"
            >
              <button
                className={
                  selectedNode === "overview"
                    ? "selected"
                    : ""
                }
                aria-pressed={
                  selectedNode === "overview"
                }
                onClick={() =>
                  setSelectedNode("overview")
                }
              >
                Overview
              </button>

              {zone.nodes.map((sensor) => {
                const down = isDown(sensor, now);
                const check =
                  !down &&
                  faulty.has(`${zone.zone_id}/${sensor.node_id}`);

                return (
                  <button
                    key={sensor.node_id}
                    className={
                      selectedNode === sensor.node_id
                        ? "selected"
                        : ""
                    }
                    aria-pressed={
                      selectedNode === sensor.node_id
                    }
                    aria-label={
                      down
                        ? `${sensor.name}, offline`
                        : check
                          ? `${sensor.name}, check sensor`
                          : undefined
                    }
                    onClick={() =>
                      setSelectedNode(sensor.node_id)
                    }
                  >
                    {sensor.name}

                    {(down || check) && (
                      <i className="tab-down">
                        {down ? "Offline" : "Check sensor"}
                      </i>
                    )}
                  </button>
                );
              })}
            </div>

            {node ? (
              <NodePage
                {...detailProps}
                node={node}
              />
            ) : (
              <ZonePage {...detailProps} />
            )}
          </>
        )}

        {/* Reports */}
        {page === "reports" && (
          <ReportsPage
            zones={live.zones}
            isDemo={isDemo}
            hours={hours}
            onHoursChange={setHours}
            getLimit={getLimit}
          />
        )}

        {/* Empty data state */}
        {!live.loading &&
          !live.error &&
          live.zones.length === 0 && (
            <div className="empty">
              No zones returned. Check the backend or select demo mode.
            </div>
          )}

        <footer>
          <span>©2026, FROST-IoE</span>

          <span>
            Cold Storage Monitoring · Malaysia Time (UTC+8)
          </span>
        </footer>
      </main>
    </div>
  );
}