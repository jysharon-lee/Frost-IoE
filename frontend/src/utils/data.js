/* Reading validation and freshness */
export const FRESHNESS_LIMIT = 30_000; // keep equal to backend STALE_AFTER_S

export function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export function isFresh(reading, now = Date.now()) {
  const timestamp = Date.parse(reading?.timestamp);

  return (
    Number.isFinite(timestamp) &&
    now - timestamp <= FRESHNESS_LIMIT &&
    timestamp - now <= 30_000
  );
}

/* Trend label from °C/hour. Within ±TREND_LIMIT counts as stable. */
export const TREND_LIMIT = 1;

export function getTrend(rate) {
  if (!isNumber(rate)) return null;
  if (rate > TREND_LIMIT) return { text: "↑ Rising", tone: "up" };
  if (rate < -TREND_LIMIT) return { text: "↓ Dropping", tone: "down" };
  return { text: "→ Stable", tone: "flat" };
}

/* Value and date formatting */
export function formatValue(value, unit = "") {
  return isNumber(value)
    ? `${value.toFixed(1)}${unit}`
    : "—";
}

export function formatTime(value) {
  return new Date(value).toLocaleTimeString("en-MY", {
    timeZone: "Asia/Kuching",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDateTime(value) {
  if (!value) {
    return "Not received";
  }

  return new Date(value).toLocaleString("en-MY", {
    timeZone: "Asia/Kuching",
  });
}

/* Temperature status */
export function getTemperatureStatus(temperature, limits) {
  if (!isNumber(temperature)) {
    return "No data";
  }

  if (!limits) {
    return "Limits unavailable";
  }

  if (isNumber(limits.max) && temperature > limits.max) {
    return "Above limit";
  }

  if (isNumber(limits.min) && temperature < limits.min) {
    return "Below limit";
  }

  return "Within limits";
}

export function formatLimits(limits) {
  const hasMin = isNumber(limits?.min);
  const hasMax = isNumber(limits?.max);

  if (hasMin && hasMax) return `${limits.min} to ${limits.max} °C`;
  if (hasMax) return `≤ ${limits.max} °C`;
  if (hasMin) return `≥ ${limits.min} °C`;
  return "Unavailable";
}

/* Warmest node with a recent valid reading (null if none) */
export function getWorstNode(nodes, now = Date.now()) {
  return nodes
    .filter((node) => isFresh(node, now) && isNumber(node.temp_c))
    .reduce(
      (worst, node) =>
        !worst || node.temp_c > worst.temp_c ? node : worst,
      null
    );
}

/* Outage messages: whole site, whole zone, or single sensor */
export function getOutages(zones, now = Date.now()) {
  const down = (node) =>
    !isFresh(node, now) || !isNumber(node.temp_c);

  const zoneDown = (zone) =>
    zone.nodes?.length
      ? zone.nodes.every(down)
      : !isFresh(zone, now);

  const downZones = zones.filter(zoneDown);

  if (zones.length && downZones.length === zones.length) {
    return ["Power down"];
  }

  return zones.flatMap((zone) =>
    downZones.includes(zone)
      ? [`${zone.name} down`]
      : (zone.nodes || [])
          .filter(down)
          .map((node) => `${node.name} in ${zone.name} down`)
  );
}

/* Current zone readings */
export function getAverage(nodes, field, now = Date.now()) {
  const values = nodes
    .filter(
      (node) =>
        isFresh(node, now) &&
        isNumber(node[field])
    )
    .map((node) => node[field]);

  if (values.length === 0) {
    return null;
  }

  const total = values.reduce(
    (sum, value) => sum + value,
    0
  );

  return total / values.length;
}

export function getZoneSummary(zone, now = Date.now()) {
  // Use the zone reading when individual nodes are absent.
  if (!zone.nodes?.length) {
    return {
      temp_c: zone.temp_c,
      humidity: zone.humidity,
      rate_c_per_hour: zone.rate_c_per_hour,
      reporting: null,
      total: null,
    };
  }

  return {
    temp_c: getAverage(zone.nodes, "temp_c", now),
    humidity: getAverage(zone.nodes, "humidity", now),
    rate_c_per_hour: getAverage(zone.nodes, "rate_c_per_hour", now),

    reporting: zone.nodes.filter(
      (node) =>
        isFresh(node, now) &&
        isNumber(node.temp_c)
    ).length,

    total: zone.nodes.length,
  };
}

/* Chart history preparation */
export function addHistoryGaps(
  readings,
  interval = 300_000
) {
  const sorted = readings
    .map((reading) => ({
      ...reading,
      time: Date.parse(reading.timestamp),
    }))
    .filter((reading) => Number.isFinite(reading.time))
    .sort((a, b) => a.time - b.time);

  const result = [];

  for (const reading of sorted) {
    const previous = result.at(-1);

    if (
      previous &&
      reading.time - previous.time > interval * 1.5
    ) {
      result.push({
        time: previous.time + interval,
        temp_c: null,
        humidity: null,
      });
    }

    result.push(reading);
  }

  return result;
}

export function getComparisonHistory(
  zone,
  field = "temp_c"
) {
  const nodes = zone.nodes || [];

  if (!nodes.length) {
    return [];
  }

  // Match readings by timestamp across nodes.
  const points = new Map();

  nodes.forEach((node) => {
    (node.history || []).forEach((reading) => {
      const time = Date.parse(reading.timestamp);

      if (!Number.isFinite(time)) {
        return;
      }

      if (!points.has(time)) {
        const point = { time };

        nodes.forEach((sensor) => {
          point[sensor.node_id] = null;
        });

        points.set(time, point);
      }

      points.get(time)[node.node_id] =
        isNumber(reading[field])
          ? reading[field]
          : null;
    });
  });

  return [...points.values()].sort(
    (a, b) => a.time - b.time
  );
}

/* Demo data generation */
export function createDemoZones(hours = 24) {
  const now = Date.now();

  const configurations = [
    {
      zone_id: "zone_a",
      name: "Zone 1",
      type: "Frozen storage",
      limits: { max: -18 },
      temperatures: [-20, -19.5, -20, -16.5],
    },
    {
      zone_id: "zone_b",
      name: "Zone 2",
      type: "Chilled storage",
      limits: { min: -1, max: 10 },
      temperatures: [3.2, 4.1, 3.7, 4.6],
    },
  ];

  return configurations.map((configuration) => {
    const nodes = configuration.temperatures.map(
      (base, nodeIndex) => {
        const pointCount = hours * 12;

        const history = Array.from(
          { length: pointCount + 1 },
          (_, pointIndex) => {
            const progress = pointIndex / pointCount;

            const risingTemperature =
              configuration.zone_id === "zone_a" &&
              nodeIndex === 3;

            const temperature =
              base +
              (risingTemperature
                ? -3.5 * (1 - progress)
                : 0) +
              Math.sin(pointIndex * 0.6 + nodeIndex) * 0.1;

            const humidity =
              80 +
              (nodeIndex - 1.5) * 1.2 +
              Math.sin(pointIndex * 0.25) * 0.6;

            return {
              timestamp: new Date(
                now -
                  (pointCount - pointIndex) * 300_000
              ).toISOString(),

              temp_c: Number(temperature.toFixed(2)),
              humidity: Number(humidity.toFixed(1)),
            };
          }
        );

        return {
          node_id: `node_${nodeIndex + 1}`,
          name: `Sensor ${nodeIndex + 1}`,
          location: [
            "Near door",
            "Back wall",
            "Beside evaporator fan",
            "Room centre",
          ][nodeIndex],

          ...history.at(-1),

          health: "Healthy",
          power_ok: true,

          // Illustrative trend only: one rising, one dropping, rest stable.
          rate_c_per_hour:
            configuration.zone_id === "zone_a" && nodeIndex === 3
              ? 2.4
              : configuration.zone_id === "zone_b" && nodeIndex === 1
                ? -1.6
                : 0.1,

          history,
        };
      }
    );

    return {
      ...configuration,
      nodes,
      timestamp: new Date(now).toISOString(),
      power_ok: true,
    };
  });
}

/* Demo zone averages */
export function getDemoZoneHistory(zone) {
  // Generated demo histories have aligned timestamps.
  return zone.nodes[0].history.map((reading, index) => ({
    timestamp: reading.timestamp,

    temp_c:
      zone.nodes.reduce(
        (total, node) =>
          total + node.history[index].temp_c,
        0
      ) / zone.nodes.length,

    humidity:
      zone.nodes.reduce(
        (total, node) =>
          total + node.history[index].humidity,
        0
      ) / zone.nodes.length,
  }));
}

/* CSV download */
export function downloadCSV(readings, filename) {
  const columns = [
    "timestamp",
    "zone_id",
    "node_id",
    "temp_c",
    "humidity",
  ];

  const escape = (value) =>
    `"${String(value ?? "").replaceAll('"', '""')}"`;

  const rows = [
    columns.join(","),

    ...readings.map((reading) =>
      columns
        .map((column) => escape(reading[column]))
        .join(",")
    ),
  ];

  const blob = new Blob(
    ["\uFEFF" + rows.join("\r\n")],
    {
      type: "text/csv;charset=utf-8;",
    }
  );

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  link.click();

  setTimeout(() => URL.revokeObjectURL(url), 1000);
}