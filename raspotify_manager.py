#!/usr/bin/env python3
import os
import subprocess
import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get("MQTT_HOST", "192.168.100.60")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "rme/dac/status")

def on_message(client, userdata, msg):
    state = msg.payload.decode().strip()
    if state == "online":
        subprocess.run(["systemctl", "start", "raspotify"], check=False)
    elif state == "offline":
        subprocess.run(["systemctl", "stop", "raspotify"], check=False)

client = mqtt.Client("raspotify_manager")
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_HOST, MQTT_PORT, 30)
client.subscribe(MQTT_TOPIC)
client.on_message = on_message
client.loop_forever()
