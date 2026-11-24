"""Scripted mock data: a node's reading is a pure function of time since backend start, so the live cards,
trends, raw readings and the alert engine all see the same story. Restart the backend to replay it.

Specs sit in the site config: zone "mock" merged under node "mock" (node wins), all times in minutes since start:
  curve   [[min, delta_c], ...]        linear offset from the zone base temperature, flat outside the points
  down    [[from, to], ...]            node silent (no rows, no live timestamp)
  fault   [[from, to], ...]            node alive but its sensor answers ok=false (no temperature)
  erratic [[from, to, amp_c], ...]     adds random +-amp_c every sample
"""
import random
from datetime import datetime, timedelta, timezone

START = datetime.now(timezone.utc)


def _curve(points, m):
    if not points or m <= points[0][0]:
        return points[0][1] if points else 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):  # x must increase strictly
        if m <= x1:
            return y0 + (y1 - y0) * (m - x0) / (x1 - x0)
    return points[-1][1]


def mock_sample(zone, node, t, base):
    """-> None (node silent) or {"ok": bool, "temp_c": float | None}. Noise is seeded per node-minute."""
    spec = {**zone.get("mock", {}), **node.get("mock", {})}
    m = (t - START).total_seconds() / 60
    if any(a <= m < b for a, b in spec.get("down", [])):
        return None
    if any(a <= m < b for a, b in spec.get("fault", [])):
        return {"ok": False, "temp_c": None}
    rng = random.Random(f"{node['node_id']}{int(t.timestamp() // 60)}")
    temp = base + rng.uniform(-0.05, 0.05) + _curve(spec.get("curve", []), m)
    for a, b, amp in spec.get("erratic", []):
        if a <= m < b:
            temp += rng.uniform(-amp, amp)
    rh = 80 - 1.5 * (temp - base) + rng.uniform(-1.5, 1.5)  # warmer air reads drier; ponytail: no per-zone humidity profile
    return {"ok": True, "temp_c": temp, "rh_pct": max(0.0, min(100.0, rh))}


def mock_last_seen(zone, node, now, base):
    """Latest whole minute <= now at which the node was not silent; None if silent for a day."""
    t = now.replace(second=0, microsecond=0)
    for _ in range(1440):
        if mock_sample(zone, node, t, base) is not None:
            return t
        t -= timedelta(minutes=1)
    return None
