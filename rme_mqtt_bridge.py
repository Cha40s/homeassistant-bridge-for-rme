#!/usr/bin/env python3
"""
RME ADI-2 DAC MQTT <-> USB-MIDI bridge

- Subscribes:  rme/lineout/db/set        (payload: float dB, e.g. -43.5)
- Publishes:   rme/lineout/db/state      (payload: float dB, retained)
- Publishes:   rme/bridge/status         (online/offline via LWT)
- Publishes:   rme/dac/status            (online/offline, retained)

Behavior:
- Safety limits: MIN_DB .. MAX_DB
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

Improvements (requested):
1) Publish db/state only when it actually changed, quantized to 0.5 dB steps
3) Watchdog: if MIDI reader (amidi -d) dies while DAC is ready -> restart it
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
READY_STREAK = int(os.environ.get("READY_STREAK", "3"))               # consecutive online polls required
APPLY_RETRIES = int(os.environ.get("APPLY_RETRIES", "6"))             # retries for default/pending
APPLY_RETRY_DELAY = float(os.environ.get("APPLY_RETRY_DELAY", "0.6")) # seconds between retries

MANAGE_RASPOTIFY = os.environ.get("MANAGE_RASPOTIFY", "1") == "1"

DEBOUNCE_SECONDS = float(os.environ.get("DEBOUNCE_SECONDS", "0.03"))

# Incoming MIDI (DAC -> Pi) debounce to avoid flooding MQTT when knob is turned
MIDI_RX_DEBOUNCE_SECONDS = float(os.environ.get("MIDI_RX_DEBOUNCE_SECONDS", "0.02"))

# Restart delay if amidi dies
MIDI_RESTART_SECONDS = float(os.environ.get("MIDI_RESTART_SECONDS", "1.0"))

# Debug switch from systemd env: DEBUG=1
DEBUG = os.environ.get("DEBUG", "0") == "1"


def dbg(msg: str) -> None:
    if DEBUG:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [DEBUG] {msg}", flush=True)


def info(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [INFO ] {msg}", flush=True)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def quantize_05(db: float) -> float:
    # 0.5 dB steps (matches HA slider + your DAC expectation)
    return round(db * 2.0) / 2.0


# --- State / pending tracking ---
last_sent_ts = 0.0
pending_db: float | None = None

# last state that we actually published to MQTT (already clamped+quantized)
last_published_db: float | None = None

# "online" = currently detected; "ready" = stable enough to accept MIDI
dac_online = False
dac_ready = False
online_streak = 0

# --- MIDI reader runtime ---
midi_proc: subprocess.Popen | None = None
midi_thread: threading.Thread | None = None
midi_stop = threading.Event()
last_rx_ts = 0.0

# for watchdog
last_midi_restart_ts = 0.0


def publish_state_if_changed(client: mqtt.Client, db: float, reason: str) -> None:
    """Clamp + quantize (0.5 dB), publish retained only if changed."""
    global last_published_db
    dbq = quantize_05(clamp(db, MIN_DB, MAX_DB))

    if last_published_db is not None and abs(dbq - last_published_db) < 1e-9:
        dbg(f"state unchanged ({dbq:.1f} dB) -> skip publish ({reason})")
        return

    last_published_db = dbq
    dbg(f"Publishing state ({reason}) {TOPIC_STATE_DB} = {dbq:.1f} (retain)")
    client.publish(TOPIC_STATE_DB, f"{dbq:.1f}", qos=1, retain=True)


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
    # We send in 0.1 dB units, but input is already quantized to 0.5 dB.
    db = quantize_05(clamp(db, MIN_DB, MAX_DB))

    addr = 3   # Line Out Channel Settings
    idx = 12   # Volume

    val = int(round(db * 10.0))  # 0.1 dB steps (so 0.5 dB => multiples of 5)
    v11 = val & 0x7FF            # 11-bit two's complement

    upper4 = (v11 >> 7) & 0x0F
    lower7 = v11 & 0x7F

    b0 = ((addr & 0x0F) << 3) | ((idx >> 2) & 0x07)
    b1 = ((idx & 0x03) << 5) | (1 << 4) | upper4  # scale_bit=1 for volume
    b2 = lower7

    # cmd=0x02 works for setting on this device
    return f"F0 00 20 0D 71 02 {b0:02X} {b1:02X} {b2:02X} F7"


def _parse_hex_stream_from_line(line: str) -> str | None:
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

    Match header: F0 00 20 0D 71 <cmd> ...
    Accept cmd in {01,02}.
    """
    parts = [p.upper() for p in hex_stream.strip().split() if p]
    if len(parts) < 9:
        return None

    header = ["F0", "00", "20", "0D", "71"]
    for i in range(0, len(parts) - len(header)):
        if parts[i:i + 5] != header:
            continue

        if i + 8 >= len(parts):
            return None

        cmd = parts[i + 5]
        if cmd not in ("01", "02"):
            dbg(f"RX RME header found but cmd={cmd} not in (01,02) -> ignore")
            continue

        try:
            end_idx = parts.index("F7", i + 5)
        except ValueError:
            dbg("RX RME header found but no F7 terminator -> ignore")
            continue

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
            continue

        if scale_bit != 1:
            dbg("RX matched addr=3 idx=12 but scale_bit!=1 -> ignore")
            continue

        upper4 = b1 & 0x0F
        lower7 = b2 & 0x7F
        v11 = (upper4 << 7) | lower7

        if v11 & 0x400:
            v11 -= 0x800

        db = v11 / 10.0
        db = quantize_05(clamp(db, MIN_DB, MAX_DB))
        dbg(f"RX LineOutVol OK: raw_v11={v11} -> {db:.1f} dB (cmd={cmd})")
        return db

    return None


