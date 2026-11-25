import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unittest.mock import patch

import mock_scenarios
from alerts.engine import AlertEngine
from alerts.notifiers import format_email
from config import settings
from influx_client import influx_service
from alerts.rules import (
    evaluate_forecast_warning,
    evaluate_offline,
    evaluate_sustained_breach,
    zone_average_live_series,
)


class AlertRulesTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
        self.frozen_limits = {"max": -18.0, "warn_margin": 3}
        self.chilled_limits = {"min": -1.0, "max": 10.0, "warn_margin": 3}

    def _series(self, temps, step_s=60):
        """Build [(timestamp, temp)] ending at self.now."""
        n = len(temps)
        return [(self.now - timedelta(seconds=(n - 1 - i) * step_s), t) for i, t in enumerate(temps)]

    # --- Rule 1: Sustained limit breach ---

    def test_short_door_opening_spike_does_not_trigger(self):
        # 5 minutes above -18 C (< 10 min threshold) must not trigger
        pts = self._series([-19.0, -19.0, -17.0, -16.8, -16.5, -16.9, -17.2, -17.5])
        res = evaluate_sustained_breach(pts, self.now, self.frozen_limits, sustained_minutes=10.0)
        self.assertFalse(res["triggered"])
        self.assertFalse(res["recovered"])

    def test_sustained_10_min_upper_breach_triggers(self):
        # 11 samples at 1-min intervals = 10.0 observed minutes above -18 C
        pts = self._series([-19.0] + [-17.2 + 0.1 * i for i in range(11)])
        res = evaluate_sustained_breach(pts, self.now, self.frozen_limits, sustained_minutes=10.0)
        self.assertTrue(res["triggered"])
        self.assertEqual(res["direction"], "above_max")
        self.assertEqual(res["limit_c"], -18.0)
        self.assertGreaterEqual(res["observed_minutes"], 10.0)
        self.assertAlmostEqual(res["peak_c"], -16.2, places=2)

    def test_sustained_lower_limit_breach_triggers_for_chilled_room(self):
        # Chilled room dropping below -1.0 C for 10+ minutes
        pts = self._series([2.0] + [-1.5 - 0.05 * i for i in range(11)])
        res = evaluate_sustained_breach(pts, self.now, self.chilled_limits, sustained_minutes=10.0)
        self.assertTrue(res["triggered"])
        self.assertEqual(res["direction"], "below_min")
        self.assertEqual(res["limit_c"], -1.0)

    def test_gap_over_180s_resets_sustained_timer(self):
        # 6 min breach, then 4 min gap (>180s), then 5 min breach -> only 4 min since gap
        pts = [
            (self.now - timedelta(minutes=15 - i), -16.0) for i in range(6)
        ] + [
            (self.now - timedelta(minutes=4 - i), -16.0) for i in range(5)
        ]
        res = evaluate_sustained_breach(pts, self.now, self.frozen_limits, sustained_minutes=10.0)
        self.assertFalse(res["triggered"])
        self.assertAlmostEqual(res["observed_minutes"], 4.0, places=2)

    def test_recovery_requires_two_consecutive_in_limit_samples(self):
        one_ok = self._series([-16.5, -16.8, -18.2])
        res1 = evaluate_sustained_breach(one_ok, self.now, self.frozen_limits, sustained_minutes=10.0)
        self.assertFalse(res1["triggered"])
        self.assertFalse(res1["recovered"])

        two_ok = self._series([-16.5, -18.2, -18.5])
        res2 = evaluate_sustained_breach(two_ok, self.now, self.frozen_limits, sustained_minutes=10.0)
        self.assertFalse(res2["triggered"])
        self.assertTrue(res2["recovered"])

    def test_backfill_rows_are_excluded_from_live_zone_average(self):
        rows = [
            {"timestamp": self.now - timedelta(minutes=2), "node_id": "N01", "temp_c": -19.0, "source": "LIVE"},
            {"timestamp": self.now - timedelta(minutes=2), "node_id": "N02", "temp_c": -10.0, "source": "BACKFILL"},
            {"timestamp": self.now - timedelta(minutes=1), "node_id": "N01", "temp_c": -19.2, "buffered": "true"},
        ]
        pts = zone_average_live_series(rows, self.now - timedelta(minutes=5), self.now)
        self.assertEqual(len(pts), 1)
        self.assertAlmostEqual(pts[0][1], -19.0)

    # --- Rule 2: Node or zone offline ---

    def test_single_node_offline_vs_all_nodes_zone_offline(self):
        nodes = [
            {"node_id": "N01", "name": "Sensor 1"},
            {"node_id": "N02", "name": "Sensor 2"},
            {"node_id": "N03", "name": "Sensor 3"},
        ]
        # Only N02 silent > 180s
        stamps_partial = {
            "N01": self.now - timedelta(seconds=20),
            "N02": self.now - timedelta(seconds=240),
            "N03": self.now - timedelta(seconds=10),
        }
        res_partial = evaluate_offline(nodes, stamps_partial, self.now, offline_after_s=180)
        self.assertFalse(res_partial["zone_offline"])
        self.assertEqual([n["node_id"] for n in res_partial["offline_nodes"]], ["N02"])
        self.assertEqual([n["node_id"] for n in res_partial["online_nodes"]], ["N01", "N03"])

        # All 3 nodes silent > 180s -> collapses into zone_offline
        stamps_all = {
            "N01": self.now - timedelta(seconds=200),
            "N02": self.now - timedelta(seconds=300),
            "N03": self.now - timedelta(seconds=250),
        }
        res_all = evaluate_offline(nodes, stamps_all, self.now, offline_after_s=180)
        self.assertTrue(res_all["zone_offline"])
        self.assertEqual(res_all["offline_nodes"], [])

    # --- Rule 3: Forecast early warning ---

    def test_forecast_early_warning_triggers_within_20_min_and_respects_toggle(self):
        # Rising +0.1 C/min from -19.5 to -18.5 -> ETA to -18.0 is 5 minutes (<= 20 min)
        pts = self._series([-19.5 + 0.1 * i for i in range(11)])
        res = evaluate_forecast_warning(pts, self.now, self.frozen_limits, horizon_minutes=20.0, enabled=True)
        self.assertTrue(res["triggered"])
        self.assertFalse(res["recovered"])
        self.assertAlmostEqual(res["minutes_to_limit"], 5.0, places=1)

        # Disabled switch suppresses trigger
        res_off = evaluate_forecast_warning(pts, self.now, self.frozen_limits, horizon_minutes=20.0, enabled=False)
        self.assertFalse(res_off["triggered"])
        self.assertEqual(res_off["status"], "disabled")

    def test_forecast_does_not_emit_recovery_when_already_breached(self):
        pts = self._series([-18.5 + 0.1 * i for i in range(11)])  # ends at -17.5 (> -18)
        res = evaluate_forecast_warning(pts, self.now, self.frozen_limits, horizon_minutes=20.0, enabled=True)
        self.assertFalse(res["triggered"])
        self.assertFalse(res["recovered"])


