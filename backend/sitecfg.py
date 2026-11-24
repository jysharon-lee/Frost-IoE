"""Per-client site config: zones, nodes, limits. Written by us after client consultation; clients never edit it.
Node/zone IDs must match the zone_id/node_id tags the firmware writes."""
import json
from pathlib import Path
from config import settings

# confirmed=False: placeholder limits. TODO confirm against regulation before shipping.
PRESETS = {
    "frozen": {"max": -18, "warn_margin": 3, "confirmed": True},
    "chilled": {"min": -1, "max": 10, "warn_margin": 3, "confirmed": False},
    "ambient": {"min": 15, "max": 30, "warn_margin": 3, "confirmed": False},  # Z1 sim runs ~25C
}


def _load():
    path = Path(settings.SITE_CONFIG)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for zone in cfg["zones"]:  # bad preset / missing key fails at boot, not at 3am
        zone["limits"] = {**PRESETS[zone["preset"]], **zone.get("limits", {})}
    for zone in cfg["zones"]:
        for node in zone["nodes"]:
            node["is_door"] = any(k.lower() in node.get("location", "").lower() for k in settings.DOOR_LOCATION_KEYWORDS)
    print("Door nodes:", [n["node_id"] for z in cfg["zones"] for n in z["nodes"] if n["is_door"]])  # typo check at boot
    zones = [z["zone_id"] for z in cfg["zones"]]
    nodes = [n["node_id"] for z in cfg["zones"] for n in z["nodes"]]
    assert len(zones) == len(set(zones)), "duplicate zone_id in site config"
    assert len(nodes) == len(set(nodes)), "duplicate node_id in site config"
    return cfg


site = _load()

# Drift detection needs commissioning offsets: only nodes that declare one take part.
BASELINE_OFFSETS = {n["node_id"]: n["baseline_offset"]
                    for z in site["zones"] for n in z["nodes"] if "baseline_offset" in n}


def zone_limits(zone_id):
    return next((z["limits"] for z in site["zones"] if z["zone_id"] == zone_id), None)
