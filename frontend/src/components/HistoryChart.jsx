import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  formatDateTime,
  formatTime,
  formatValue,
  isNumber,
} from "../utils/data";

const COLOURS = [
  "#078c95", // Teal
  "#5378d6", // Blue
  "#9962cb", // Purple
  "#d97706", // Orange
  "#db2777", // Pink
  "#64748b", // Slate
  "#65a30d", // Green
  "#92400e", // Brown
];

export default function HistoryChart({
  title,
  data,
  humidity = false,
  limits,
  nodes,
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h3>{title}</h3>

        <span>
          {humidity ? "% RH" : "°C"} · MYT
        </span>
      </div>

      {data.length === 0 ? (
        <div className="empty">
          No history available.
        </div>
      ) : (
        <div className="chart">
          <ResponsiveContainer
            width="100%"
            height="100%"
          >
            <LineChart
              data={data}
              margin={{
                top: 20,
                right: 25,
                left: 0,
                bottom: 10,
              }}
            >
              <CartesianGrid
                vertical={false}
                stroke="#e4ebf2"
                strokeDasharray="3 3"
              />

              <XAxis
                dataKey="time"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={formatTime}
                minTickGap={40}
                tick={{ fontSize: 11 }}
              />

              <YAxis
                width={45}
                domain={
                  humidity
                    ? [0, 100]
                    : ["auto", "auto"]
                }
                tick={{ fontSize: 11 }}
              />

              <Tooltip
                labelFormatter={formatDateTime}
                formatter={(value, name) => [
                  formatValue(
                    value,
                    humidity ? "% RH" : "°C"
                  ),
                  name,
                ]}
              />

              {!humidity && isNumber(limits?.max) && (
                <ReferenceLine
                  y={limits.max}
                  ifOverflow="extendDomain"
                  stroke="#bb3c50"
                  strokeDasharray="5 5"
                  label={{
                    value: `Maximum ${limits.max}°C`,
                    position: "insideTopRight",
                    fontSize: 11,
                  }}
                />
              )}

              {!humidity && isNumber(limits?.min) && (
                <ReferenceLine
                  y={limits.min}
                  ifOverflow="extendDomain"
                  stroke="#bb3c50"
                  strokeDasharray="5 5"
                  label={{
                    value: `Minimum ${limits.min}°C`,
                    position: "insideBottomRight",
                    fontSize: 11,
                  }}
                />
              )}

              {nodes ? (
                <>
                  <Legend />

                  {nodes.map((node, index) => (
                    <Line
                      key={node.node_id}
                      dataKey={node.node_id}
                      name={node.name}
                      stroke={
                        COLOURS[index % COLOURS.length]
                      }
                      strokeWidth={2}
                      dot={false}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  ))}
                </>
              ) : (
                <Line
                  dataKey={
                    humidity ? "humidity" : "temp_c"
                  }
                  name={
                    humidity ? "Humidity" : "Temperature"
                  }
                  stroke={
                    humidity ? "#4e8bd7" : "#078c95"
                  }
                  strokeWidth={2.3}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}