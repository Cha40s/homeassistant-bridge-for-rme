# RME ADI-2 DAC – MQTT Volume Bridge

Raspberry Pi steuert den RME ADI-2 DAC per USB-MIDI: Lautstärke, DAC-Erkennung und Status werden über MQTT an Home Assistant angebunden. Die Audioquelle ist beliebig – z. B. ein WiiM Mini per SPDIF, ein CD-Player oder optional der eingebaute Spotify Connect (raspotify/librespot).

---

## Highlights

- Lautstärkeregelung ausschließlich im RME ADI-2 DAC per USB-MIDI (SysEx)
- Home Assistant UI über MQTT (Slider, Presets, Automationen)
- Sicherheits-Limits mit Clamping im Script (z. B. −60 dB bis −10 dB)
- Erkennung von DAC Online/Offline inkl. verzögerter Initialisierung
- Default-Lautstärke nach dem Einschalten inkl. Retries bis USB/MIDI stabil ist
- Graceful Shutdown bei SIGTERM (sauberes MQTT-Disconnect)
- Optional: raspotify (Spotify Connect) mit DAC-gesteuertem Start/Stop

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

## Repository-Inhalt

| Datei | Zweck |
| ----- | ----- |
| `rme_mqtt_bridge.py` | Zentrale Bridge: MQTT ↔ USB-MIDI, DAC-Erkennung, Lautstärke-Logik |
| `rme-mqtt-bridge.service` | systemd-Service für die Bridge |
| `raspotify_manager.py` | Optional: steuert raspotify Start/Stop anhand des DAC-Status |
| `raspotify-manager.service` | systemd-Service für den raspotify-Manager |
| `conf` | Beispiel für `/etc/raspotify/conf` (librespot, bit-perfect) |
| `env.example` | Vorlage für `/etc/default/rme-mqtt-bridge` (MQTT-Credentials) |

---

## Voraussetzungen

- Hardware: Raspberry Pi mit USB, RME ADI-2 DAC, funktionierender MQTT Broker
- Software: Debian/DietPi, Python 3, `python3-paho-mqtt`, `amidi` (ALSA MIDI)
- Optional: `raspotify` (nur wenn Spotify Connect vom Pi gewünscht)

---

## Setup (Raspberry Pi)

1) Abhängigkeiten installieren
   ```bash
   sudo apt update
   sudo apt install python3 python3-paho-mqtt amidi
   ```

2) MQTT-Credentials anlegen
   ```bash
   sudo cp env.example /etc/default/rme-mqtt-bridge
   sudo chmod 600 /etc/default/rme-mqtt-bridge
   # Datei editieren: MQTT_USER und MQTT_PASS anpassen
   sudo nano /etc/default/rme-mqtt-bridge
   ```

3) Bridge installieren
   ```bash
   sudo cp rme_mqtt_bridge.py /usr/local/bin/
   sudo cp rme-mqtt-bridge.service /etc/systemd/system/
   sudo chmod +x /usr/local/bin/rme_mqtt_bridge.py
   ```
   - Service-File anpassen: MQTT-Host, `MIDI_PORT`, Lautstärke-Limits usw.

4) Dienst aktivieren
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now rme-mqtt-bridge.service
   ```

---

## Optional: Raspotify (Spotify Connect)

Wenn der Pi auch als Spotify-Quelle dienen soll (statt z. B. WiiM Mini):

```bash
sudo apt install raspotify
sudo cp conf /etc/raspotify/conf
sudo cp raspotify_manager.py /usr/local/bin/
sudo cp raspotify-manager.service /etc/systemd/system/
sudo chmod +x /usr/local/bin/raspotify_manager.py
sudo systemctl daemon-reload
sudo systemctl enable --now raspotify.service raspotify-manager.service
```

Der raspotify-Manager startet/stoppt raspotify automatisch wenn der DAC online/offline geht.

---

## Verhalten / Logik

- DAC-Erkennung über `amidi -l` (Name enthält „ADI-2 DAC"). „Ready" erst nach mehreren Online-Polls (`READY_STREAK`).
- Beim Hochfahren des DAC: Default-Lautstärke wird mit Retries gesetzt, danach ggf. ein ausstehender (pending) Wert.
- Eingehende MQTT-Werte werden entprellt (`DEBOUNCE_SECONDS`) und strikt auf `MIN_DB`/`MAX_DB` begrenzt.
- Bei SIGTERM (systemctl stop): Bridge disconnectet sauber von MQTT und setzt Status auf "offline".

---

## MQTT Topics

| Topic | Richtung | Payload | Beschreibung |
| ----- | -------- | ------- | ------------ |
| `rme/lineout/db/set` | Subscribe | Float dB (z. B. `-43.5`) | Gewünschte Lautstärke |
| `rme/lineout/db/state` | Publish (retained) | Float dB | Tatsächlich gesetzte Lautstärke |
| `rme/dac/status` | Publish (retained) | `online` / `offline` | DAC-Erkennung via `amidi -l` |
| `rme/bridge/status` | Publish (retained, LWT) | `online` / `offline` | Status des Python-Clients |

---

## Home Assistant Beispiel (Slider)

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

## Feintuning über Umgebungsvariablen

| Variable | Default | Bedeutung |
| -------- | ------- | --------- |
| `MQTT_HOST` / `MQTT_PORT` | `192.168.100.60` / `1883` | MQTT-Broker |
| `MQTT_USER` / `MQTT_PASS` | leer | MQTT-Auth (via EnvironmentFile) |
| `MIDI_PORT` | `hw:1,0,0` | ALSA MIDI-Port des DAC |
| `DEFAULT_DB` | `-50.0` | Lautstärke, die beim „ready" sofort gesetzt wird |
| `MIN_DB` / `MAX_DB` | `-60.0` / `-10.0` | Harte Limits für alle Eingaben |
| `DAC_POLL_SECONDS` | `1.0` | Intervall für `amidi -l` |
| `READY_STREAK` | `3` (Service: `5`) | Aufeinanderfolgende Online-Polls bis „ready" |
| `APPLY_RETRIES` | `6` (Service: `10`) | Wiederholungen beim Setzen von Default/Pending |
| `APPLY_RETRY_DELAY` | `0.6` s (Service: `0.8`) | Pause zwischen Wiederholungen |
| `DEBOUNCE_SECONDS` | `0.03` | Mindestabstand zwischen Lautstärke-Updates |

---

## Lizenz

MIT License. Nutzung auf eigene Gefahr; Lautstärke-Limits sind bewusst konservativ gewählt.
