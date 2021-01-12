import "fake-indexeddb/auto";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  flushReadings,
  loadSnapshot,
  pendingReadings,
  queueReading,
  saveSnapshot,
} from "./outbox";
import type { Reading } from "./types";

const reading = (): Reading => ({
  event_id: crypto.randomUUID(),
  device_id: "inverter-01",
  recorded_at: new Date().toISOString(),
  grid_voltage_v: 230,
  load_w: 1000,
  solar_w: 500,
  battery_soc_pct: 60,
  battery_power_w: 500,
});

afterEach(async () => {
  const rows = await pendingReadings();
  if (rows.length)
    await flushReadings(
      "demo",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              accepted: rows.length,
              event_ids: rows.map((row) => row.event_id),
            }),
          ),
        ),
    );
});

describe("durable browser outbox", () => {
  it("retains telemetry after a network failure", async () => {
    await queueReading(reading());
    await expect(
      flushReadings("demo", vi.fn().mockRejectedValue(new Error("offline"))),
    ).rejects.toThrow("offline");
    expect(await pendingReadings()).toHaveLength(1);
  });
  it("retains telemetry after an incomplete acknowledgement", async () => {
    await queueReading(reading());
    const sender = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ accepted: 1, event_ids: [] })),
      );
    await expect(flushReadings("demo", sender)).rejects.toThrow("Incomplete");
    expect(await pendingReadings()).toHaveLength(1);
  });
  it("accepts idempotent duplicate acknowledgements and flushes once concurrently", async () => {
    const row = reading();
    await queueReading(row);
    const sender = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ duplicates: 1, event_ids: [row.event_id] }),
        ),
      );
    await Promise.all([
      flushReadings("demo", sender),
      flushReadings("demo", sender),
    ]);
    expect(sender).toHaveBeenCalledTimes(1);
    expect(await pendingReadings()).toHaveLength(0);
  });
  it("keeps the last dashboard snapshot across module reads", async () => {
    await saveSnapshot("overview-1", { last_seen: "2023-03-01" });
    expect(await loadSnapshot("overview-1")).toEqual({
      last_seen: "2023-03-01",
    });
  });
});
