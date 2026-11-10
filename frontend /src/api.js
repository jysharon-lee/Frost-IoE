/* API configuration */

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  "http://localhost:8000"
).replace(/\/$/, "");

/* Shared JSON request */

export async function getJSON(path, signal) {
  const timeout = AbortSignal.timeout(8000);

  const requestSignal = signal
    ? AbortSignal.any([signal, timeout])
    : timeout;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    signal: requestSignal,
  });

  if (!response.ok) {
    throw new Error(
      `API request failed (${response.status}). Check your backend.`
    );
  }

  return response.json();
}

/* Live zone readings */

export async function getLiveZones(signal) {
  const response = await getJSON(
    "/api/zones/live",
    signal
  );

  if (!Array.isArray(response.zones)) {
    throw new Error(
      "Unexpected API response: zones must be an array."
    );
  }

  return {
    zones: response.zones.map((zone) => ({
      ...zone,
      type: "Zone readings",
      nodes: [],
      limits: zone.limits ?? null,
    })),
  };
}

/* Zone history */

export async function getZoneTrend(zoneId, hours, signal) {
  const response = await getJSON(
    `/api/zones/${encodeURIComponent(zoneId)}/trend?hours=${hours}`,
    signal
  );

  if (!Array.isArray(response.data)) {
    throw new Error(
      "Unexpected API response: history must be an array."
    );
  }

  return response.data;
}

/* Thermal forecast */

export function getForecast(zoneId, limit, signal) {
  const query = new URLSearchParams({
    zone_id: zoneId,
    limit_c: String(limit),
  });

  return getJSON(`/api/forecast?${query}`, signal);
}

/* Sensor health */

export function getSensorHealth(zoneId, signal) {
  const query = new URLSearchParams({
    zone_id: zoneId,
  });

  return getJSON(`/api/sensor-health?${query}`, signal);
}

/* PDF and Excel report downloads */

export async function downloadReport({
  zoneId,
  limit,
  start,
  end,
  facility = "",
  format,
}) {
  if (!zoneId) {
    throw new Error("Select a zone.");
  }

  if (
    !Number.isFinite(limit) ||
    limit < -100 ||
    limit > 100
  ) {
    throw new Error(
      "The zone needs a valid temperature limit."
    );
  }

  if (format !== "pdf" && format !== "excel") {
    throw new Error("Choose PDF or Excel.");
  }

  const from = new Date(start);
  const until = new Date(end);

  if (
    !Number.isFinite(from.getTime()) ||
    !Number.isFinite(until.getTime()) ||
    until <= from ||
    until - from > 31 * 86400000 ||
    from >= new Date()
  ) {
    throw new Error(
      "Choose a valid reporting period of up to 31 days."
    );
  }

  const query = new URLSearchParams({
    zone_id: zoneId,
    limit_c: String(limit),
    start: from.toISOString(),
    end: until.toISOString(),
    facility: facility.trim() || "Not specified",
  });

  const endpoint =
    format === "pdf" ? "export-pdf" : "export-excel";

  const response = await fetch(
    `${API_BASE_URL}/api/reports/${endpoint}?${query}`,
    {
      signal: AbortSignal.timeout(60000),
    }
  );

  if (!response.ok) {
    const body = await response.json().catch(() => null);

    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `Report failed (${response.status}).`
    );
  }

  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");

  try {
    link.href = url;
    link.download =
      `frost-${zoneId}.${format === "pdf" ? "pdf" : "xlsx"}`;

    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();

    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 1000);
  }
}