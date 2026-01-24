#!/usr/bin/env python3
import os
import subprocess
import paho.mqtt.client as mqtt

MQTT_HOST = "192.168.100.60"
MQTT_TOPIC = "rme/dac/status"

def on_message(client, userdata, msg):
    state = msg.payload.decode().strip()
    if state == "online":
        subprocess.run(["systemctl", "start", "raspotify"], check=False)
    elif state == "offline":
        subprocess.run(["systemctl", "stop", "raspotify"], check=False)

client = mqtt.Client("raspotify_manager")
client.connect(MQTT_HOST, 1883, 30)
client.subscribe(MQTT_TOPIC)
client.on_message = on_message
client.loop_forever()
