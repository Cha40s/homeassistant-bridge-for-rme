# RME ADI-2 DAC – MQTT Volume Bridge

Steuere deinen RME ADI-2 DAC per USB-MIDI über Home Assistant. Ein Raspberry Pi übernimmt die Lautstärkeregelung direkt im DAC (nicht digital!), erkennt Online/Offline-Status und kommuniziert alles über MQTT. Die Audioquelle ist beliebig – WiiM, Spotify Connect, CD-Player oder was auch immer am DAC hängt.

---

## Quick Start

```bash
git clone https://github.com/DEIN_USER/RME_Bridge.git
cd RME_Bridge
sudo ./install.sh
```

Das Script installiert alle Abhängigkeiten, fragt MQTT-Zugangsdaten ab und startet den Service.

---

## Highlights

- Lautstärkeregelung direkt im DAC per USB-MIDI SysEx (kein digitales Clipping)
- Home Assistant Integration über MQTT (Slider, Presets, Automationen)
- Sicherheits-Limits: harte Grenzen bei −60 dB bis −10 dB
- DAC Online/Offline Erkennung mit verzögerter Initialisierung
- Default-Lautstärke beim Einschalten mit Retries bis USB-MIDI stabil ist
- Graceful Shutdown bei SIGTERM (sauberes MQTT-Disconnect)
- Optional: Spotify Connect (raspotify) mit DAC-gesteuertem Start/Stop

---

## Hardware

| Komponente | Getestet mit |
| --- | --- |
| Raspberry Pi | Pi 4, Pi 5 (jedes Modell mit USB sollte funktionieren) |
| DAC | RME ADI-2 DAC FS |
| USB-Kabel | Standard USB-A/C zu Micro-B |
| OS | Raspberry Pi OS (Bookworm), DietPi, Debian 12/13 |
| MQTT Broker | Mosquitto (z. B. auf Home Assistant) |

> **Hinweis:** Der RME ADI-2 DAC meldet sich als USB-Audio- **und** USB-MIDI-Gerät. Die Bridge nutzt nur die MIDI-Schnittstelle für die Lautstärke. Audio läuft separat (ALSA, SPDIF, analog – egal).

---

## Signalfluss

```
Audioquelle (WiiM / raspotify / CD / ...) → RME ADI-2 DAC
                                              ↑
                            MQTT ↔ MIDI Bridge → USB-MIDI → DAC Lautstärke
                                     ↑
                               MQTT Broker ↔ Home Assistant
```

---

## Dateien

| Datei | Zweck |
| --- | --- |
| `rme_mqtt_bridge.py` | Zentrale Bridge: MQTT ↔ USB-MIDI, DAC-Erkennung, Lautstärke |
| `rme-mqtt-bridge.service` | systemd-Service für die Bridge |
| `env.example` | Vorlage für `/etc/default/rme-mqtt-bridge` (Credentials + Optionen) |
| `install.sh` | Automatisches Setup |
| `raspotify_manager.py` | Optional: raspotify Start/Stop anhand DAC-Status |
| `raspotify-manager.service` | systemd-Service für den raspotify-Manager |
| `conf` | Beispiel für `/etc/raspotify/conf` (librespot, bit-perfect) |

---

## Voraussetzungen

- Raspberry Pi mit USB-Verbindung zum RME ADI-2 DAC
- MQTT Broker (z. B. Mosquitto auf Home Assistant)
- Python 3.10+ und `paho-mqtt` (wird vom Installer installiert)
- `amidi` aus `alsa-utils` (wird vom Installer installiert)

---

## Installation

### Automatisch (empfohlen)

```bash
git clone https://github.com/DEIN_USER/RME_Bridge.git
cd RME_Bridge
sudo ./install.sh
```

### Manuell

1) Abhängigkeiten installieren
   ```bash
   sudo apt update
   sudo apt install python3 python3-paho-mqtt alsa-utils
   ```

2) MQTT-Credentials anlegen
   ```bash
   sudo cp env.example /etc/default/rme-mqtt-bridge
   sudo chmod 600 /etc/default/rme-mqtt-bridge
   sudo nano /etc/default/rme-mqtt-bridge   # MQTT_USER und MQTT_PASS anpassen
   ```

3) Bridge installieren
   ```bash
   sudo cp rme_mqtt_bridge.py /usr/local/bin/
   sudo chmod +x /usr/local/bin/rme_mqtt_bridge.py
   sudo cp rme-mqtt-bridge.service /etc/systemd/system/
   ```

4) Service-Datei anpassen (falls nötig)
   ```bash
   sudo nano /etc/systemd/system/rme-mqtt-bridge.service
   # MQTT_HOST, MIDI_PORT etc. anpassen
   ```

