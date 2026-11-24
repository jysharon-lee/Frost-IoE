"""Background alert evaluation engine with send-once-until-recovery state machine."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from alerts.notifiers import EmailNotifier
from alerts.rules import (
    evaluate_forecast_warning,
    evaluate_offline,
    evaluate_sustained_breach,
    is_backfill,
    zone_average_live_series,
)
from analytics import erratic
from config import settings
from influx_client import influx_service
from sitecfg import site

logger = logging.getLogger("frost_ioe.alerts")
AlertKey = Tuple[str, str, str]  # (zone_id, node_id, alert_type)


class AlertEngine:
    def __init__(self, influx=None, notifier: Optional[EmailNotifier] = None, site_config: Optional[dict] = None):
        self.influx = influx or influx_service
        self.notifier = notifier or EmailNotifier()
        self.site_config = site_config or site

        # Runtime-configurable parameters (seeded from config.settings)
        self.alerts_enabled: bool = settings.ALERTS_ENABLED
        self.poll_interval_s: int = settings.ALERT_POLL_INTERVAL_S
        self.sustained_breach_minutes: float = settings.SUSTAINED_BREACH_MINUTES
        self.offline_alert_after_s: int = settings.OFFLINE_ALERT_AFTER_S
        self.forecast_alerts_enabled: bool = settings.FORECAST_ALERTS_ENABLED
        self.forecast_warning_minutes: float = settings.FORECAST_WARNING_MINUTES
        self.door_sustained_minutes: float = settings.DOOR_SUSTAINED_MINUTES

        self._active: Dict[AlertKey, dict] = {}
        self._forecast_streak: Dict[str, int] = {}
        self._fault_streak: Dict[AlertKey, int] = {}  # +n consecutive faulty polls, -n consecutive clean polls
        self._task: Optional[asyncio.Task] = None

    def get_config(self) -> dict:
        return {
            "alerts_enabled": self.alerts_enabled,
            "poll_interval_s": self.poll_interval_s,
            "sustained_breach_minutes": self.sustained_breach_minutes,
            "door_sustained_minutes": self.door_sustained_minutes,
            "offline_alert_after_s": self.offline_alert_after_s,
            "forecast_alerts_enabled": self.forecast_alerts_enabled,
            "forecast_warning_minutes": self.forecast_warning_minutes,
            "email_alerts_enabled": self.notifier.enabled,
            "smtp_configured": self.notifier.is_configured(),
        }

    def update_config(self, **kwargs) -> dict:
        if "alerts_enabled" in kwargs and kwargs["alerts_enabled"] is not None:
            self.alerts_enabled = bool(kwargs["alerts_enabled"])
        if "forecast_alerts_enabled" in kwargs and kwargs["forecast_alerts_enabled"] is not None:
            self.forecast_alerts_enabled = bool(kwargs["forecast_alerts_enabled"])
            if not self.forecast_alerts_enabled:
                self._forecast_streak.clear()
        if "email_alerts_enabled" in kwargs and kwargs["email_alerts_enabled"] is not None:
            self.notifier.enabled = bool(kwargs["email_alerts_enabled"])
        if "sustained_breach_minutes" in kwargs and kwargs["sustained_breach_minutes"] is not None:
            self.sustained_breach_minutes = float(kwargs["sustained_breach_minutes"])
        for name in ("door_sustained_minutes", "forecast_warning_minutes"):
            if kwargs.get(name) is not None:
                setattr(self, name, float(kwargs[name]))
        if "offline_alert_after_s" in kwargs and kwargs["offline_alert_after_s"] is not None:
            self.offline_alert_after_s = int(kwargs["offline_alert_after_s"])
        return self.get_config()

    def get_active_alerts(self) -> List[dict]:
        return sorted(self._active.values(), key=lambda a: a["started_at"], reverse=True)

    def hydrate_from_influx(self) -> None:
        """Restore currently ALERTING states from InfluxDB `alert_events` on startup."""
        try:
            latest = self.influx.get_latest_alert_states(days=7)
        except Exception as exc:
            logger.warning("Could not hydrate alert state from InfluxDB: %s", exc)
            return

        for key, ev in latest.items():
            if ev.get("state") == "ALERTING":
                self._active[key] = {
                    "zone_id": ev["zone_id"],
                    "node_id": ev["node_id"],
                    "alert_type": ev["alert_type"],
                    "severity": ev["severity"],
                    "state": "ALERTING",
                    "message": ev["message"],
                    "started_at": ev["timestamp"],
                    "temp_c": ev.get("temp_c"),
                    "limit_c": ev.get("limit_c"),
                    "peak_c": ev.get("peak_c"),
                    "email_sent": ev.get("email_sent", False),
                }

    def _emit(self, event: dict, send_email: bool = True) -> dict:
        email_sent = self.notifier.send_sync(event) if send_email else False
        event["email_sent"] = email_sent
        try:
            self.influx.write_alert_event(event)
        except Exception as exc:
            logger.error("Failed to write alert event to InfluxDB: %s", exc)
        return event

    def _trigger(self, key: AlertKey, event: dict, started_at: Optional[datetime] = None) -> Optional[dict]:
        """Fire once on OK -> ALERTING transition; ignore if already active."""
        if key in self._active:
            return None
        dispatched = self._emit(event, send_email=True)
        self._active[key] = {
            **dispatched,
            "started_at": started_at or dispatched["timestamp"],
        }
        return dispatched

    def _resolve(
        self,
        key: AlertKey,
        now: datetime,
        message: str,
        zone_name: str,
        node_name: Optional[str] = None,
        temp_c: Optional[float] = None,
        send_email: bool = True,
    ) -> Optional[dict]:
        """Fire once on ALERTING -> OK transition."""
        active = self._active.pop(key, None)
        if active is None:
            return None
        duration_min = round(max(0.0, (now - active["started_at"]).total_seconds() / 60.0), 1)
        zone_id, node_id, alert_type = key
        event = {
            "timestamp": now,
            "zone_id": zone_id,
            "zone_name": zone_name,
            "node_id": node_id,
            "node_name": node_name,
            "alert_type": alert_type,
            "severity": "RECOVERY",
            "state": "RESOLVED",
            "message": message,
            "temp_c": temp_c,
            "limit_c": active.get("limit_c"),
            "peak_c": active.get("peak_c"),
            "duration_minutes": duration_min,
        }
        return self._emit(event, send_email=send_email)

    def evaluate_once(self, now: Optional[datetime] = None) -> List[dict]:
        """Run one evaluation pass across all configured zones. Returns newly emitted events."""
        if not self.alerts_enabled:
            return []

        now = now or datetime.now(timezone.utc)
        emitted: List[dict] = []

        live_stamps = self.influx.get_latest_live_timestamps()
        failed = self.influx.get_failed_nodes()
        window_min = max(30.0, max(self.sustained_breach_minutes, self.door_sustained_minutes) + 15.0)
        start = now - timedelta(minutes=window_min)

        for zone in self.site_config["zones"]:
            zone_id = zone["zone_id"]
            zone_name = zone.get("name", zone_id)
            limits = zone.get("limits")

            # --- Rule 2: Node or zone offline (>180s without LIVE report) ---
            off = evaluate_offline(zone["nodes"], live_stamps, now, offline_after_s=self.offline_alert_after_s)
            zone_off_key: AlertKey = (zone_id, "zone_aggregate", "zone_offline")

            if off["zone_offline"]:
                # Collapse individual node_offline states silently when the entire zone goes offline.
                for node in zone["nodes"]:
                    n_key: AlertKey = (zone_id, node["node_id"], "node_offline")
                    if n_key in self._active:
                        self._resolve(
                            n_key,
                            now,
                            f"Superseded by full zone offline for {zone_name}.",
                            zone_name=zone_name,
                            node_name=node.get("name"),
                            send_email=False,
                        )
                ev = self._trigger(
                    zone_off_key,
                    {
                        "timestamp": now,
                        "zone_id": zone_id,
                        "zone_name": zone_name,
                        "node_id": "zone_aggregate",
                        "alert_type": "zone_offline",
                        "severity": "CRITICAL",
                        "state": "ALERTING",
                        "message": (
                            f"All {len(zone['nodes'])} nodes in {zone_name} have been silent "
                            f"for more than {self.offline_alert_after_s}s."
                        ),
                    },
                    started_at=off["zone_last_seen"] or now,
                )
                if ev:
                    emitted.append(ev)
            else:
                if zone_off_key in self._active:
                    ev = self._resolve(
                        zone_off_key,
                        now,
                        f"{zone_name} is back online ({len(off['online_nodes'])}/{len(zone['nodes'])} nodes reporting).",
                        zone_name=zone_name,
                    )
                    if ev:
                        emitted.append(ev)

                for node_info in off["offline_nodes"]:
                    n_key = (zone_id, node_info["node_id"], "node_offline")
                    ev = self._trigger(
                        n_key,
                        {
                            "timestamp": now,
                            "zone_id": zone_id,
                            "zone_name": zone_name,
                            "node_id": node_info["node_id"],
                            "node_name": node_info["name"],
                            "alert_type": "node_offline",
                            "severity": "CRITICAL",
                            "state": "ALERTING",
                            "message": (
                                f"Node {node_info['name']} ({node_info['node_id']}) in {zone_name} "
                                f"has not reported live data for more than {self.offline_alert_after_s}s."
                            ),
                        },
                        started_at=node_info["last_seen"] or now,
                    )
                    if ev:
                        emitted.append(ev)

                for node_info in off["online_nodes"]:
                    n_key = (zone_id, node_info["node_id"], "node_offline")
                    if n_key in self._active:
                        ev = self._resolve(
                            n_key,
                            now,
                            f"Node {node_info['name']} ({node_info['node_id']}) in {zone_name} is back online.",
                            zone_name=zone_name,
                            node_name=node_info["name"],
                        )
                        if ev:
                            emitted.append(ev)

            # Skip temperature rules if the entire zone is offline.
            if off["zone_offline"]:
                self._forecast_streak[zone_id] = 0
                continue

            # Fetch live zone average series for Rules 1 & 3
            raw_rows = self.influx.get_raw_readings(zone_id, start, now)
            door_ids = {n["node_id"] for n in zone["nodes"] if n.get("is_door")}
            # Broken (ok=false) or erratic sensors are left out of the zone average too, like door nodes (Rule 4 alerts them).
            silent = {n["node_id"] for n in off["offline_nodes"]}  # offline nodes belong to Rule 2
            faulty = {}
            for node in zone["nodes"]:
                nid = node["node_id"]
                if nid in silent:
                    continue
                if nid in failed:
                    faulty[nid] = "reports a sensor failure (ok=false)"
                elif erratic([r for r in raw_rows if r.get("node_id") == nid and not is_backfill(r)], now):
                    faulty[nid] = "has erratic readings (large jumps between samples)"
            points = zone_average_live_series(
                [r for r in raw_rows if r.get("node_id") not in door_ids | faulty.keys()], start, now)

            # --- Rule 1: Sustained limit breach (zone average, >=10 min) ---
            breach = evaluate_sustained_breach(
                points,
                now,
                limits,
                sustained_minutes=self.sustained_breach_minutes,
                stale_after_s=self.offline_alert_after_s,
            )
            breach_key: AlertKey = (zone_id, "zone_aggregate", "sustained_breach")

            if breach["triggered"]:
                if breach_key in self._active:
                    # Keep peak updated while active without re-sending email
                    prev_peak = self._active[breach_key].get("peak_c")
                    if breach["peak_c"] is not None:
                        if breach["direction"] == "below_min":
                            self._active[breach_key]["peak_c"] = (
                                min(prev_peak, breach["peak_c"]) if prev_peak is not None else breach["peak_c"]
                            )
                        else:
                            self._active[breach_key]["peak_c"] = (
                                max(prev_peak, breach["peak_c"]) if prev_peak is not None else breach["peak_c"]
                            )
                    self._active[breach_key]["temp_c"] = breach["current_temp_c"]
                else:
                    dir_text = "below lower limit" if breach["direction"] == "below_min" else "above upper limit"
                    ev = self._trigger(
                        breach_key,
                        {
                            "timestamp": now,
                            "zone_id": zone_id,
                            "zone_name": zone_name,
                            "node_id": "zone_aggregate",
                            "alert_type": "sustained_breach",
                            "severity": "CRITICAL",
                            "state": "ALERTING",
                            "message": (
                                f"{zone_name} average temperature ({breach['current_temp_c']:.2f} °C) "
                                f"has been {dir_text} ({breach['limit_c']:.1f} °C) "
                                f"for {breach['observed_minutes']:.1f} minutes."
                            ),
                            "temp_c": breach["current_temp_c"],
                            "limit_c": breach["limit_c"],
                            "peak_c": breach["peak_c"],
                            "duration_minutes": breach["observed_minutes"],
                        },
                        started_at=breach["started_at"] or now,
                    )
                    if ev:
                        emitted.append(ev)
            elif breach["recovered"] and breach_key in self._active:
                ev = self._resolve(
                    breach_key,
                    now,
                    f"{zone_name} average temperature is back within limits ({breach['current_temp_c']:.2f} °C).",
                    zone_name=zone_name,
                    temp_c=breach["current_temp_c"],
                )
                if ev:
                    emitted.append(ev)

            breach_active = breach_key in self._active

            # --- Rule 1b: per-node sustained breach (door nodes wait longer). Zone breach supersedes: one email, not N+1. ---
            for node in zone["nodes"]:
                nid = node["node_id"]
                nb_key: AlertKey = (zone_id, nid, "node_breach")
                if breach_active:
                    self._resolve(nb_key, now, f"Superseded by zone breach for {zone_name}.",
                                  zone_name=zone_name, node_name=node.get("name"), send_email=False)
                    continue
                nb = evaluate_sustained_breach(
                    zone_average_live_series([r for r in raw_rows if r.get("node_id") == nid], start, now),
                    now,
                    limits,
                    sustained_minutes=self.door_sustained_minutes if node.get("is_door") else self.sustained_breach_minutes,
                    stale_after_s=self.offline_alert_after_s,
                )
                if nb["triggered"]:
                    side = "below lower limit" if nb["direction"] == "below_min" else "above upper limit"
                    ev = self._trigger(
                        nb_key,
                        {
                            "timestamp": now,
                            "zone_id": zone_id,
                            "zone_name": zone_name,
                            "node_id": nid,
                            "node_name": node.get("name"),
                            "alert_type": "node_breach",
                            "severity": "CRITICAL",
                            "state": "ALERTING",
                            "message": (
                                f"{node.get('name', nid)} ({nid}) in {zone_name} ({nb['current_temp_c']:.2f} °C) "
                                f"has been {side} ({nb['limit_c']:.1f} °C) for {nb['observed_minutes']:.1f} minutes."
                            ),
                            "temp_c": nb["current_temp_c"],
                            "limit_c": nb["limit_c"],
                            "peak_c": nb["peak_c"],
                            "duration_minutes": nb["observed_minutes"],
                        },
                        started_at=nb["started_at"] or now,
                    )
                    if ev:
                        emitted.append(ev)
                elif nb["recovered"]:
                    ev = self._resolve(
                        nb_key, now,
                        f"{node.get('name', nid)} ({nid}) is back within limits ({nb['current_temp_c']:.2f} °C).",
                        zone_name=zone_name, node_name=node.get("name"), temp_c=nb["current_temp_c"],
                    )
                    if ev:
                        emitted.append(ev)

            # --- Rule 4: sensor fault (node alive but ok=false, or erratic readings). Offline nodes belong to Rule 2.
            # Opens and closes only after 2 consecutive polls, so one glitch does not email. ---
            for node in zone["nodes"]:
                nid, label = node["node_id"], node.get("name", node["node_id"])
                if nid in silent:
                    continue
                why = faulty.get(nid)
                f_key: AlertKey = (zone_id, nid, "sensor_fault")
                prev = self._fault_streak.get(f_key, 0)
                streak = self._fault_streak[f_key] = max(prev, 0) + 1 if why else min(prev, 0) - 1
                ev = None
                if why and streak >= 2:
                    ev = self._trigger(f_key, {
                        "timestamp": now, "zone_id": zone_id, "zone_name": zone_name, "node_id": nid,
                        "node_name": node.get("name"), "alert_type": "sensor_fault", "severity": "WARNING",
                        "state": "ALERTING", "message": f"Check sensor: {label} ({nid}) in {zone_name} {why}."})
                elif not why and streak <= -2:
                    ev = self._resolve(f_key, now, f"Sensor {label} ({nid}) in {zone_name} is working normally again.",
                                       zone_name=zone_name, node_name=node.get("name"))
                if ev:
                    emitted.append(ev)

            # --- Rule 3: Forecast early warning (<=20 min, own toggle, 2-cycle debounce) ---
            fc =evaluate_forecast_warning(
                points,
                now,
                limits,
                horizon_minutes=self.forecast_warning_minutes,
                enabled=self.forecast_alerts_enabled,
                suppressed=breach_active,
            )
            fc_key: AlertKey = (zone_id, "zone_aggregate", "forecast_early_warning")

            if fc["triggered"]:
                self._forecast_streak[zone_id] = self._forecast_streak.get(zone_id, 0) + 1
                if self._forecast_streak[zone_id] >= 2:
                    ev = self._trigger(
                        fc_key,
                        {
                            "timestamp": now,
                            "zone_id": zone_id,
                            "zone_name": zone_name,
                            "node_id": "zone_aggregate",
                            "alert_type": "forecast_early_warning",
                            "severity": "WARNING",
                            "state": "ALERTING",
                            "message": (
                                f"Early warning: {zone_name} is warming at +{fc['rate_c_per_hour']:.2f} °C/hr "
                                f"and is projected to cross {fc['limit_c']:.1f} °C in ~{fc['minutes_to_limit']:.1f} minutes."
                            ),
                            "temp_c": fc["current_temp_c"],
                            "limit_c": fc["limit_c"],
                        },
                        started_at=now,
                    )
                    if ev:
                        emitted.append(ev)
            else:
                self._forecast_streak[zone_id] = 0
                if fc_key in self._active:
                    if breach_active:
                        # Escalated into a confirmed breach — resolve forecast quietly without a recovery email.
                        self._resolve(
                            fc_key,
                            now,
                            f"Forecast warning escalated to sustained breach for {zone_name}.",
                            zone_name=zone_name,
                            temp_c=fc["current_temp_c"],
                            send_email=False,
                        )
                    elif fc["recovered"]:
                        ev = self._resolve(
                            fc_key,
                            now,
                            f"{zone_name} warming trend has stabilized ({fc['current_temp_c']:.2f} °C).",
                            zone_name=zone_name,
                            temp_c=fc["current_temp_c"],
                        )
                        if ev:
                            emitted.append(ev)

        return emitted

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.evaluate_once)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Alert evaluation cycle failed: %s", exc)
            await asyncio.sleep(self.poll_interval_s)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        await asyncio.to_thread(self.hydrate_from_influx)
        self._task = asyncio.create_task(self._loop(), name="frost-ioe-alert-loop")
        logger.info("AlertEngine started (poll=%ss, forecast=%s)", self.poll_interval_s, self.forecast_alerts_enabled)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("AlertEngine stopped")


# Singleton instance for import across backend
alert_engine = AlertEngine()
