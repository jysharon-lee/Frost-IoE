import { useRef, useState } from "react";

import {
  formatValue,
  getTemperatureStatus,
  isFresh,
} from "../utils/data";

import "../styles/zoneLayout.css";

const clamp = (value) =>
  Math.max(3, Math.min(97, Number(value) || 3));

function emptyLayout() {
  return {
    ratio: 1.6,
    labels: [],
    positions: {},
  };
}

function loadLayout(key) {
  try {
    const data = JSON.parse(localStorage.getItem(key));

    if (
      !data ||
      !Array.isArray(data.labels) ||
      !data.positions ||
      typeof data.positions !== "object"
    ) {
      return emptyLayout();
    }

    return {
      ratio: Math.max(
        0.7,
        Math.min(2.5, Number(data.ratio) || 1.6)
      ),

      labels: data.labels
        .filter(
          (label) =>
            label &&
            typeof label.id === "string" &&
            typeof label.text === "string"
        )
        .map((label) => ({
          ...label,
          x: clamp(label.x),
          y: clamp(label.y),
          rotation: Number.isFinite(label.rotation)
            ? label.rotation
            : 0,
          fontSize: Math.max(
            10,
            Math.min(48, Number(label.fontSize) || 13)
          ),
        })),

      positions: Object.fromEntries(
        Object.entries(data.positions)
          .filter(
            ([, position]) =>
              position &&
              Number.isFinite(position.x) &&
              Number.isFinite(position.y)
          )
          .map(([id, position]) => [
            id,
            {
              x: clamp(position.x),
              y: clamp(position.y),
              label:
                typeof position.label === "string"
                  ? position.label
                  : "",
            },
          ])
      ),
    };
  } catch {
    return emptyLayout();
  }
}

