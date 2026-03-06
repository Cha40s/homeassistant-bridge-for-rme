#!/usr/bin/env python3
"""
Optional raspotify manager: starts/stops raspotify based on DAC status via MQTT.

Only needed when using the Pi's built-in raspotify (librespot) as Spotify source.
Not required when using an external source (e.g. WiiM Mini via SPDIF).
"""

import os
import signal
import subprocess
import sys
import time
import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get("MQTT_HOST", "192.168.100.60")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "rme/dac/status")


def info(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [INFO ] {msg}", flush=True)


def on_connect(client, userdata, flags, reason_code, properties):
    info(f"MQTT connected rc={reason_code} host={MQTT_HOST}:{MQTT_PORT}")
    client.subscribe(MQTT_TOPIC, qos=1)


def on_message(client, userdata, msg):
    state = msg.payload.decode().strip()
    if state == "online":
        info("DAC online -> starting raspotify")
        subprocess.run(["systemctl", "start", "raspotify"], check=False)
    elif state == "offline":
        info("DAC offline -> stopping raspotify")
        subprocess.run(["systemctl", "stop", "raspotify"], check=False)


def main():
    info("raspotify_manager starting")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="raspotify_manager",
        protocol=mqtt.MQTTv311,
    )

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.on_connect = on_connect
    client.on_message = on_message

    def _shutdown(signum, frame):
        info(f"Signal {signum} received, shutting down...")
        client.disconnect()

    signal.signal(signal.SIGTERM, _shutdown)

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_forever()
    info("raspotify_manager stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        info("Interrupted, exiting")
        sys.exit(0)
