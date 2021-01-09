"""Durable MQTT → SQLite outbox → authenticated HTTP bridge."""

import json
import logging
import os
import signal
import sqlite3
import threading

import httpx
import paho.mqtt.client as mqtt
from pydantic import ValidationError

from .config import DEMO_DEVICE, DEMO_TOKEN
from .edge import Outbox
from .schemas import Reading

log = logging.getLogger("gridsense.mqtt")


def main():
    logging.basicConfig(level=logging.INFO)
    device = os.getenv("DEVICE_ID", DEMO_DEVICE)
    token = os.getenv("DEVICE_TOKEN", DEMO_TOKEN)
    topic = f"gridsense/telemetry/{device}"
    outbox = Outbox(os.getenv("MQTT_OUTBOX", "data/runtime/mqtt.db"))
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"gridsense-bridge-{device}",
        clean_session=False,
        manual_ack=True,
    )
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))
    if os.getenv("MQTT_TLS", "false").lower() == "true":
        client.tls_set(ca_certs=os.getenv("MQTT_CA_FILE"))

    def on_connect(connection, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            log.error("MQTT connection was rejected")
        else:
            connection.subscribe(topic, qos=1)

    def on_message(connection, _userdata, message):
        if len(message.payload) > 4096:
            log.warning("Rejected oversized telemetry")
            connection.ack(message.mid, message.qos)
            return
        try:
            reading = Reading.model_validate(json.loads(message.payload))
            if reading.device_id != device:
                raise ValueError("Device does not match the bridge topic")
            outbox.enqueue(reading)
            # Acknowledge only after a durable local write. HTTP retries are independent.
            connection.ack(message.mid, message.qos)
        except (ValidationError, ValueError):
            log.warning("Rejected invalid telemetry; payload omitted")
            connection.ack(message.mid, message.qos)
        except (OSError, sqlite3.Error):
            log.error("Outbox unavailable; leaving MQTT message unacknowledged")
            connection.disconnect()

    client.on_connect, client.on_message = on_connect, on_message
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    client.connect_async(os.getenv("MQTT_HOST", "127.0.0.1"), int(os.getenv("MQTT_PORT", "1883")))
    client.loop_start()
    try:
        while not stop.is_set():
            try:
                sent = outbox.drain(os.getenv("GRIDSENSE_URL", "http://127.0.0.1:8000"), token)
                if sent:
                    log.info("Acknowledged %d readings", sent)
            except (httpx.HTTPError, ValueError):
                log.warning("HTTP upload pending; durable outbox retained")
            stop.wait(5)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
