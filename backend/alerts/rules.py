"""Pure alert evaluation rules (no database, network, or HTTP dependencies)."""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from analytics import clean_points, forecast

Point2D = Tuple[datetime, float]


def is_backfill(row: dict) -> bool:
    """True when a row was buffered/backfilled during an outage."""
    source = str(row.get("source", "")).upper()
    buffered = row.get("buffered")
    return source in ("BACKFILL", "BUFFERED") or buffered in (True, "true", "True")


def zone_average_live_series(rows: List[dict], start: datetime, end: datetime) -> List[Point2D]:
    """Equal-weighted zone average across live (non-backfilled) sensors at each timestamp."""
    sensors: Dict[str, List[dict]] = {}
    for row in rows:
        if is_backfill(row):
            continue
        identity = row.get("sensor_id") or row.get("node_id") or "zone_aggregate"
        sensors.setdefault(identity, []).append(row)

    grouped: Dict[datetime, List[float]] = {}
    for readings in sensors.values():
        for stamp, temp in clean_points(readings, start, end):
            grouped.setdefault(stamp, []).append(temp)

    return [(t, sum(vals) / len(vals)) for t, vals in sorted(grouped.items())]


def _breach_info(temp: float, limits: dict) -> Optional[Tuple[str, float]]:
    """Return (direction, breached_limit) if temp is outside [min, max], else None."""
    hi, lo = limits.get("max"), limits.get("min")
    if hi is not None and temp > hi:
        return ("above_max", float(hi))
    if lo is not None and temp < lo:
        return ("below_min", float(lo))
    return None


def _limit_excursions(points: List[Point2D], limits: dict, max_gap_s: int = 180) -> List[dict]:
    """Track contiguous out-of-limit windows (above max or below min), splitting on >max_gap_s gaps."""
    events: List[dict] = []
    active: Optional[dict] = None

    for stamp, temp in points:
        if active and (stamp - active["last_observed"]).total_seconds() > max_gap_s:
            active["end_reason"] = "data_gap"
            events.append(active)
            active = None

        breach = _breach_info(temp, limits)
        if breach is not None:
            direction, limit_c = breach
            if active is not None and active["direction"] != direction:
                active["end_reason"] = "direction_changed"
                events.append(active)
                active = None
            if active is None:
                active = {
                    "start": stamp,
                    "last_observed": stamp,
                    "peak_c": temp,
                    "limit_c": limit_c,
                    "direction": direction,
                    "sample_count": 0,
                    "end_reason": "ongoing_or_end_of_range",
                }
            active["last_observed"] = stamp
            active["sample_count"] += 1
            if direction == "above_max":
                active["peak_c"] = max(active["peak_c"], temp)
            else:
                active["peak_c"] = min(active["peak_c"], temp)
        elif active is not None:
            active["end_reason"] = "next_sample_within_limit"
            events.append(active)
            active = None

    if active is not None:
        events.append(active)

    for ev in events:
        ev["observed_minutes"] = (ev["last_observed"] - ev["start"]).total_seconds() / 60.0
    return events


def evaluate_sustained_breach(
    points: List[Point2D],
    now: datetime,
    limits: Optional[dict],
    sustained_minutes: float = 10.0,
    stale_after_s: int = 180,
    recovery_samples: int = 2,
) -> dict:
    """Rule 1: Zone average outside [min, max] continuously for >= sustained_minutes."""
    empty = {
        "triggered": False,
        "recovered": False,
        "current_temp_c": None,
        "limit_c": None,
        "peak_c": None,
        "observed_minutes": 0.0,
        "started_at": None,
        "direction": None,
    }
    if not points or not limits:
        return empty

    last_ts, last_temp = points[-1]
    if (now - last_ts).total_seconds() > stale_after_s:
        # Stale data is handled by Rule 2 (offline); do not trigger or resolve breach.
        return empty

    events = _limit_excursions(points, limits, max_gap_s=stale_after_s)
    ongoing = (
        events[-1]
        if events and events[-1]["end_reason"] == "ongoing_or_end_of_range" and events[-1]["last_observed"] == last_ts
        else None
    )

    if ongoing is not None:
        triggered = ongoing["observed_minutes"] >= sustained_minutes and ongoing["sample_count"] >= 3
        return {
            "triggered": triggered,
            "recovered": False,
            "current_temp_c": round(last_temp, 2),
            "limit_c": ongoing["limit_c"],
            "peak_c": round(ongoing["peak_c"], 2),
            "observed_minutes": round(ongoing["observed_minutes"], 2),
            "started_at": ongoing["start"],
            "direction": ongoing["direction"],
        }

    # Not currently breaching: check anti-flapping recovery condition (N consecutive in-limit samples).
    tail = points[-recovery_samples:] if len(points) >= recovery_samples else []
    in_limit_tail = (
        len(tail) == recovery_samples
        and all(_breach_info(v, limits) is None for _, v in tail)
        and all((b[0] - a[0]).total_seconds() <= stale_after_s for a, b in zip(tail, tail[1:]))
    )
    return {
        "triggered": False,
        "recovered": in_limit_tail,
        "current_temp_c": round(last_temp, 2),
        "limit_c": limits.get("max"),
        "peak_c": None,
        "observed_minutes": 0.0,
        "started_at": None,
        "direction": None,
    }


