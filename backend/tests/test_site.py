import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from config import settings
from influx_client import influx_service
from main import app
from schemas import ComplianceStatus as S
from sitecfg import site


class SiteTests(unittest.TestCase):
    def test_status_bands(self):
        limits = {"max": -18, "warn_margin": 3}
        cs = influx_service.calculate_status
        self.assertEqual([cs(-19, limits), cs(-16, limits), cs(-14, limits), cs(None, limits)],
                         [S.NORMAL, S.WARNING, S.CRITICAL, S.NO_DATA])
        both = {"min": -1, "max": 10, "warn_margin": 3}
        self.assertEqual([cs(-3, both), cs(5, both)], [S.WARNING, S.NORMAL])

    def test_live_follows_config(self):
        zones = influx_service.get_live_readings()
        self.assertEqual([z.zone_id for z in zones], [z["zone_id"] for z in site["zones"]])
        for zone, cfg in zip(zones, site["zones"]):
            self.assertEqual([n.node_id for n in zone.nodes], [n["node_id"] for n in cfg["nodes"]])
            self.assertEqual(zone.limits, cfg["limits"])

    def test_stale_node_goes_offline(self):
        zone = site["zones"][0]
        node, temp = zone["nodes"][0]["node_id"], influx_service._mock_base(zone["zone_id"])
        now = datetime.now(timezone.utc)

        def read(age_s):
            stamp = now - timedelta(seconds=age_s)
            latest = {node: {"ok": (True, stamp), "temp_c": (temp, stamp), "rh_pct": (80.0, stamp)}}
            with patch.object(settings, "USE_MOCK_DATA", False), \
                 patch.object(influx_service, "_latest_by_node", return_value=latest), \
                 patch.object(influx_service, "_rate_by_node", return_value={node: 2.5}):
                return influx_service.get_nodes_live(node_id=node)[0]

        fresh, old = read(10), read(settings.STALE_AFTER_S + 60)
        self.assertEqual((fresh.temp_c, fresh.status, fresh.rate_c_per_hour), (round(temp, 2), S.NORMAL, 2.5))
        self.assertEqual((old.temp_c, old.humidity, old.status, old.rate_c_per_hour), (None, None, S.NO_DATA, None))
        self.assertIsNotNone(old.timestamp)

    def test_site_endpoint(self):
        body = TestClient(app).get("/api/site").json()
        self.assertEqual(body["company"], site["company"])


if __name__ == "__main__":
    unittest.main()
