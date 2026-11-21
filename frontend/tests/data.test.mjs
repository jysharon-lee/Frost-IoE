import test from "node:test";
import assert from "node:assert/strict";

import { getOutages, getWorstNode } from "../src/utils/data.js";

const now = Date.parse("2026-11-18T10:00:00Z");
const fresh = new Date(now - 10_000).toISOString();
const stale = new Date(now - 600_000).toISOString();

const node = (name, timestamp, temp_c = -19) => ({
  node_id: name,
  name,
  timestamp,
  temp_c,
});

const zone = (name, ...nodes) => ({ name, nodes });

test("no outage when everything reports", () => {
  const zones = [zone("Zone 1", node("Sensor 1", fresh))];
  assert.deepEqual(getOutages(zones, now), []);
});

test("one sensor down", () => {
  const zones = [
    zone("Zone 1", node("Sensor 1", fresh), node("Sensor 2", stale)),
    zone("Zone 2", node("Sensor 3", fresh)),
  ];
  assert.deepEqual(getOutages(zones, now), ["Sensor 2 in Zone 1 down"]);
});

test("sensor that answered ok=false counts as down", () => {
  const zones = [
    zone("Zone 1", node("Sensor 1", fresh, null), node("Sensor 2", fresh)),
  ];
  assert.deepEqual(getOutages(zones, now), ["Sensor 1 in Zone 1 down"]);
});

test("whole zone down", () => {
  const zones = [
    zone("Zone 1", node("Sensor 1", stale), node("Sensor 2", stale)),
    zone("Zone 2", node("Sensor 3", fresh)),
  ];
  assert.deepEqual(getOutages(zones, now), ["Zone 1 down"]);
});

test("everything down is a power outage", () => {
  const zones = [
    zone("Zone 1", node("Sensor 1", stale)),
    zone("Zone 2", node("Sensor 2", stale)),
  ];
  assert.deepEqual(getOutages(zones, now), ["Power down"]);
});

test("warmest node ignores stale and invalid readings", () => {
  const nodes = [
    node("a", fresh, -19),
    node("b", fresh, -17),
    node("c", stale, 5),
    node("d", fresh, null),
  ];
  assert.equal(getWorstNode(nodes, now).name, "b");
  assert.equal(getWorstNode([node("c", stale)], now), null);
});
