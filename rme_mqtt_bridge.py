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

MIDI RX (DAC -> Pi):
- Starts `amidi -p <MIDI_PORT> -d` when DAC becomes ready
- Parses incoming hex bytes, decodes RME SysEx for Line Out volume
- Mirrors detected Line Out volume changes to MQTT state topic
- Verbose debug logging when DEBUG=1
"""

import os
import time
import subprocess
import threading
import re
import sys
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

# Incoming MIDI (DAC -> Pi) debounce to avoid flooding MQTT when knob is turned
MIDI_RX_DEBOUNCE_SECONDS = float(os.environ.get("MIDI_RX_DEBOUNCE_SECONDS", "0.02"))

# Debug switch from systemd env: DEBUG=1
DEBUG = os.environ.get("DEBUG", "0") == "1"


def dbg(msg: str) -> None:
    if DEBUG:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [DEBUG] {msg}", flush=True)


def info(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [INFO ] {msg}", flush=True)


last_sent_ts = 0.0
pending_db: float | None = None

# "online" = currently detected; "ready" = stable enough to accept MIDI
dac_online = False
dac_ready = False
online_streak = 0

# MIDI reader runtime
midi_proc: subprocess.Popen | None = None
midi_thread: threading.Thread | None = None
midi_stop = threading.Event()
last_rx_ts = 0.0


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def is_dac_online() -> bool:
    try:
        out = subprocess.check_output(["amidi", "-l"], text=True, stderr=subprocess.DEVNULL)
        ok = "ADI-2 DAC" in out
        dbg(f"is_dac_online: {'YES' if ok else 'NO'} (match='ADI-2 DAC')\n{out.strip()}")
        return ok
    except Exception as e:
        dbg(f"is_dac_online: exception: {e}")
        return False


def send_sysex(hex_sysex: str) -> None:
    try:
        if DEBUG:
            dbg(f"send_sysex -> amidi -p {MIDI_PORT} -S '{hex_sysex}'")
        subprocess.run(
            ["amidi", "-p", MIDI_PORT, "-S", hex_sysex],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        dbg(f"send_sysex: exception: {e}")


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

    # NOTE: historically we sent cmd=0x02 here. DAC reports changes with cmd=0x01.
    return f"F0 00 20 0D 71 02 {b0:02X} {b1:02X} {b2:02X} F7"


def _parse_hex_stream_from_line(line: str) -> str | None:
    """
    Extract all 2-hex-byte tokens from an arbitrary amidi output line.
    Returns normalized "AA BB CC ..." or None.
    """
    tokens = re.findall(r"(?i)\b[0-9a-f]{2}\b", line)
    if not tokens:
        return None
    return " ".join(t.upper() for t in tokens)


def _decode_addr_idx_scale(b0: int, b1: int) -> tuple[int, int, int]:
    addr = (b0 >> 3) & 0x0F
    idx = ((b0 & 0x07) << 2) | ((b1 >> 5) & 0x03)
    scale_bit = (b1 >> 4) & 0x01
    return addr, idx, scale_bit


def sysex_to_db_if_lineout_volume(hex_stream: str) -> float | None:
    """
    Decode RME ADI-2 SysEx for Line Out volume (addr=3, idx=12).

    Important: DAC sends different opcodes:
      - 0x02 often used for "set" style messages
      - 0x01 observed in your logs for "report/change" messages

    We therefore match header: F0 00 20 0D 71 <cmd> ...
    and accept cmd in {01, 02} for this decoder.
    """
    parts = [p.upper() for p in hex_stream.strip().split() if p]
    if len(parts) < 9:
        return None

    # Search for header: F0 00 20 0D 71
    header = ["F0", "00", "20", "0D", "71"]
    for i in range(0, len(parts) - len(header)):
        if parts[i:i + 5] != header:
            continue

        # Need at least cmd + b0 b1 b2 afterwards
        if i + 8 >= len(parts):
            return None

        cmd = parts[i + 5]
        if cmd not in ("01", "02"):
            # Not a command type we handle for volume (still log in debug sometimes)
            dbg(f"RX RME header found but cmd={cmd} not in (01,02) -> ignore")
            continue

        # find terminating F7 after cmd
        try:
            end_idx = parts.index("F7", i + 5)
        except ValueError:
            dbg("RX RME header found but no F7 terminator -> ignore")
            continue

        # ensure we have at least cmd+b0+b1+b2 before F7
        if i + 9 > end_idx:
            dbg(f"RX RME cmd={cmd} but too short before F7 (end_idx={end_idx}, start={i})")
            continue

        try:
            b0 = int(parts[i + 6], 16)
            b1 = int(parts[i + 7], 16)
            b2 = int(parts[i + 8], 16)
        except Exception as e:
            dbg(f"RX parse b0/b1/b2 failed: {e}")
            continue

        addr, idx, scale_bit = _decode_addr_idx_scale(b0, b1)
        dbg(f"RX RME cmd={cmd} b0={b0:02X} b1={b1:02X} b2={b2:02X} -> addr={addr} idx={idx} scale={scale_bit}")

        if addr != 3 or idx != 12:
            # Not Line Out volume
            continue

        if scale_bit != 1:
            dbg("RX matched addr=3 idx=12 but scale_bit!=1 -> ignore")
            continue

        upper4 = b1 & 0x0F
        lower7 = b2 & 0x7F
        v11 = (upper4 << 7) | lower7  # 11-bit two's complement

        # sign extend 11-bit
        if v11 & 0x400:
            v11 -= 0x800

        db = v11 / 10.0
        db = clamp(db, MIN_DB, MAX_DB)
        dbg(f"RX LineOutVol OK: raw_v11={v11} -> {db:.1f} dB (cmd={cmd})")
        return db

    return None


def apply_volume_with_retries(db: float) -> None:
    """Fire-and-forget retries (device may ignore early during USB init)."""
    sysex = db_to_sysex_lineout(db)
    dbg(f"apply_volume_with_retries({db:.1f} dB) retries={APPLY_RETRIES} delay={APPLY_RETRY_DELAY}")
    for n in range(APPLY_RETRIES):
        dbg(f"  retry {n+1}/{APPLY_RETRIES}")
        send_sysex(sysex)
        time.sleep(APPLY_RETRY_DELAY)


def _midi_reader_loop(client: mqtt.Client) -> None:
    global midi_proc, last_rx_ts

    cmd = ["amidi", "-p", MIDI_PORT, "-d"]
    dbg(f"Starting MIDI monitor: {' '.join(cmd)}")

    try:
        midi_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        info(f"MIDI monitor could not start: {e}")
        midi_proc = None
        return

    if not midi_proc.stdout:
        info("MIDI monitor: no stdout pipe (unexpected)")
        return

    def _stderr_pump(proc: subprocess.Popen) -> None:
        if not proc.stderr:
            return
        for eline in proc.stderr:
            if midi_stop.is_set():
                break
            dbg(f"amidi stderr: {eline.rstrip()}")

    if DEBUG and midi_proc.stderr:
        threading.Thread(target=_stderr_pump, args=(midi_proc,), daemon=True).start()

    dbg("MIDI monitor running; waiting for incoming messages...")

    for line in midi_proc.stdout:
        if midi_stop.is_set():
            dbg("MIDI monitor stop requested; breaking read loop")
            break

        raw_line = line.rstrip("\n")
        dbg(f"amidi stdout: {raw_line}")

        hex_stream = _parse_hex_stream_from_line(raw_line)
        if not hex_stream:
            dbg("amidi line contained no hex tokens -> skip")
            continue

        dbg(f"Parsed hex stream: {hex_stream}")

        db = sysex_to_db_if_lineout_volume(hex_stream)
        if db is None:
            dbg("No Line Out volume SysEx detected in this line")
            continue

        now = time.time()
        if now - last_rx_ts < MIDI_RX_DEBOUNCE_SECONDS:
            dbg(f"RX debounce: {now-last_rx_ts:.3f}s < {MIDI_RX_DEBOUNCE_SECONDS}s -> drop")
            continue
        last_rx_ts = now

        dbg(f"Publishing RX volume to MQTT {TOPIC_STATE_DB} = {db:.1f} (retain)")
        client.publish(TOPIC_STATE_DB, f"{db:.1f}", qos=1, retain=True)

    dbg("MIDI monitor exiting; terminating amidi process")
    try:
        if midi_proc and midi_proc.poll() is None:
            midi_proc.terminate()
    except Exception as e:
        dbg(f"terminate amidi exception: {e}")

    midi_proc = None


def start_midi_monitor(client: mqtt.Client) -> None:
    global midi_thread
    if midi_thread and midi_thread.is_alive():
        dbg("start_midi_monitor: already running")
        return
    midi_stop.clear()
    midi_thread = threading.Thread(target=_midi_reader_loop, args=(client,), daemon=True)
    midi_thread.start()
    dbg("start_midi_monitor: thread started")


def stop_midi_monitor() -> None:
    global midi_proc
    dbg("stop_midi_monitor: stopping")
    midi_stop.set()
    try:
        if midi_proc and midi_proc.poll() is None:
            midi_proc.terminate()
            dbg("stop_midi_monitor: terminated amidi process")
    except Exception as e:
        dbg(f"stop_midi_monitor: exception: {e}")


def on_connect(client, userdata, flags, reason_code, properties):
    info(f"MQTT connected rc={reason_code} host={MQTT_HOST}:{MQTT_PORT}")
    client.publish(TOPIC_BRIDGE_STATUS, "online", qos=1, retain=True)
    client.publish(TOPIC_DAC_STATUS, "online" if is_dac_online() else "offline", qos=1, retain=True)
    client.subscribe(TOPIC_SET_DB, qos=1)
    dbg(f"Subscribed to {TOPIC_SET_DB}")


def on_message(client, userdata, msg):
    global last_sent_ts, pending_db, dac_ready

    dbg(f"MQTT msg topic={msg.topic} payload={msg.payload!r}")

    if msg.topic != TOPIC_SET_DB:
        return

    try:
        db = float(msg.payload.decode("utf-8").strip())
    except Exception as e:
        dbg(f"MQTT payload parse error: {e}")
        return

    db = clamp(db, MIN_DB, MAX_DB)
    client.publish(TOPIC_STATE_DB, f"{db:.1f}", qos=1, retain=True)
    dbg(f"Published state echo: {db:.1f} dB (retain)")

    if not dac_ready:
        pending_db = db
        dbg(f"DAC not ready -> pending_db={pending_db:.1f}")
        return

    now = time.time()
    if now - last_sent_ts < DEBOUNCE_SECONDS:
        pending_db = db
        dbg(f"TX debounce: {now-last_sent_ts:.3f}s < {DEBOUNCE_SECONDS}s -> pending_db={pending_db:.1f}")
        return

    dbg(f"Sending volume to DAC: {db:.1f} dB")
    send_sysex(db_to_sysex_lineout(db))
    last_sent_ts = now
    pending_db = None


def main():
    global dac_online, dac_ready, online_streak, pending_db

    info(f"Bridge starting (DEBUG={'1' if DEBUG else '0'}) MIDI_PORT={MIDI_PORT}")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="rme_mqtt_bridge",
        protocol=mqtt.MQTTv311,
    )

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
        dbg("MQTT auth enabled (user set)")

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
            info(f"DAC transition: {'online' if online else 'offline'}")
            client.publish(TOPIC_DAC_STATUS, "online" if online else "offline", qos=1, retain=True)

            # when it disappears -> not ready
            if not online:
                dac_ready = False
                stop_midi_monitor()
                if MANAGE_RASPOTIFY:
                    dbg("Stopping raspotify (DAC offline)")
                    subprocess.run(["systemctl", "stop", "raspotify"], check=False)

        # Become "ready" only after N consecutive online polls
        if dac_online and not dac_ready and online_streak >= READY_STREAK:
            dac_ready = True
            info(f"DAC READY (online_streak={online_streak} >= READY_STREAK={READY_STREAK})")

            if MANAGE_RASPOTIFY:
                dbg("Starting raspotify (DAC ready)")
                subprocess.run(["systemctl", "start", "raspotify"], check=False)

            # Start MIDI monitor once device is stable
            start_midi_monitor(client)

            # Apply default (retries), then pending (retries)
            default_db = clamp(DEFAULT_DB, MIN_DB, MAX_DB)
            apply_volume_with_retries(default_db)
            client.publish(TOPIC_STATE_DB, f"{default_db:.1f}", qos=1, retain=True)
            dbg(f"Published default state: {default_db:.1f} dB")

            if pending_db is not None:
                dbg(f"Applying pending after ready: {pending_db:.1f} dB")
                apply_volume_with_retries(pending_db)
                client.publish(TOPIC_STATE_DB, f"{pending_db:.1f}", qos=1, retain=True)
                pending_db = None

        # If ready and we still have pending (debounce), apply it
        if dac_ready and pending_db is not None:
            dbg(f"Applying pending (debounce tail): {pending_db:.1f} dB")
            apply_volume_with_retries(pending_db)
            client.publish(TOPIC_STATE_DB, f"{pending_db:.1f}", qos=1, retain=True)
            pending_db = None

        time.sleep(DAC_POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        info("Interrupted, exiting")
        try:
            stop_midi_monitor()
        except Exception:
            pass
        sys.exit(0)

