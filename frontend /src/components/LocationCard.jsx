import {
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { MapPin, X } from "lucide-react";

import ZoneLayout from "./ZoneLayout";

import "../styles/locationCard.css";

function readLayout(key) {
  try {
    const data = JSON.parse(localStorage.getItem(key));

    return {
      ratio: Math.max(
        0.7,
        Math.min(2.5, Number(data?.ratio) || 1.6)
      ),

      labels: Array.isArray(data?.labels)
        ? data.labels.filter(
            (label) =>
              label &&
              typeof label.text === "string" &&
              Number.isFinite(label.x) &&
              Number.isFinite(label.y)
          )
        : [],

      positions:
        data?.positions &&
        typeof data.positions === "object"
          ? data.positions
          : {},
    };
  } catch {
    return {
      ratio: 1.6,
      labels: [],
      positions: {},
    };
  }
}

function hasPosition(position) {
  return (
    Number.isFinite(position?.x) &&
    Number.isFinite(position?.y)
  );
}

const clamp = (value) =>
  Math.max(3, Math.min(97, value));

export default function LocationCard({
  zone,
  node = null,
  isDemo,
  now,
  onSelectNode,
}) {
  const storageKey =
    `frost-layout:v1:${isDemo ? "demo" : "api"}:${zone.zone_id}`;

  const [layout, setLayout] = useState(() =>
    readLayout(storageKey)
  );

  const [open, setOpen] = useState(false);

  const dialogRef = useRef(null);
  const triggerRef = useRef(null);
  const titleId = useId();

  const nodes = zone.nodes || [];

  const positionedNodes = nodes.filter((sensor) =>
    hasPosition(layout.positions[sensor.node_id])
  );

  // Refresh the preview when changing zones or data mode.
  useEffect(() => {
    setLayout(readLayout(storageKey));
  }, [storageKey]);

  useEffect(() => {
    if (!open) return;

    const dialog = dialogRef.current;

    if (dialog && !dialog.open) {
      dialog.showModal();
    }

    const previousOverflow =
      document.body.style.overflow;

    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow =
        previousOverflow;

      if (dialog?.open) {
        dialog.close();
      }
    };
  }, [open]);

  function closePopup() {
    // Refresh the miniature map after saving in the popup.
    setLayout(readLayout(storageKey));
    setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        className="panel location-card location-preview-card"
        ref={triggerRef}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-label={`Open ${
          node
            ? `${node.name} location`
            : `${zone.name} layout`
        }`}
      >
        <span className="location-card-heading">
          <MapPin size={18} aria-hidden="true" />

          <span>
            {node ? "Location" : "Zone layout"}
          </span>
        </span>

        {/* Miniature room map. */}
        <span
          className="location-preview-area"
          aria-hidden="true"
        >
          <span
            className="location-mini-room"
            style={{ aspectRatio: layout.ratio }}
          >
            {layout.labels.map((label, index) => (
              <span
                key={label.id || index}
                className="location-mini-label"
                style={{
                  left: `${clamp(label.x)}%`,
                  top: `${clamp(label.y)}%`,
                  transform:
                    `translate(-50%, -50%) rotate(${
                      Number.isFinite(label.rotation)
                      ? label.rotation
                      : 0
                    }deg)`,
                }}
              >
                {label.text}
              </span>
            ))}

            {positionedNodes.map((sensor) => {
              const position =
                layout.positions[sensor.node_id];

              const selected =
                node?.node_id === sensor.node_id;

              return (
                <span
                  key={sensor.node_id}
                  className={[
                    "location-mini-marker",
                    selected ? "selected" : "",
                    node && !selected ? "faded" : "",
                  ].join(" ")}
                  style={{
                    left: `${clamp(position.x)}%`,
                    top: `${clamp(position.y)}%`,
                  }}
                  title={sensor.name}
                />
              );
            })}

            {positionedNodes.length === 0 && (
              <span className="location-mini-empty">
                No nodes placed
              </span>
            )}
          </span>
        </span>
      </button>

      {open && (
        <dialog
          ref={dialogRef}
          className="location-dialog"
          aria-labelledby={titleId}
          onCancel={(event) => {
            event.preventDefault();
            closePopup();
          }}
          onClose={() =>
            triggerRef.current?.focus()
          }
        >
          <div className="location-dialog-header">
            <h2 id={titleId}>
              {node
                ? `${node.name} location`
                : `${zone.name} layout`}
            </h2>

            <button
              type="button"
              aria-label="Close location window"
              onClick={closePopup}
            >
              <X size={20} />
            </button>
          </div>

          <p className="muted location-dialog-hint">
            Save changes before closing.
          </p>

          <ZoneLayout
            key={`${storageKey}:${
              node?.node_id || "overview"
            }`}
            zone={zone}
            node={node}
            isDemo={isDemo}
            now={now}
            onSelectNode={(nodeId) => {
              closePopup();
              onSelectNode?.(nodeId);
            }}
          />
        </dialog>
      )}
    </>
  );
}