def apply_volume_with_retries(db: float) -> None:
    """Fire-and-forget retries (device may ignore early during USB init)."""
    db = quantize_05(clamp(db, MIN_DB, MAX_DB))
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

        publish_state_if_changed(client, db, reason="midi_rx")

    # process ended or stop requested
    rc = None
    try:
        rc = midi_proc.poll() if midi_proc else None
    except Exception:
        rc = None

    dbg(f"MIDI monitor exiting (amidi returncode={rc}); cleaning up")

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


def midi_monitor_healthy() -> bool:
    """Consider the monitor healthy if thread is alive and process is running."""
    if not (midi_thread and midi_thread.is_alive()):
        return False
    if midi_proc is None:
        return False
    try:
        return midi_proc.poll() is None
    except Exception:
        return False


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

    db = quantize_05(clamp(db, MIN_DB, MAX_DB))

    # Mirror to state topic (retained), but only if changed
    publish_state_if_changed(client, db, reason="mqtt_set_echo")

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
    global dac_online, dac_ready, online_streak, pending_db, last_midi_restart_ts

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

            start_midi_monitor(client)
            last_midi_restart_ts = time.time()

            # Apply default (retries), then pending (retries)
            default_db = quantize_05(clamp(DEFAULT_DB, MIN_DB, MAX_DB))
            apply_volume_with_retries(default_db)
            publish_state_if_changed(client, default_db, reason="default_after_ready")

            if pending_db is not None:
                dbg(f"Applying pending after ready: {pending_db:.1f} dB")
                apply_volume_with_retries(pending_db)
                publish_state_if_changed(client, pending_db, reason="pending_after_ready")
                pending_db = None

        # If ready and we still have pending (debounce), apply it
        if dac_ready and pending_db is not None:
            dbg(f"Applying pending (debounce tail): {pending_db:.1f} dB")
            apply_volume_with_retries(pending_db)
            publish_state_if_changed(client, pending_db, reason="pending_tail")
            pending_db = None

        # --- Watchdog: restart MIDI reader if it died while DAC is ready ---
        if dac_ready:
            healthy = midi_monitor_healthy()
            if not healthy:
                now = time.time()
                if now - last_midi_restart_ts >= MIDI_RESTART_SECONDS:
                    info("MIDI monitor not healthy while DAC ready -> restarting")
                    stop_midi_monitor()
                    start_midi_monitor(client)
                    last_midi_restart_ts = now
                else:
                    dbg("MIDI monitor not healthy, but restart suppressed due to backoff")

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