export default function ZoneLayout({
  zone,
  node = null,
  isDemo,
  now = Date.now(),
  onSelectNode,
}) {
  const storageKey =
    `frost-layout:v1:${isDemo ? "demo" : "api"}:${zone.zone_id}`;

  const [saved, setSaved] = useState(() =>
    loadLayout(storageKey)
  );

  const [draft, setDraft] = useState(saved);
  const [editing, setEditing] = useState(false);
  const [selectedLabel, setSelectedLabel] = useState("");
  const [error, setError] = useState("");

  const roomRef = useRef(null);
  const gestureRef = useRef(null);
  const textInputRef = useRef(null);

  const layout = editing ? draft : saved;
  const nodes = zone.nodes || [];

  const position = node
    ? layout.positions[node.node_id]
    : null;

  const activeLabel = layout.labels.find(
    (label) => label.id === selectedLabel
  );

  const unplacedNodes = nodes.filter(
    (sensor) => !layout.positions[sensor.node_id]
  );

  function beginEditing() {
    setDraft(structuredClone(saved));
    setSelectedLabel("");
    setError("");
    setEditing(true);
  }

  function saveLayout() {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify(draft)
      );

      setSaved(draft);
      setEditing(false);
      setError("");
    } catch {
      setError(
        "Unable to save in this browser. Your changes are still open."
      );
    }
  }

  function cancelEditing() {
    setDraft(saved);
    setEditing(false);
    setError("");
  }

  function updateNodePosition(changes) {
    if (!node) return;

    setDraft((previous) => ({
      ...previous,

      positions: {
        ...previous.positions,

        [node.node_id]: {
          ...(previous.positions[node.node_id] || {
            x: 50,
            y: 50,
            label: "",
          }),
          ...changes,
        },
      },
    }));
  }

  function removeNodePosition() {
    setDraft((previous) => {
      const positions = { ...previous.positions };

      delete positions[node.node_id];

      return {
        ...previous,
        positions,
      };
    });
  }

  function addRoomLabel() {
    const id = crypto.randomUUID();

    setDraft((previous) => ({
      ...previous,

      labels: [
        ...previous.labels,
        {
          id,
          text: "Door",
          x: 50,
          y: 85,
          rotation: 0,
          fontSize: 13,
        },
      ],
    }));

    setSelectedLabel(id);
  }

  function updateRoomLabel(
    changes,
    id = selectedLabel
  ) {
    setDraft((previous) => ({
      ...previous,

      labels: previous.labels.map((label) =>
        label.id === id
          ? { ...label, ...changes }
          : label
      ),
    }));
  }

  function deleteRoomLabel() {
    setDraft((previous) => ({
      ...previous,

      labels: previous.labels.filter(
        (label) => label.id !== selectedLabel
      ),
    }));

    setSelectedLabel("");
  }

  function pointInRoom(event) {
    const room = roomRef.current;
    const bounds = room.getBoundingClientRect();

    return {
      x: event.clientX - bounds.left - room.clientLeft,
      y: event.clientY - bounds.top - room.clientTop,
      width: room.clientWidth,
      height: room.clientHeight,
    };
  }

  function beginLabelGesture(
    event,
    label,
    mode = "move"
  ) {
    if (!editing || node || event.button !== 0) return;

    event.preventDefault();
    event.stopPropagation();

    setSelectedLabel(label.id);

    const point = pointInRoom(event);
    const cx = (point.width * label.x) / 100;
    const cy = (point.height * label.y) / 100;

    gestureRef.current = {
      id: label.id,
      mode,
      pointerId: event.pointerId,
      startX: point.x,
      startY: point.y,
      x: label.x,
      y: label.y,
      cx,
      cy,
      angle: Math.atan2(
        point.y - cy,
        point.x - cx
      ),
      distance: Math.max(
        1,
        Math.hypot(point.x - cx, point.y - cy)
      ),
      rotation: label.rotation || 0,
      fontSize: label.fontSize || 13,
    };

    roomRef.current.setPointerCapture(event.pointerId);
  }

  function handlePointerDown(event) {
    if (!editing || event.button !== 0) return;

    if (!node) {
      // Clicking blank space deselects the label.
      setSelectedLabel("");
      return;
    }

    event.preventDefault();

    const point = pointInRoom(event);

    updateNodePosition({
      x: clamp((point.x / point.width) * 100),
      y: clamp((point.y / point.height) * 100),
    });

    gestureRef.current = {
      mode: "node",
      pointerId: event.pointerId,
    };

    event.currentTarget.setPointerCapture(
      event.pointerId
    );
  }

  function handlePointerMove(event) {
    const gesture = gestureRef.current;

    if (
      !gesture ||
      gesture.pointerId !== event.pointerId
    ) {
      return;
    }

    const point = pointInRoom(event);

    if (gesture.mode === "node") {
      updateNodePosition({
        x: clamp((point.x / point.width) * 100),
        y: clamp((point.y / point.height) * 100),
      });
    } else if (gesture.mode === "move") {
      updateRoomLabel(
        {
          x: clamp(
            gesture.x +
              ((point.x - gesture.startX) /
                point.width) *
                100
          ),
          y: clamp(
            gesture.y +
              ((point.y - gesture.startY) /
                point.height) *
                100
          ),
        },
        gesture.id
      );
    } else if (gesture.mode === "resize") {
      const distance = Math.hypot(
        point.x - gesture.cx,
        point.y - gesture.cy
      );

      updateRoomLabel(
        {
          fontSize: Math.max(
            10,
            Math.min(
              48,
              Math.round(
                (gesture.fontSize * distance) /
                  gesture.distance
              )
            )
          ),
        },
        gesture.id
      );
    } else if (gesture.mode === "rotate") {
      const angle = Math.atan2(
        point.y - gesture.cy,
        point.x - gesture.cx
      );

      let rotation =
        gesture.rotation +
        ((angle - gesture.angle) * 180) / Math.PI;

      if (event.shiftKey) {
        rotation = Math.round(rotation / 15) * 15;
      }

      rotation = Math.round(
        ((rotation % 360) + 360) % 360
      );

      updateRoomLabel(
        { rotation },
        gesture.id
      );
    }
  }

  function endGesture(event) {
    if (
      gestureRef.current?.pointerId !== event.pointerId
    ) {
      return;
    }

    gestureRef.current = null;

    const room = roomRef.current;

    if (room?.hasPointerCapture(event.pointerId)) {
      room.releasePointerCapture(event.pointerId);
    }
  }

  function markerTone(sensor) {
    if (!isFresh(sensor, now)) {
      return "stale";
    }

    const status = getTemperatureStatus(
      sensor.temp_c,
      zone.limits
    );

    if (status === "Within limits") {
      return "normal";
    }

    if (
      status === "Above limit" ||
      status === "Below limit"
    ) {
      return "breach";
    }

    return "unknown";
  }

  return (
    <section className="panel zone-layout">
      <div className="panel-heading">
        {!node && <h3>Zone layout</h3>}

        {!editing && (
          <button
            type="button"
            className="layout-edit-button"
            onClick={beginEditing}
          >
            {node
              ? "Edit location"
              : "Edit room labels"}
          </button>
        )}
      </div>

      <p className="muted">
        {zone.name} · Schematic room layout, not to scale.
      </p>

      {editing && (
        <div className="layout-controls">
          {node ? (
            <>
              <p>
                Click or drag on the map to position this node.
              </p>

              <div className="layout-location-row">
                <label>
                  Location label
                  <input
                    value={position?.label || ""}
                    maxLength={80}
                    placeholder="e.g. Beside entrance"
                    onChange={(event) =>
                      updateNodePosition({
                        label: event.target.value,
                      })
                    }
                  />
                </label>

                <button
                  type="button"
                  className="layout-remove-button"
                  onClick={removeNodePosition}
                >
                  Remove location
                </button>
              </div>
            </>
          ) : (
            <>
              <label>
                Room width-to-height ratio
                <input
                  type="number"
                  min="0.7"
                  max="2.5"
                  step="0.1"
                  value={draft.ratio}
                  onChange={(event) => {
                    const ratio = Math.max(
                      0.7,
                      Math.min(
                        2.5,
                        Number(event.target.value) || 1.6
                      )
                    );

                    setDraft((previous) => ({
                      ...previous,
                      ratio,
                    }));
                  }}
                />
              </label>

              <div className="layout-label-toolbar">
                <strong>Room labels</strong>

                <button
                  type="button"
                  className="layout-add-label"
                  onClick={addRoomLabel}
                >
                  <span aria-hidden="true">＋</span>
                  Add room label
                </button>
              </div>

              <div className="layout-label-grid">
                {draft.labels.map((label) => (
                  <button
                    type="button"
                    key={label.id}
                    aria-pressed={
                      label.id === selectedLabel
                    }
                    onClick={() =>
                      setSelectedLabel(label.id)
                    }
                  >
                    {label.text || "Unnamed label"}
                  </button>
                ))}
              </div>

              {activeLabel && (
                <>
                  <label>
                    Label text
                    <input
                      ref={textInputRef}
                      value={activeLabel.text}
                      maxLength={60}
                      onChange={(event) =>
                        updateRoomLabel({
                          text: event.target.value,
                        })
                      }
                    />
                  </label>

                  <div className="layout-label-properties">
                    <label>
                      Text size
                      <input
                        type="number"
                        min="10"
                        max="48"
                        step="1"
                        value={activeLabel.fontSize || 13}
                        onChange={(event) =>
                          updateRoomLabel({
                            fontSize: Math.max(
                              10,
                              Math.min(
                                48,
                                Number(event.target.value) || 13
                              )
                            ),
                          })
                        }
                      />
                    </label>

                    <label>
                      Rotation (°)
                      <input
                        type="number"
                        min="0"
                        max="359"
                        step="1"
                        value={activeLabel.rotation || 0}
                        onChange={(event) =>
                          updateRoomLabel({
                            rotation:
                              (((Number(event.target.value) || 0) %
                                360) +
                                360) %
                              360,
                          })
                        }
                      />
                    </label>

                    <button
                      type="button"
                      className="layout-delete-label"
                      onClick={deleteRoomLabel}
                    >
                      Delete label
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      )}

      <div
        ref={roomRef}
        className={`layout-room ${
          editing ? "editing" : ""
        }`}
        style={{ aspectRatio: layout.ratio }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        onLostPointerCapture={endGesture}
      >
        {layout.labels.map((label) => {
          const editable = editing && !node;
          const selected =
            editable && selectedLabel === label.id;

          return (
            <div
              key={label.id}
              className={`room-label ${
                editable ? "editable" : ""
              } ${selected ? "active" : ""}`}
              style={{
                left: `${label.x}%`,
                top: `${label.y}%`,
                fontSize: `${(label.fontSize || 13) / 8}cqw`,
                transform:
                  `translate(-50%, -50%) rotate(${
                    label.rotation || 0
                  }deg)`,
              }}
              onPointerDown={(event) =>
                beginLabelGesture(event, label)
              }
              onDoubleClick={() => {
                if (editable) {
                  setSelectedLabel(label.id);

                  requestAnimationFrame(() =>
                    textInputRef.current?.focus()
                  );
                }
              }}
              tabIndex={editable ? 0 : undefined}
              role={editable ? "group" : undefined}
              aria-label={
                editable
                  ? `Room label: ${
                      label.text || "Unnamed"
                    }. Arrow keys move; Shift and arrows move faster.`
                  : undefined
              }
              onFocus={() => {
                if (editable) {
                  setSelectedLabel(label.id);
                }
              }}
              onKeyDown={(event) => {
                if (
                  !editable ||
                  event.target !== event.currentTarget
                ) {
                  return;
                }

                const delta = event.shiftKey ? 2 : 0.5;

                const directions = {
                  ArrowLeft: [-delta, 0],
                  ArrowRight: [delta, 0],
                  ArrowUp: [0, -delta],
                  ArrowDown: [0, delta],
                };

                if (directions[event.key]) {
                  event.preventDefault();

                  const [dx, dy] = directions[event.key];

                  updateRoomLabel(
                    {
                      x: clamp(label.x + dx),
                      y: clamp(label.y + dy),
                    },
                    label.id
                  );
                }

                if (event.key === "Enter") {
                  event.preventDefault();
                  textInputRef.current?.focus();
                }
              }}
            >
              <span>
                {label.text || "Unnamed label"}
              </span>

              {selected && (
                <>
                  <span
                    className="label-rotation-stem"
                    aria-hidden="true"
                  />

                  <button
                    type="button"
                    className="label-handle label-rotate"
                    aria-label={`Rotate ${label.text}`}
                    title="Drag to rotate · Shift: snap to 15°"
                    onPointerDown={(event) =>
                      beginLabelGesture(
                        event,
                        label,
                        "rotate"
                      )
                    }
                  />

                  {["nw", "ne", "sw", "se"].map(
                    (corner) => (
                      <button
                        key={corner}
                        type="button"
                        className={`label-handle label-resize ${corner}`}
                        aria-label={
                          `Resize ${label.text}, ${corner} corner`
                        }
                        title="Drag to resize text"
                        onPointerDown={(event) =>
                          beginLabelGesture(
                            event,
                            label,
                            "resize"
                          )
                        }
                      />
                    )
                  )}
                </>
              )}
            </div>
          );
        })}

        {nodes.map((sensor) => {
          const point =
            layout.positions[sensor.node_id];

          if (!point) return null;

          const faded =
            node && sensor.node_id !== node.node_id;

          return (
            <button
              type="button"
              key={sensor.node_id}
              className={`layout-marker ${markerTone(
                sensor
              )} ${faded ? "faded" : ""}`}
              style={{
                left: `${point.x}%`,
                top: `${point.y}%`,
              }}
              title={[
                sensor.name,
                point.label || "No location label",
                formatValue(sensor.temp_c, "°C"),
                formatValue(sensor.humidity, "% RH"),
              ].join(" · ")}
              aria-label={`${sensor.name}, ${
                point.label || "Location placed"
              }. Open node details`}
              onClick={() => {
                if (!editing) {
                  onSelectNode?.(sensor.node_id);
                }
              }}
            >
              <span aria-hidden="true">●</span>
              <small>{sensor.name}</small>
            </button>
          );
        })}

        {layout.labels.length === 0 &&
          !nodes.some(
            (sensor) =>
              layout.positions[sensor.node_id]
          ) && (
            <span className="layout-empty">
              {node
                ? "Edit location to place this node"
                : "Add room labels, then place nodes from their node pages"}
            </span>
          )}
      </div>

      <p className="layout-legend">
        Green: within limits · Red: outside limits ·
        Grey: stale or unavailable
      </p>

      {node && (
        <p>
          <b>{node.name}:</b>{" "}
          {position
            ? position.label || "Location placed; no label"
            : "Location not set"}
        </p>
      )}

      {!node && unplacedNodes.length > 0 && (
        <div className="layout-unplaced">
          <strong>
            Location not set · {unplacedNodes.length} nodes
          </strong>

          <p>Select a node to set its location.</p>

          <div className="layout-unplaced-actions">
            {unplacedNodes.map((sensor) => (
              <button
                type="button"
                key={sensor.node_id}
                onClick={() =>
                  onSelectNode?.(sensor.node_id)
                }
              >
                {sensor.name}
                <span>Set location →</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {editing && (
        <div className="layout-actions layout-save-actions">
          <button
            type="button"
            className="primary"
            onClick={saveLayout}
          >
            Save {node ? "location" : "layout"}
          </button>

          <button
            type="button"
            onClick={cancelEditing}
          >
            Cancel
          </button>
        </div>
      )}

      {error && (
        <p className="notice danger" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}