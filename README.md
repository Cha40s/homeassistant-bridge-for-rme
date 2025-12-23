# RME ADI-2 DAC – Spotify Connect & Home Assistant Volume Bridge

Dieses Projekt verbindet **Spotify Connect**, **Home Assistant**, **MQTT** und den **RME ADI-2 DAC** zu einem schlanken, bit-perfekten Audio-Setup:

- Spotify streamt **ohne digitale Lautstärkeänderung**
- Die **reale Lautstärke** wird direkt **im RME DAC** per MIDI gesteuert
- Home Assistant dient als zentrale UI (Slider, Presets, Automationen)
- Der Raspberry Pi fungiert als stabile Bridge
- Der DAC-Status (an/aus) wird zuverlässig erkannt
- Spotify Connect wird automatisch gestartet/gestoppt, je nach DAC-Status

Das Ziel:  
👉 **Digitale Lautstärke immer 100 %, echte Lautstärke ausschließlich im DAC.**

---

## Features

- ✅ Bit-perfect Spotify Connect (librespot / raspotify)
- ✅ Direkte Lautstärkeregelung im RME ADI-2 DAC per USB-MIDI (SysEx)
- ✅ Home Assistant Integration über MQTT
- ✅ Sicherheits-Limits für Lautstärke (z. B. −60 dB bis −10 dB)
- ✅ DAC Online/Offline-Erkennung
- ✅ Verzögerte Initialisierung (DAC braucht Zeit nach dem Einschalten)
- ✅ Automatisches Starten/Stoppen von Spotify Connect
- ✅ Default-Lautstärke beim Einschalten des DAC
- ✅ Schlankes, robustes System (kein PulseAudio, kein PipeWire)

---

## Architektur

iPhone / Spotify App
|
| Spotify Connect
v
Raspberry Pi (raspotify / librespot)
|
| USB Audio (bit-perfect)
v
RME ADI-2 DAC
^
|
| USB MIDI (SysEx)
|
Raspberry Pi (MQTT <-> MIDI Bridge)
|
| MQTT
v
Home Assistant


---

## Komponenten

### Raspberry Pi
- DietPi / Debian
- raspotify (librespot)
- Python 3
- `amidi` (ALSA MIDI)
- MQTT Client

### DAC
- RME ADI-2 DAC (USB Audio + USB MIDI)

### Home Assistant
- MQTT Integration
- Slider / Presets / Automationen

---

## Dateien im Repository

| Datei | Beschreibung |
|-----|-------------|
| `rme_mqtt_bridge.py` | Zentrale Bridge: MQTT ↔ MIDI, DAC-Erkennung, Volume-Logik |
| `rme-mqtt-bridge.service` | systemd Service für die Bridge |
| `raspotify.conf` | Beispiel-Konfiguration für Spotify Connect |

---

## Funktionsprinzip (wichtig)

### Warum digitale Lautstärke vermeiden?
Spotify (und viele andere Player) ändern bei Lautstärkeänderungen:
- die Wortbreite
- die Dynamik
- den Headroom

Dieses Projekt setzt daher:
- **Spotify Lautstärke = fixed**
- **echte Lautstärke = analog im DAC**

---

## Lautstärke-Workflow

1. Spotify streamt immer mit voller Auflösung
2. Home Assistant sendet dB-Wert per MQTT
3. Raspberry Pi wandelt dB → RME SysEx
4. RME ADI-2 DAC setzt **seinen internen Lautstärkeregler**

---

## DAC Online / Offline Logik

- Der DAC verschwindet vollständig aus ALSA/MIDI, wenn er ausgeschaltet ist
- Die Bridge prüft regelmäßig:
  ```bash
  amidi -l

Erst nach mehreren erfolgreichen Erkennungen gilt der DAC als „ready“

Erst dann werden:

Default-Lautstärke gesetzt

Spotify Connect gestartet

Spotify Connect Handling

Spotify Connect kann nicht zuverlässig erkennen, ob ein DAC physisch verfügbar ist.

Lösung:

Wenn DAC offline → raspotify wird gestoppt

Wenn DAC ready → raspotify wird gestartet

Ergebnis:

Kein „Fake-Verbunden“ mehr in der Spotify App

Sauberes Verhalten für Endnutzer

MQTT Topics
Steuerung
rme/lineout/db/set        (float, z. B. -43.5)

Status
rme/lineout/db/state     (float, retained)
rme/dac/status           (online / offline)
rme/bridge/status        (online / offline)

Sicherheits-Limits

Im Script fest verdrahtet (Default):

Minimum: −60.0 dB

Maximum: −10.0 dB

Selbst wenn Home Assistant oder ein Client falsche Werte sendet, wird der DAC geschützt.

Default-Lautstärke

Beim Einschalten des DAC:

Warten, bis USB & MIDI stabil sind

Default-Lautstärke setzen (z. B. −30.0 dB)

Optional: zuletzt gesetzten Wert anwenden

Das verhindert Überraschungen beim Einschalten.

Home Assistant Beispiel (Slider)
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

Voraussetzungen

RME ADI-2 DAC per USB verbunden

MQTT Broker (z. B. Home Assistant Mosquitto)

Raspberry Pi mit USB Zugriff

amidi installiert

Warum dieses Projekt existiert

Es gibt viele Spotify-Receiver.
Es gibt viele Home-Assistant-Setups.
Aber kaum saubere Lösungen, die:

bit-perfekt arbeiten

echte DAC-Lautstärke nutzen

zuverlässig mit Hardware-Status umgehen

Dieses Projekt schließt genau diese Lücke.

Haftung / Hinweis

Nutzung auf eigene Gefahr

Lautstärke-Limits sind bewusst konservativ gewählt

Änderungen an MIDI-Befehlen können unerwartete Effekte haben

Lizenz

MIT License
Frei nutzbar, veränderbar, weiterverteilbar.

Autor

Initiale Idee & Umsetzung:

Raspberry Pi

RME ADI-2 DAC

Home Assistant

Spotify Connect

Feel free to fork, improve and adapt.


