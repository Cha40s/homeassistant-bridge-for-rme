# RME ADI-2 DAC – Spotify Connect & Home Assistant Volume Bridge

Raspberry Pi, librespot/raspotify und der RME ADI-2 DAC werden zu einem schlanken Audio-Setup verbunden: Spotify streamt bit-perfect, die echte Lautstärke sitzt im DAC (USB-MIDI), Home Assistant steuert und zeigt den Status über MQTT. Digitale Lautstärke bleibt immer bei 100 %.

---

## Highlights

- Bit-perfect Spotify Connect (librespot/raspotify), kein PulseAudio/PipeWire
- Lautstärkeregelung ausschließlich im RME ADI-2 DAC per USB-MIDI (SysEx)
- Home Assistant UI über MQTT (Slider, Presets, Automationen)
- Sicherheits-Limits mit Clamping im Script (z. B. −60 dB bis −10 dB)
- Erkennung von DAC Online/Offline inkl. verzögerter Initialisierung
- Optional: external raspotify manager via MQTT (start/stop by DAC status)
- Default-Lautstärke nach dem Einschalten inkl. Retries bis USB/MIDI stabil ist

---

## Signalfluss

```
Spotify App → raspotify/librespot → USB Audio → RME ADI-2 DAC
                                   ↘
                            MQTT ↔ MIDI Bridge → USB-MIDI → DAC Lautstärke
                                     ↑
                               MQTT Broker ↔ Home Assistant
```

---

## Repository-Inhalt

| Datei | Zweck |
| ----- | ----- |
| `rme_mqtt_bridge.py` | Zentrale Bridge: MQTT ↔ USB-MIDI, DAC-Erkennung, Lautstärke-Logik |
| `rme-mqtt-bridge.service` | Beispiel systemd-Service für die Bridge (mit Umgebungvariablen) |
| `raspotify_manager.py` | Optionaler Listener: steuert raspotify via MQTT-DAC-Status |
| `raspotify-manager.service` | Beispiel systemd-Service für den raspotify-Manager |
| `conf` | Beispiel für `/etc/raspotify/conf` (librespot) für ein bit-perfect Spotify Connect |

---

## Voraussetzungen

- Hardware: Raspberry Pi mit USB, RME ADI-2 DAC, funktionierender MQTT Broker
- Software: DietPi/Debian, `raspotify` (librespot), Python 3, `amidi` (ALSA MIDI)

---

## Setup (Raspberry Pi)

1) Abhängigkeiten installieren  
   ```bash
   sudo apt update
   sudo apt install python3 python3-paho-mqtt amidi raspotify
   ```

2) Dateien platzieren  
   ```bash
   sudo cp rme_mqtt_bridge.py /usr/local/bin/
   sudo cp rme-mqtt-bridge.service /etc/systemd/system/
   sudo chmod +x /usr/local/bin/rme_mqtt_bridge.py
   ```
   - Service-File anpassen: MQTT-Host/User/Pass, `MIDI_PORT`, Lautstärke-Limits usw.
   - Optional: `conf` nach `/etc/raspotify/conf` kopieren, um librespot bit-perfect zu konfigurieren.

3) Dienst aktivieren  
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now rme-mqtt-bridge.service
   ```

---

## Raspotify control (choose one)

Option A (recommended): external raspotify manager

Copy files and enable:
```bash
sudo cp raspotify_manager.py /usr/local/bin/
sudo cp raspotify-manager.service /etc/systemd/system/
sudo chmod +x /usr/local/bin/raspotify_manager.py
sudo systemctl daemon-reload
sudo systemctl enable --now raspotify-manager.service
```
Keep `MANAGE_RASPOTIFY=0` in `rme-mqtt-bridge.service`.

Option B: bridge controls raspotify

Set `MANAGE_RASPOTIFY=1` in `rme-mqtt-bridge.service` and do not run `raspotify-manager.service` at the same time.

---

## Verhalten / Logik

- DAC-Erkennung über `amidi -l` (Name enthält „ADI-2 DAC“). „Ready“ erst nach mehreren Online-Polls (`READY_STREAK`).
- Wenn `MANAGE_RASPOTIFY=1`, startet/stoppt die Bridge raspotify. Alternativ kann das der raspotify-manager per MQTT machen.
- Beim Hochfahren des DAC: Default-Lautstärke wird mit Retries gesetzt, danach ggf. ein ausstehender (pending) Wert.
- Eingehende MQTT-Werte werden entprellt (`DEBOUNCE_SECONDS`) und strikt auf `MIN_DB`/`MAX_DB` begrenzt.

---

## MQTT Topics

| Topic | Richtung | Payload | Beschreibung |
| ----- | -------- | ------- | ------------ |
| `rme/lineout/db/set` | Subscribe | Float dB (z. B. `-43.5`) | Gewünschte Lautstärke |
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
| `MQTT_HOST` / `MQTT_PORT` / `MQTT_USER` / `MQTT_PASS` | `192.168.100.60` / `1883` / leer | MQTT-Broker |
| `MIDI_PORT` | `hw:1,0,0` | ALSA MIDI-Port des DAC |
| `DEFAULT_DB` | `-50.0` | Lautstärke, die beim „ready“ sofort gesetzt wird |
| `MIN_DB` / `MAX_DB` | `-60.0` / `-10.0` | Harte Limits für alle Eingaben |
| `DAC_POLL_SECONDS` | `1.0` | Intervall für `amidi -l` |
| `READY_STREAK` | `3` (Beispiel-Service: `5`) | Anzahl aufeinanderfolgender Online-Polls bis „ready“ |
| `APPLY_RETRIES` | `6` (Beispiel-Service: `10`) | Anzahl Wiederholungen beim Setzen von Default/Pending |
| `APPLY_RETRY_DELAY` | `0.6` s (Beispiel-Service: `0.8`) | Pause zwischen Wiederholungen |
| `DEBOUNCE_SECONDS` | `0.03` | Mindestabstand zwischen Lautstärke-Updates |
| `MANAGE_RASPOTIFY` | `0` | `1` = Bridge startet/stoppt raspotify (nicht parallel zum raspotify-manager) |

---

## Warum das Projekt?

Viele Spotify-Receiver und Home-Assistant-Setups existieren, aber kaum Lösungen, die:

- bit-perfect spielen,
- die echte DAC-Lautstärke nutzen,
- und sauber mit dem Hardware-Status umgehen.

Genau diese Lücke schließt die Bridge.

---

## Lizenz

MIT License. Nutzung auf eigene Gefahr; Lautstärke-Limits sind bewusst konservativ gewählt.
