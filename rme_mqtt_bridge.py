#!/usr/bin/env python3
"""
RME ADI-2 DAC MQTT <-> USB-MIDI bridge

- Subscribes:  rme/lineout/db/set        (payload: float dB, e.g. -43.5)
- Publishes:   rme/lineout/db/state      (payload: float dB, retained)
- Publishes:   rme/bridge/status         (online/offline via LWT)
- Publishes:   rme/dac/status            (online/offline, retained)

Behavior:
- Safety limits: -60.0 dB .. -10.0 dB
- DAC presence detection via `amidi -l` ("ADI-2 DAC")
- If DAC offline: remember latest requested volume as pending
- When DAC becomes "ready": apply DEFAULT_DB, then pending (if any)
- "Ready" means: detected online N consecutive polls
- Default/pending are sent with retries (device may ignore early after power-on)
"""

import os
import time
import subprocess
import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get("MQTT_HOST", "192.168.100.60")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MIDI_PORT = os.environ.get("MIDI_PORT", "hw:1,0,0")

TOPIC_SET_DB = "rme/lineout/db/set"
TOPIC_STATE_DB = "rme/lineout/db/state"
TOPIC_BRIDGE_STATUS = "rme/bridge/status"
TOPIC_DAC_STATUS = "rme/dac/status"

DEFAULT_DB = float(os.environ.get("DEFAULT_DB", "-50.0"))
MIN_DB = float(os.environ.get("MIN_DB", "-60.0"))
MAX_DB = float(os.environ.get("MAX_DB", "-10.0"))

DAC_POLL_SECONDS = float(os.environ.get("DAC_POLL_SECONDS", "1.0"))

# DAC readiness tuning:
READY_STREAK = int(os.environ.get("READY_STREAK", "3"))          # consecutive online polls required
APPLY_RETRIES = int(os.environ.get("APPLY_RETRIES", "6"))         # retries for default/pending
APPLY_RETRY_DELAY = float(os.environ.get("APPLY_RETRY_DELAY", "0.6"))  # seconds between retries

MANAGE_RASPOTIFY = os.environ.get("MANAGE_RASPOTIFY", "1") == "1"

DEBOUNCE_SECONDS = float(os.environ.get("DEBOUNCE_SECONDS", "0.03"))

last_sent_ts = 0.0
pending_db: float | None = None

# "online" = currently detected; "ready" = stable enough to accept MIDI
dac_online = False
dac_ready = False
online_streak = 0


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def is_dac_online() -> bool:
    try:
        out = subprocess.check_output(["amidi", "-l"], text=True, stderr=subprocess.DEVNULL)
        return "ADI-2 DAC" in out
    except Exception:
        return False


def send_sysex(hex_sysex: str) -> None:
    try:
        subprocess.run(
            ["amidi", "-p", MIDI_PORT, "-S", hex_sysex],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def db_to_sysex_lineout(db: float) -> str:
    db = clamp(db, MIN_DB, MAX_DB)

    addr = 3   # Line Out Channel Settings
    idx = 12   # Volume

    val = int(round(db * 10.0))  # 0.1 dB steps
    v11 = val & 0x7FF            # 11-bit two's complement

    upper4 = (v11 >> 7) & 0x0F
    lower7 = v11 & 0x7F

    b0 = ((addr & 0x0F) << 3) | ((idx >> 2) & 0x07)
    b1 = ((idx & 0x03) << 5) | (1 << 4) | upper4  # scale_bit=1 for volume
    b2 = lower7

    return f"F0 00 20 0D 71 02 {b0:02X} {b1:02X} {b2:02X} F7"


def apply_volume_with_retries(db: float) -> None:
    """Fire-and-forget retries (device may ignore early during USB init)."""
    sysex = db_to_sysex_lineout(db)
    for _ in range(APPLY_RETRIES):
        send_sysex(sysex)
        time.sleep(APPLY_RETRY_DELAY)


def on_connect(client, userdata, flags, reason_code, properties):
    client.publish(TOPIC_BRIDGE_STATUS, "online", qos=1, retain=True)
    client.publish(TOPIC_DAC_STATUS, "online" if is_dac_online() else "offline", qos=1, retain=True)
    client.subscribe(TOPIC_SET_DB, qos=1)


def on_message(client, userdata, msg):
    global last_sent_ts, pending_db, dac_ready

    if msg.topic != TOPIC_SET_DB:
        return

    try:
        db = float(msg.payload.decode("utf-8").strip())
    except Exception:
        return

    db = clamp(db, MIN_DB, MAX_DB)
    client.publish(TOPIC_STATE_DB, f"{db:.1f}", qos=1, retain=True)

    if not dac_ready:
        pending_db = db
        return

    now = time.time()
    if now - last_sent_ts < DEBOUNCE_SECONDS:
        pending_db = db
        return

    send_sysex(db_to_sysex_lineout(db))
    last_sent_ts = now
    pending_db = None


def main():
    global dac_online, dac_ready, online_streak, pending_db

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="rme_mqtt_bridge",
        protocol=mqtt.MQTTv311,
    )

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.will_set(TOPIC_BRIDGE_STATUS, "offline", qos=1, retain=True)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()

    while True:
        online = is_dac_online()

        if online:
            online_streak += 1
        else:
            online_streak = 0

        # Update dac_online state + publish transitions
        if online != dac_online:
            dac_online = online
            client.publish(TOPIC_DAC_STATUS, "online" if online else "offline", qos=1, retain=True)

            # when it disappears -> not ready
            if not online:
                dac_ready = False
                if MANAGE_RASPOTIFY:
                    subprocess.run(["systemctl", "stop", "raspotify"], check=False)

        # Become "ready" only after N consecutive online polls
        if dac_online and not dac_ready and online_streak >= READY_STREAK:
            dac_ready = True
            if MANAGE_RASPOTIFY:
                subprocess.run(["systemctl", "start", "raspotify"], check=False)

            # Apply default (retries), then pending (retries)
            default_db = clamp(DEFAULT_DB, MIN_DB, MAX_DB)
            apply_volume_with_retries(default_db)
            client.publish(TOPIC_STATE_DB, f"{default_db:.1f}", qos=1, retain=True)

            if pending_db is not None:
                apply_volume_with_retries(pending_db)
                client.publish(TOPIC_STATE_DB, f"{pending_db:.1f}", qos=1, retain=True)
                pending_db = None

        # If ready and we still have pending (debounce), apply it
        if dac_ready and pending_db is not None:
            apply_volume_with_retries(pending_db)
            client.publish(TOPIC_STATE_DB, f"{pending_db:.1f}", qos=1, retain=True)
            pending_db = None

        time.sleep(DAC_POLL_SECONDS)


if __name__ == "__main__":
    main()

