# RME ADI-2 DAC – MQTT Volume Bridge

Control your RME ADI-2 DAC volume via Home Assistant. A Raspberry Pi handles volume control directly in the DAC hardware (not digitally!) via USB-MIDI, detects online/offline status, and communicates everything over MQTT. The audio source doesn't matter – WiiM, Spotify Connect, CD player, or anything else connected to the DAC.

---

## Quick Start

```bash
git clone https://github.com/YOUR_USER/RME_Bridge.git
cd RME_Bridge
sudo ./install.sh
```

The script installs all dependencies, prompts for MQTT credentials, and starts the service.

---

## Highlights

- Volume control directly in the DAC via USB-MIDI SysEx (no digital clipping)
- Home Assistant integration via MQTT (slider, presets, automations)
- Safety limits: hard boundaries at -60 dB to -10 dB
- DAC online/offline detection with delayed initialization
- Default volume on power-up with retries until USB-MIDI is stable
- Graceful shutdown on SIGTERM (clean MQTT disconnect)
- Optional: Spotify Connect (raspotify) with DAC-controlled start/stop

---

## Hardware

| Component | Tested with |
| --- | --- |
| Raspberry Pi | Pi 4, Pi 5 (any model with USB should work) |
| DAC | RME ADI-2 DAC FS |
| USB cable | Standard USB-A/C to Micro-B |
| OS | Raspberry Pi OS (Bookworm), DietPi, Debian 12/13 |
| MQTT Broker | Mosquitto (e.g. on Home Assistant) |

> **Note:** The RME ADI-2 DAC registers as both a USB audio **and** USB MIDI device. The bridge only uses the MIDI interface for volume control. Audio runs separately (ALSA, SPDIF, analog – doesn't matter).

---

## Signal Flow

```
Audio source (WiiM / raspotify / CD / ...) → RME ADI-2 DAC
                                               ↑
                             MQTT ↔ MIDI Bridge → USB-MIDI → DAC Volume
                                      ↑
                                MQTT Broker ↔ Home Assistant
```

---

## Files

| File | Purpose |
| --- | --- |
| `rme_mqtt_bridge.py` | Main bridge: MQTT ↔ USB-MIDI, DAC detection, volume logic |
| `rme-mqtt-bridge.service` | systemd service for the bridge |
| `env.example` | Template for `/etc/default/rme-mqtt-bridge` (credentials + options) |
| `install.sh` | Automated setup script |
| `raspotify_manager.py` | Optional: start/stop raspotify based on DAC status |
| `raspotify-manager.service` | systemd service for the raspotify manager |
| `conf` | Example `/etc/raspotify/conf` (librespot, bit-perfect) |

---

## Prerequisites

- Raspberry Pi with USB connection to the RME ADI-2 DAC
- MQTT broker (e.g. Mosquitto on Home Assistant)
- Python 3.10+ and `paho-mqtt` (installed automatically)
- `amidi` from `alsa-utils` (installed automatically)

---

## Installation

### Automatic (recommended)

```bash
git clone https://github.com/YOUR_USER/RME_Bridge.git
cd RME_Bridge
sudo ./install.sh
```

### Manual

1) Install dependencies
   ```bash
   sudo apt update
   sudo apt install python3 python3-paho-mqtt alsa-utils
   ```

2) Create MQTT credentials file
   ```bash
   sudo cp env.example /etc/default/rme-mqtt-bridge
   sudo chmod 600 /etc/default/rme-mqtt-bridge
   sudo nano /etc/default/rme-mqtt-bridge   # Set MQTT_USER and MQTT_PASS
   ```

3) Install bridge
   ```bash
   sudo cp rme_mqtt_bridge.py /usr/local/bin/
   sudo chmod +x /usr/local/bin/rme_mqtt_bridge.py
   sudo cp rme-mqtt-bridge.service /etc/systemd/system/
   ```

4) Adjust service file (if needed)
   ```bash
   sudo nano /etc/systemd/system/rme-mqtt-bridge.service
   # Adjust MQTT_HOST, MIDI_PORT etc.
   ```