def evaluate_offline(
    zone_nodes: List[dict],
    latest_live_timestamps: Dict[str, datetime],
    now: datetime,
    offline_after_s: int = 180,
) -> dict:
    """Rule 2: Node or zone silent for > offline_after_s based on LIVE (non-buffered) reports.

    When every configured node in a zone is offline, collapses into a single `zone_offline`
    alert instead of spamming one alert per node.
    """
    offline: List[dict] = []
    online: List[dict] = []
    seen_stamps: List[datetime] = []

    for node in zone_nodes:
        nid = node["node_id"]
        last_seen = latest_live_timestamps.get(nid)
        if last_seen is not None:
            seen_stamps.append(last_seen)
        age_s = (now - last_seen).total_seconds() if last_seen is not None else None
        is_off = age_s is None or age_s > offline_after_s
        entry = {
            "node_id": nid,
            "name": node.get("name", nid),
            "last_seen": last_seen,
            "offline_seconds": round(age_s, 1) if age_s is not None else None,
        }
        if is_off:
            offline.append(entry)
        else:
            online.append(entry)

    zone_offline = len(zone_nodes) > 0 and len(offline) == len(zone_nodes)
    zone_last_seen = max(seen_stamps) if seen_stamps else None
    zone_offline_s = round((now - zone_last_seen).total_seconds(), 1) if zone_last_seen else None

    return {
        "zone_offline": zone_offline,
        "zone_last_seen": zone_last_seen,
        "zone_offline_seconds": zone_offline_s,
        "offline_nodes": [] if zone_offline else offline,
        "online_nodes": online,
    }


def evaluate_forecast_warning(
    points: List[Point2D],
    now: datetime,
    limits: Optional[dict],
    horizon_minutes: float = 20.0,
    enabled: bool = True,
    suppressed: bool = False,
) -> dict:
    """Rule 3: Forecast projects upper-limit crossing within horizon_minutes (default 20 min)."""
    if not enabled or suppressed or not limits or limits.get("max") is None:
        return {
            "triggered": False,
            "recovered": False if suppressed else True,
            "enabled": enabled,
            "suppressed": suppressed,
            "minutes_to_limit": None,
            "rate_c_per_hour": None,
            "current_temp_c": round(points[-1][1], 2) if points else None,
            "limit_c": limits.get("max") if limits else None,
            "status": "disabled" if not enabled else "suppressed" if suppressed else "unavailable",
        }

    limit_c = float(limits["max"])
    rows = [{"timestamp": t, "temp_c": v} for t, v in points]
    res = forecast(rows, now, limit_c)
    eta = res.get("minutes_to_limit")
    triggered = bool(res["status"] == "warming" and eta is not None and eta <= horizon_minutes)
    # Do not report "forecast recovered" if the zone actually escalated into a breach.
    recovered = (not triggered) and res["status"] not in ("breached", "unavailable")

    return {
        "triggered": triggered,
        "recovered": recovered,
        "enabled": enabled,
        "suppressed": False,
        "minutes_to_limit": round(eta, 1) if eta is not None else None,
        "rate_c_per_hour": round(res["rate_c_per_hour"], 2) if res.get("rate_c_per_hour") is not None else None,
        "current_temp_c": round(res["current_temp_c"], 2) if res.get("current_temp_c") is not None else None,
        "limit_c": limit_c,
        "status": res["status"],
    }
