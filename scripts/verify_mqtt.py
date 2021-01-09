"""Publish one synthetic observation and verify it reaches the HTTP dashboard."""

import os
import random
import threading
import time
from datetime import UTC, datetime

import httpx
import paho.mqtt.client as mqtt
from gridsense.simulator import simulated_reading


def main():
    connected = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(_client, _userdata, _flags, reason, _properties):
        if not reason.is_failure:
            connected.set()

    client.on_connect = on_connect
    client.connect(os.getenv("MQTT_HOST", "127.0.0.1"), int(os.getenv("MQTT_PORT", "1883")))
    client.loop_start()
    try:
        if not connected.wait(10):
            raise RuntimeError("MQTT connection timed out")
        reading = simulated_reading(datetime.now(UTC), random.Random(7))
        message = client.publish(
            "gridsense/telemetry/inverter-01", reading.model_dump_json(), qos=1
        )
        message.wait_for_publish(timeout=10)
        base = os.getenv("GRIDSENSE_URL", "http://127.0.0.1:8000")
        with httpx.Client(timeout=5) as http:
            for _ in range(30):
                response = http.get(base + "/api/sites/1/overview")
                response.raise_for_status()
                if any(
                    row["event_id"] == str(reading.event_id) for row in response.json()["series"]
                ):
                    print("PASS: MQTT QoS 1 → durable bridge outbox → HTTP ingestion → dashboard")
                    return
                time.sleep(1)
        raise RuntimeError("Published reading did not reach the dashboard")
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