5) Start
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now rme-mqtt-bridge
   ```

---

## Optional: Raspotify (Spotify Connect)

If you want the Pi to also serve as a Spotify source (instead of e.g. a WiiM Mini):

```bash
sudo apt install raspotify
sudo cp conf /etc/raspotify/conf
sudo cp raspotify_manager.py /usr/local/bin/
sudo chmod +x /usr/local/bin/raspotify_manager.py
sudo cp raspotify-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now raspotify raspotify-manager
```

The raspotify manager automatically starts/stops raspotify when the DAC goes online/offline. Audio is streamed bit-perfect (S32, 320 kbps), volume is controlled in the DAC (not digitally).

---

## DietPi Notes

- DietPi uses systemd (since v6), service files work out of the box
- ALSA utils: `sudo apt install alsa-utils` or via `dietpi-software`
- Audio device issues: check `dietpi-config` → Audio options
- SSH access is enabled by default on DietPi (user: `root`)

---

## MQTT Topics

| Topic | Direction | Payload | Description |
| --- | --- | --- | --- |
| `rme/lineout/db/set` | Subscribe | Float dB (e.g. `-43.5`) | Desired volume |
| `rme/lineout/db/state` | Publish (retained) | Float dB | Actual volume set |
| `rme/dac/status` | Publish (retained) | `online` / `offline` | DAC detection via `amidi -l` |
| `rme/bridge/status` | Publish (retained, LWT) | `online` / `offline` | Bridge status |

---

## Home Assistant Example

```yaml
mqtt:
  number:
    - name: "ADI-2 Line Out Volume"
      command_topic: "rme/lineout/db/set"
      state_topic: "rme/lineout/db/state"
      availability_topic: "rme/dac/status"
      payload_available: "online"
      payload_not_available: "offline"
      min: -60
      max: -10
      step: 0.5
      unit_of_measurement: "dB"
      mode: slider
      optimistic: true
```

---

## Configuration

All settings can be set via environment variables – either in the service file or in the EnvironmentFile (`/etc/default/rme-mqtt-bridge`).

| Variable | Default | Description |
| --- | --- | --- |
| `MQTT_HOST` | `192.168.100.60` | MQTT broker address |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` / `MQTT_PASS` | empty | MQTT auth (via EnvironmentFile) |
| `MIDI_PORT` | `hw:1,0,0` | ALSA MIDI port of the DAC |
| `DEFAULT_DB` | `-50.0` | Volume applied on DAC ready |
| `MIN_DB` / `MAX_DB` | `-60.0` / `-10.0` | Hard limits |
| `DAC_POLL_SECONDS` | `1.0` | DAC detection poll interval |
| `READY_STREAK` | `3` | Consecutive online polls before "ready" |
| `APPLY_RETRIES` | `6` | Retries when setting volume |
| `APPLY_RETRY_DELAY` | `0.6` | Seconds between retries |
| `DEBOUNCE_SECONDS` | `0.03` | Minimum interval between updates |
| `DEBUG` | `0` | Set to `1` for verbose logging |

---

## Troubleshooting

### DAC not detected

```bash
amidi -l          # Lists MIDI devices – "ADI-2 DAC" should appear
aplay -l          # Lists audio devices
lsusb             # Check USB devices
```

- Check USB cable (some cables are charge-only)
- Try a different USB port
- Power-cycle the DAC

### MQTT connection fails

```bash
journalctl -u rme-mqtt-bridge -e
# Look for: "MQTT connected rc=..." or error messages
```

- Verify broker address and port (`MQTT_HOST`, `MQTT_PORT`)
- Check credentials: `/etc/default/rme-mqtt-bridge`
- Firewall: port 1883 must be open from Pi to broker
- Test: `mosquitto_sub -h BROKER_IP -u USER -P PASS -t 'rme/#'`

### Service won't start

```bash
systemctl status rme-mqtt-bridge
journalctl -u rme-mqtt-bridge --no-pager -n 30
```

- Python error? → Run `python3 /usr/local/bin/rme_mqtt_bridge.py` manually
- Missing EnvironmentFile? → See [Installation](#installation)

### Debug mode

```bash
# Set DEBUG=1 via systemd override:
sudo systemctl edit rme-mqtt-bridge
# [Service]
# Environment=DEBUG=1

sudo systemctl restart rme-mqtt-bridge
journalctl -fu rme-mqtt-bridge
```

### Wrong MIDI port

```bash
amidi -l
# Example output:
# Dir Device    Name
# IO  hw:1,0,0  RME ADI-2 DAC MIDI 1
```

If the port is not `hw:1,0,0`, adjust the service file:
```bash
# In /etc/systemd/system/rme-mqtt-bridge.service:
Environment=MIDI_PORT=hw:2,0,0   # Match your actual port
```

---

## License

[MIT License](LICENSE) – Use at your own risk. Volume limits are intentionally conservative.
