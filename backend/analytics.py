"""Timestamp-based analytics. No database or HTTP dependencies."""
from datetime import timedelta
from math import isfinite
from statistics import median


def clean_points(rows, start, end):
    # Collapse retransmissions deterministically; conflicting duplicates are unusable.
    values = {}
    conflicts = set()
    for row in rows:
        time, temp = row["timestamp"], row.get("temp_c")
        if not start <= time <= end or temp is None or not isfinite(temp):
            continue
        if time in values and values[time] != temp:
            conflicts.add(time)
        values[time] = temp
    return [(t, values[t]) for t in sorted(values) if t not in conflicts]


def coverage(points, now, minutes):
    if len(points) < 3:
        return "insufficient_data"
    if (now - points[-1][0]).total_seconds() > 180:
        return "stale_data"
    if (points[-1][0] - points[0][0]).total_seconds() < (minutes - 1) * 60:
        return "insufficient_history"
    if any((b[0]-a[0]).total_seconds() > 180 for a,b in zip(points, points[1:])):
        return "data_gap"
    return None


def forecast(rows, now, limit):
    points = clean_points(rows, now-timedelta(minutes=10), now)
    result = {"status": "unavailable", "reason": coverage(points, now, 10),
              "limit_c": limit, "sample_count": len(points),
              "rate_c_per_minute": None, "rate_c_per_hour": None,
              "minutes_to_limit": None, "early_warning": False}
    if result["reason"]:
        return result
    times = [(t-points[0][0]).total_seconds()/60 for t,_ in points]
    temps = [v for _,v in points]
    xm, ym = sum(times)/len(times), sum(temps)/len(temps)
    slope = sum((x-xm)*(y-ym) for x,y in zip(times,temps))/sum((x-xm)**2 for x in times)
    current = temps[-1]
    eta = max(0.0, (limit-current)/slope) if slope > 1e-9 else None
    breached = current > limit
    if breached:
        eta = 0.0
    result.update(status="breached" if breached else "warming" if slope > 1e-9 else "not_rising",
                  current_temp_c=current, rate_c_per_minute=slope, rate_c_per_hour=slope*60,
                  minutes_to_limit=eta, early_warning=not breached and eta is not None and eta <= 20)
    return result


def sensor_health(rows, now, baseline_offsets):
    groups = {}
    for row in rows:
        identity = row.get("sensor_id") or row.get("node_id") or "zone_aggregate"
        groups.setdefault(identity, []).append(row)
    results = []
    for identity, readings in sorted(groups.items()):
        recent = clean_points(readings, now-timedelta(minutes=15), now)
        reason = coverage(recent, now, 15)
        flatline = None if reason else max(v for _,v in recent)-min(v for _,v in recent) < 0.05
        drift, drift_reason = None, "individual_sensor_ids_and_baselines_required"
        if identity != "zone_aggregate" and identity in baseline_offsets:
            own = clean_points(readings, now-timedelta(hours=6), now)
            drift_reason = coverage(own, now, 360)
            if not drift_reason:
                deviations = []
                peers = {key: clean_points(value, now-timedelta(hours=6), now)
                         for key,value in groups.items() if key != identity and key in baseline_offsets}
                # Match within 30 seconds; do not compare unrelated sampling times.
                indexes = {key: 0 for key in peers}
                for stamp, temp in own:
                    matches = []
                    for key, points in peers.items():
                        i = indexes[key]
                        while i+1 < len(points) and abs((points[i+1][0]-stamp).total_seconds()) <= abs((points[i][0]-stamp).total_seconds()):
                            i += 1
                        indexes[key] = i
                        if points and abs((points[i][0]-stamp).total_seconds()) <= 30:
                            matches.append(points[i][1]-baseline_offsets[key])
                    if matches:
                        deviations.append((stamp, temp-baseline_offsets[identity]-median(matches)))
                drift_reason = coverage(deviations, now, 360)
                if not drift_reason:
                    drift = all(value > 1 for _,value in deviations) or all(value < -1 for _,value in deviations)
        results.append({"sensor_id": identity, "scope": "zone" if identity == "zone_aggregate" else "sensor",
                        "flatline_suspected": flatline, "flatline_reason": reason,
                        "drift_suspected": drift, "drift_reason": drift_reason,
                        "note": "Flags indicate suspected anomalies, not confirmed sensor failure."})
    return results


def excursions(points, limit):
    events, active = [], None
    for stamp,temp in points:
        if active and (stamp-active["last_observed"]).total_seconds() > 180:
            active["end_reason"] = "data_gap"
            events.append(active)
            active = None
        if temp > limit:
            if active is None:
                active = {"start": stamp, "last_observed": stamp, "peak_c": temp, "end_reason": "ongoing_or_end_of_range"}
            active["last_observed"] = stamp
            active["peak_c"] = max(active["peak_c"], temp)
        elif active:
            active["end_reason"] = "next_sample_within_limit"
            events.append(active)
            active = None
    if active:
        events.append(active)
    for event in events:
        event["observed_minutes"] = (event["last_observed"]-event["start"]).total_seconds()/60
    return events