5) Starten
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now rme-mqtt-bridge
   ```

---

## Optional: Raspotify (Spotify Connect)

Falls der Pi auch als Spotify-Quelle dienen soll (statt z. B. WiiM Mini):

```bash
sudo apt install raspotify
sudo cp conf /etc/raspotify/conf
sudo cp raspotify_manager.py /usr/local/bin/
sudo chmod +x /usr/local/bin/raspotify_manager.py
sudo cp raspotify-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now raspotify raspotify-manager
```

Der raspotify-Manager startet/stoppt raspotify automatisch wenn der DAC online/offline geht. Audio wird bit-perfect (S32, 320 kbps) gestreamt, die Lautstärke wird im DAC geregelt (nicht digital).

---

## DietPi-Hinweise

- DietPi nutzt systemd (seit v6), die Service-Dateien funktionieren direkt
- ALSA-Utils: `sudo apt install alsa-utils` oder über `dietpi-software`
- Bei Problemen mit dem Audio-Device: `dietpi-config` → Audio-Optionen prüfen
- SSH-Zugang ist bei DietPi standardmäßig aktiv (User: `root`)

---

## MQTT Topics

| Topic | Richtung | Payload | Beschreibung |
| --- | --- | --- | --- |
| `rme/lineout/db/set` | Subscribe | Float dB (z. B. `-43.5`) | Gewünschte Lautstärke |
| `rme/lineout/db/state` | Publish (retained) | Float dB | Tatsächlich gesetzte Lautstärke |
| `rme/dac/status` | Publish (retained) | `online` / `offline` | DAC-Erkennung via `amidi -l` |
| `rme/bridge/status` | Publish (retained, LWT) | `online` / `offline` | Bridge-Status |

---

## Home Assistant Beispiel

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

## Konfiguration

Alle Einstellungen können über Umgebungsvariablen gesetzt werden – entweder in der Service-Datei oder im EnvironmentFile (`/etc/default/rme-mqtt-bridge`).

| Variable | Default | Bedeutung |
| --- | --- | --- |
| `MQTT_HOST` | `192.168.100.60` | MQTT-Broker Adresse |
| `MQTT_PORT` | `1883` | MQTT-Broker Port |
| `MQTT_USER` / `MQTT_PASS` | leer | MQTT-Auth (via EnvironmentFile) |
| `MIDI_PORT` | `hw:1,0,0` | ALSA MIDI-Port des DAC |
| `DEFAULT_DB` | `-50.0` | Lautstärke beim DAC-Start |
| `MIN_DB` / `MAX_DB` | `-60.0` / `-10.0` | Harte Limits |
| `DAC_POLL_SECONDS` | `1.0` | Abfrageintervall für DAC-Erkennung |
| `READY_STREAK` | `3` | Online-Polls bis "ready" |
| `APPLY_RETRIES` | `6` | Wiederholungen beim Setzen der Lautstärke |
| `APPLY_RETRY_DELAY` | `0.6` | Sekunden zwischen Wiederholungen |
| `DEBOUNCE_SECONDS` | `0.03` | Mindestabstand zwischen Updates |
| `DEBUG` | `0` | `1` für ausführliche Logs |

---

## Troubleshooting

### DAC wird nicht erkannt

```bash
amidi -l          # Zeigt MIDI-Geräte – "ADI-2 DAC" sollte erscheinen
aplay -l          # Zeigt Audio-Geräte
lsusb             # USB-Geräte prüfen
```

- USB-Kabel prüfen (manche Kabel sind nur zum Laden)
- Anderen USB-Port testen
- DAC aus- und wieder einschalten

### MQTT verbindet nicht

```bash
journalctl -u rme-mqtt-bridge -e
# Suche nach: "MQTT connected rc=..." oder Fehlermeldungen
```

- Broker-Adresse und Port prüfen (`MQTT_HOST`, `MQTT_PORT`)
- Credentials prüfen: `/etc/default/rme-mqtt-bridge`
- Firewall: Port 1883 muss vom Pi zum Broker offen sein
- Test: `mosquitto_sub -h BROKER_IP -u USER -P PASS -t 'rme/#'`

### Service startet nicht

```bash
systemctl status rme-mqtt-bridge
journalctl -u rme-mqtt-bridge --no-pager -n 30
```

- Python-Fehler? → `python3 /usr/local/bin/rme_mqtt_bridge.py` manuell testen
- EnvironmentFile fehlt? → Siehe [Installation](#installation)

### Debug-Modus

```bash
# In der Service-Datei DEBUG=1 setzen:
sudo systemctl edit rme-mqtt-bridge
# [Service]
# Environment=DEBUG=1

sudo systemctl restart rme-mqtt-bridge
journalctl -fu rme-mqtt-bridge
```

### MIDI-Port stimmt nicht

```bash
amidi -l
# Ausgabe z. B.:
# Dir Device    Name
# IO  hw:1,0,0  RME ADI-2 DAC MIDI 1
```

Falls der Port nicht `hw:1,0,0` ist, in der Service-Datei anpassen:
```bash
# In /etc/systemd/system/rme-mqtt-bridge.service:
Environment=MIDI_PORT=hw:2,0,0   # An tatsächlichen Port anpassen
```

---

## Lizenz

[MIT License](LICENSE) – Nutzung auf eigene Gefahr. Lautstärke-Limits sind bewusst konservativ gewählt.