class _FakeInflux:
    def __init__(self):
        self.live_stamps = {}
        self.raw_by_zone = {}
        self.written = []
        self.failed = set()

    def get_latest_live_timestamps(self):
        return dict(self.live_stamps)

    def get_failed_nodes(self):
        return set(self.failed)

    def get_raw_readings(self, zone_id, start, end):
        return list(self.raw_by_zone.get(zone_id, []))

    def write_alert_event(self, event):
        self.written.append(dict(event))

    def get_latest_alert_states(self, days=7):
        latest = {}
        for ev in sorted(self.written, key=lambda x: x["timestamp"]):
            latest[(ev["zone_id"], ev["node_id"], ev["alert_type"])] = ev
        return latest


class _FakeNotifier:
    def __init__(self):
        self.enabled = True
        self.sent = []

    def is_configured(self):
        return True

    def send_sync(self, event):
        self.sent.append(dict(event))
        return True


class AlertEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
        self.site_cfg = {
            "zones": [
                {
                    "zone_id": "Z1",
                    "name": "Freezer Room 1",
                    "limits": {"max": -18.0, "warn_margin": 3},
                    "nodes": [
                        {"node_id": "N01", "name": "Sensor 1"},
                        {"node_id": "N02", "name": "Sensor 2"},
                    ],
                }
            ]
        }
        self.influx = _FakeInflux()
        self.influx.live_stamps = {
            "N01": self.now - timedelta(seconds=10),
            "N02": self.now - timedelta(seconds=10),
        }
        self.notifier = _FakeNotifier()
        self.engine = AlertEngine(influx=self.influx, notifier=self.notifier, site_config=self.site_cfg)

    def _raw_rows(self, temps, end_time):
        n = len(temps)
        rows = []
        for i, t in enumerate(temps):
            ts = end_time - timedelta(minutes=n - 1 - i)
            rows.append({"timestamp": ts, "node_id": "N01", "temp_c": t, "source": "LIVE"})
            rows.append({"timestamp": ts, "node_id": "N02", "temp_c": t, "source": "LIVE"})
        return rows

    def test_sustained_breach_sends_once_until_recovery(self):
        # Cycle 1: 11 samples = 10 min above -18 -> sends 1 CRITICAL alert
        self.influx.raw_by_zone["Z1"] = self._raw_rows([-17.0] * 11, self.now)
        e1 = self.engine.evaluate_once(self.now)
        self.assertEqual(len(e1), 1)
        self.assertEqual(e1[0]["alert_type"], "sustained_breach")
        self.assertEqual(e1[0]["state"], "ALERTING")
        self.assertEqual(len(self.notifier.sent), 1)

        # Cycle 2: still breached 1 min later -> NO duplicate email
        t2 = self.now + timedelta(minutes=1)
        self.influx.live_stamps = {"N01": t2, "N02": t2}
        self.influx.raw_by_zone["Z1"] = self._raw_rows([-16.2] * 12, t2)
        e2 = self.engine.evaluate_once(t2)
        self.assertEqual(len(e2), 0)
        self.assertEqual(len(self.notifier.sent), 1)

        # Cycle 3: 2 consecutive readings back within limit -> 1 RECOVERY email with peak -16.2
        t3 = self.now + timedelta(minutes=3)
        self.influx.live_stamps = {"N01": t3, "N02": t3}
        self.influx.raw_by_zone["Z1"] = self._raw_rows([-16.2, -18.5, -19.0], t3)
        e3 = self.engine.evaluate_once(t3)
        self.assertEqual(len(e3), 1)
        self.assertEqual(e3[0]["severity"], "RECOVERY")
        self.assertEqual(e3[0]["state"], "RESOLVED")
        self.assertAlmostEqual(e3[0]["peak_c"], -16.2, places=2)
        self.assertEqual(len(self.notifier.sent), 2)

    def test_door_node_waits_longer_and_is_left_out_of_zone_average(self):
        self.site_cfg["zones"][0]["nodes"] = [
            {"node_id": "N01", "name": "Sensor 1"},
            {"node_id": "N02", "name": "Sensor 2"},
            {"node_id": "N03", "name": "Door", "is_door": True},
        ]
        self.influx.live_stamps = {n: self.now for n in ("N01", "N02", "N03")}

        def rows(hot, minutes):  # `hot` node at -17 (over -18 limit) for `minutes`, others -19
            return [{"timestamp": self.now - timedelta(minutes=i), "node_id": n,
                     "temp_c": -17.0 if n == hot else -19.0, "source": "LIVE"}
                    for n in ("N01", "N02", "N03") for i in range(minutes + 1)]

        self.influx.raw_by_zone["Z1"] = rows("N03", 11)  # door: 11 min < 20 -> quiet
        self.assertEqual(self.engine.evaluate_once(self.now), [])
        self.influx.raw_by_zone["Z1"] = rows("N03", 20)  # door: 20 min -> own alert, zone average untouched
        ev = self.engine.evaluate_once(self.now)
        self.assertEqual([(e["node_id"], e["alert_type"]) for e in ev], [("N03", "node_breach")])

        self.influx.raw_by_zone["Z1"] = rows("N01", 10)  # regular node: 10 min -> alerts
        ev = [e for e in self.engine.evaluate_once(self.now) if e["state"] == "ALERTING"]  # N03 recovery also emitted
        self.assertEqual([(e["node_id"], e["alert_type"]) for e in ev], [("N01", "node_breach")])

    def test_hydration_prevents_duplicate_email_after_restart(self):
        self.influx.raw_by_zone["Z1"] = self._raw_rows([-17.0] * 11, self.now)
        self.engine.evaluate_once(self.now)
        self.assertEqual(len(self.notifier.sent), 1)

        # Simulate backend restart with a fresh engine hydrated from InfluxDB
        restarted = AlertEngine(influx=self.influx, notifier=self.notifier, site_config=self.site_cfg)
        restarted.hydrate_from_influx()
        restarted.evaluate_once(self.now + timedelta(minutes=1))
        self.assertEqual(len(self.notifier.sent), 1)  # Still only 1 email sent

    def test_offline_grouping_and_recovery(self):
        # All nodes silent > 180s -> 1 zone_offline alert (not 2 node_offline alerts)
        self.influx.live_stamps = {
            "N01": self.now - timedelta(seconds=240),
            "N02": self.now - timedelta(seconds=220),
        }
        e1 = self.engine.evaluate_once(self.now)
        self.assertEqual(len(e1), 1)
        self.assertEqual(e1[0]["alert_type"], "zone_offline")
        self.assertEqual(e1[0]["node_id"], "zone_aggregate")

        # Both nodes come back online -> 1 recovery email
        t2 = self.now + timedelta(minutes=2)
        self.influx.live_stamps = {"N01": t2, "N02": t2}
        self.influx.raw_by_zone["Z1"] = self._raw_rows([-19.5, -19.5], t2)
        e2 = self.engine.evaluate_once(t2)
        self.assertEqual(len(e2), 1)
        self.assertEqual(e2[0]["alert_type"], "zone_offline")
        self.assertEqual(e2[0]["state"], "RESOLVED")
        self.assertNotIn("recovered", e2[0]["message"])  # no buffered rows, no tail

    def test_back_online_message_counts_recovered_readings(self):
        self.influx.live_stamps = {"N01": self.now - timedelta(seconds=240), "N02": self.now - timedelta(seconds=220)}
        self.engine.evaluate_once(self.now)
        t2 = self.now + timedelta(minutes=2)
        self.influx.live_stamps = {"N01": t2, "N02": t2}
        self.influx.raw_by_zone["Z1"] = [{"timestamp": self.now, "node_id": "N01", "temp_c": -19.0, "source": "BACKFILL"}] * 3
        e2 = self.engine.evaluate_once(t2)
        self.assertIn("3 readings logged on the board during the outage were recovered", e2[0]["message"])

    def test_forecast_requires_two_cycles_and_respects_toggle(self):
        # Warming +0.1 C/min -> ETA 5 min
        warming = [-19.5 + 0.1 * i for i in range(11)]
        self.influx.raw_by_zone["Z1"] = self._raw_rows(warming, self.now)

        # Cycle 1: streak=1 -> does not fire yet (debounce)
        e1 = self.engine.evaluate_once(self.now)
        self.assertEqual(len(e1), 0)

        # Cycle 2: streak=2 -> fires 1 WARNING email
        t2 = self.now + timedelta(minutes=1)
        self.influx.live_stamps = {"N01": t2, "N02": t2}
        self.influx.raw_by_zone["Z1"] = self._raw_rows(warming, t2)
        e2 = self.engine.evaluate_once(t2)
        self.assertEqual(len(e2), 1)
        self.assertEqual(e2[0]["alert_type"], "forecast_early_warning")
        self.assertEqual(e2[0]["severity"], "WARNING")

    def test_sensor_fault_needs_two_polls_to_open_and_close(self):
        self.influx.failed = {"N01"}  # node alive, sensor answers ok=false
        self.assertEqual(self.engine.evaluate_once(self.now), [])  # 1st bad poll: debounced
        ev = self.engine.evaluate_once(self.now)
        self.assertEqual([(e["node_id"], e["alert_type"], e["severity"]) for e in ev],
                         [("N01", "sensor_fault", "WARNING")])
        self.assertEqual(len(self.notifier.sent), 1)
        self.influx.failed = set()
        self.assertEqual(self.engine.evaluate_once(self.now), [])
        self.assertEqual([e["state"] for e in self.engine.evaluate_once(self.now)], ["RESOLVED"])

    def test_scripted_mock_faults_are_caught(self):
        # Backend "started" 15 min ago: Z4 N12 silent since min 3, N13 ok=false since 10, Z3 N09 erratic since 4.
        # Z1 is mid-ramp (only 2 min over limit) and Z2's door spike is short, so neither may alert yet.
        now = datetime.now(timezone.utc)
        with patch.multiple(settings, USE_MOCK_DATA=True, ERRATIC_WINDOW_MIN=10.0, ERRATIC_JUMP_C=3.0,
                            FORECAST_WINDOW_MIN=10.0), \
                patch.object(mock_scenarios, "START", now - timedelta(minutes=15)):
            eng = AlertEngine(influx=influx_service, notifier=_FakeNotifier())
            eng.sustained_breach_minutes, eng.door_sustained_minutes = 10.0, 20.0
            eng.offline_alert_after_s, eng.forecast_warning_minutes = 180, 20.0
            got = {(e["node_id"], e["alert_type"]) for e in eng.evaluate_once() + eng.evaluate_once()
                   if e["state"] == "ALERTING"}
        self.assertEqual(got, {("N12", "node_offline"), ("N13", "sensor_fault"), ("N09", "sensor_fault")})

    def test_format_email_contains_myt_and_details(self):
        subj, body = format_email({
            "timestamp": self.now,
            "zone_id": "Z1",
            "zone_name": "Freezer Room 1",
            "node_id": "zone_aggregate",
            "alert_type": "sustained_breach",
            "severity": "CRITICAL",
            "state": "ALERTING",
            "message": "Temp above limit",
            "temp_c": -16.5,
            "limit_c": -18.0,
            "peak_c": -16.2,
            "duration_minutes": 10.5,
        })
        self.assertIn("[Frost-IoE CRITICAL]", subj)
        self.assertIn("MYT", body)
        self.assertIn("-16.50 °C", body)
        self.assertIn("10.5 min", body)


class AlertApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from main import app
        from alerts.engine import alert_engine

        self.client = TestClient(app)
        self.engine = alert_engine
        self._orig_cfg = self.engine.get_config()

    def tearDown(self):
        self.engine.update_config(
            alerts_enabled=self._orig_cfg["alerts_enabled"],
            forecast_alerts_enabled=self._orig_cfg["forecast_alerts_enabled"],
            email_alerts_enabled=self._orig_cfg["email_alerts_enabled"],
            sustained_breach_minutes=self._orig_cfg["sustained_breach_minutes"],
            offline_alert_after_s=self._orig_cfg["offline_alert_after_s"],
        )

    def test_alerts_endpoints_and_forecast_toggle(self):
        r_active = self.client.get("/api/alerts/active")
        self.assertEqual(r_active.status_code, 200)
        self.assertIn("alerts", r_active.json())

        r_hist = self.client.get("/api/alerts/history?hours=24")
        self.assertEqual(r_hist.status_code, 200)
        self.assertIn("events", r_hist.json())

        r_cfg = self.client.get("/api/alerts/config")
        self.assertEqual(r_cfg.status_code, 200)
        self.assertTrue(r_cfg.json()["forecast_alerts_enabled"])

        r_patch = self.client.patch("/api/alerts/config", json={"forecast_alerts_enabled": False})
        self.assertEqual(r_patch.status_code, 200)
        self.assertFalse(r_patch.json()["forecast_alerts_enabled"])

        r_test = self.client.post("/api/alerts/test-email")
        self.assertEqual(r_test.status_code, 200)
        self.assertIn("email_sent", r_test.json())


if __name__ == "__main__":
    unittest.main()
