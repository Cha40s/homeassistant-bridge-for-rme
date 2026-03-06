# Home Assistant MQTT Bridge for RME ADI-2 DAC

> **Disclaimer:** This project is an independent open-source software and is not affiliated with, endorsed by, or in any way officially connected to RME Audio (Audio AG) or any of its subsidiaries or affiliates. The official RME Audio website can be found at [https://www.rme-audio.de](https://www.rme-audio.de). The name "RME" as well as related names, marks, emblems, and images are registered trademarks of their respective owners.

Control your RME ADI-2 DAC **Line Out** volume via Home Assistant. A Raspberry Pi handles volume control directly in the DAC hardware (not digitally!) via USB-MIDI, detects online/offline status, and communicates everything over MQTT.

> **Important:** This bridge controls **Line Out volume only** (not headphone output or input selection). The USB connection is used exclusively for MIDI control – audio can come from any source.

---

## Quick Start

```bash
git clone https://github.com/Cha40s/homeassistant-bridge-for-rme.git
cd homeassistant-bridge-for-rme
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

> **Note:** The RME ADI-2 DAC registers as both a USB audio **and** USB MIDI device. The bridge only uses the MIDI interface for volume control. Audio runs separately.

---

## Audio Source Setup

The bridge controls volume regardless of how audio reaches the DAC. You need to set the correct **DAC input** to match your setup:

| Audio source | Connection | DAC input setting |
| --- | --- | --- |
| **External player** (WiiM Mini, CD, streamer) | SPDIF optical/coax to DAC | Set DAC to **SPDIF** or **Optical** |
| **This Raspberry Pi** (raspotify / Spotify Connect) | USB to DAC (shared with MIDI) | Set DAC to **USB** |

The installer will ask which setup you use and install raspotify automatically if needed.

### Why SPDIF is enough

The RME ADI-2 DAC's USB input is technically superior to SPDIF (higher sample rates, native DSD, async transfer). However, these advantages only matter with hi-res source material beyond CD quality. Spotify's highest tiers top out well within SPDIF's capabilities:

| Spotify quality | Format | Bitrate |
| --- | --- | --- |
| Normal | OGG | ~96 kbit/s |
| High | OGG | ~160 kbit/s |
| Very high | OGG | ~320 kbit/s |
| Lossless | FLAC | up to 24-bit/44.1 kHz |

Even Spotify Lossless at 24-bit/44.1 kHz is handled perfectly by SPDIF (which supports up to 24-bit/192 kHz). There is **no audible difference** between USB and SPDIF when the source is Spotify – at any quality level.

This means you can use an affordable network streamer like the [WiiM Mini](https://www.wiimhome.com/) via SPDIF and keep the USB port free for MIDI control only. The WiiM Mini supports Spotify Connect, AirPlay, and Chromecast at a fraction of the cost of high-end streamers – a perfect match for this setup.

---

## Signal Flow


<img width="2752" height="1536" alt="Gemini_Generated_Image_ijvwl3ijvwl3ijvw" src="https://github.com/user-attachments/assets/b2ab52b4-6726-4341-ada4-ff86f2e97c6b" />

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
git clone https://github.com/Cha40s/homeassistant-bridge-for-rme.git
cd homeassistant-bridge-for-rme
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

If you chose option 2 (USB audio) during installation, raspotify is already set up. For manual installation:

```bash
sudo apt install raspotify
sudo cp conf /etc/raspotify/conf
sudo cp raspotify_manager.py /usr/local/bin/
sudo chmod +x /usr/local/bin/raspotify_manager.py
sudo cp raspotify-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now raspotify raspotify-manager
```

The raspotify manager automatically starts/stops raspotify when the DAC goes online/offline. Audio is streamed bit-perfect (S32, 320 kbps), volume is controlled in the DAC (not digitally). Make sure the DAC input is set to **USB**.

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

## Acknowledgements

This project is largely built with the help of AI ([Claude](https://claude.ai) by Anthropic).

It relies on the following open-source projects:

- [Eclipse Paho MQTT](https://github.com/eclipse-paho/paho.mqtt.python) – MQTT client library for Python
- [ALSA](https://www.alsa-project.org/) – `amidi` for USB-MIDI communication
- [Mosquitto](https://mosquitto.org/) – lightweight MQTT broker
- [raspotify](https://github.com/dtcooper/raspotify) – Spotify Connect client for Raspberry Pi
- [Home Assistant](https://www.home-assistant.io/) – open-source home automation platform

Thanks to all contributors and maintainers of these projects.

---

## License

[MIT License](LICENSE) – Use at your own risk. Volume limits are intentionally conservative.

All product and company names are trademarks or registered trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
