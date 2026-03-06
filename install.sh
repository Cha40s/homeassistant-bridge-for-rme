#!/bin/bash
set -euo pipefail

# RME ADI-2 DAC MQTT Bridge - Installer
# Tested on: Raspberry Pi OS (Bookworm+), DietPi, Debian 12/13

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="/etc/default/rme-mqtt-bridge"
SERVICE_FILE="/etc/systemd/system/rme-mqtt-bridge.service"
BRIDGE_SCRIPT="/usr/local/bin/rme_mqtt_bridge.py"

info()  { echo -e "\033[1;32m[+]\033[0m $1"; }
warn()  { echo -e "\033[1;33m[!]\033[0m $1"; }
error() { echo -e "\033[1;31m[x]\033[0m $1"; exit 1; }
ask()   { read -rp "$1 " "$2"; }

# --- Root check ---
if [[ $EUID -ne 0 ]]; then
    error "Bitte als root ausfuehren: sudo $0"
fi

echo ""
echo "============================================"
echo "  RME ADI-2 DAC MQTT Bridge - Installation"
echo "============================================"
echo ""

# --- Dependencies ---
info "Installiere Abhaengigkeiten..."
apt-get update -qq
apt-get install -y -qq python3 python3-paho-mqtt alsa-utils > /dev/null
info "Abhaengigkeiten installiert."

# --- Bridge Script ---
info "Kopiere Bridge-Script..."
cp "$SCRIPT_DIR/rme_mqtt_bridge.py" "$BRIDGE_SCRIPT"
chmod +x "$BRIDGE_SCRIPT"

# --- Service File ---
info "Kopiere Service-Datei..."
cp "$SCRIPT_DIR/rme-mqtt-bridge.service" "$SERVICE_FILE"

# --- EnvironmentFile (Credentials) ---
if [[ -f "$ENV_FILE" ]]; then
    warn "EnvironmentFile $ENV_FILE existiert bereits, wird nicht ueberschrieben."
else
    info "MQTT-Zugangsdaten konfigurieren:"
    ask "  MQTT User [mqtt]:" MQTT_USER
    MQTT_USER="${MQTT_USER:-mqtt}"
    ask "  MQTT Passwort:" MQTT_PASS

    if [[ -z "$MQTT_PASS" ]]; then
        warn "Kein Passwort angegeben, verwende Vorlage aus env.example"
        cp "$SCRIPT_DIR/env.example" "$ENV_FILE"
    else
        cat > "$ENV_FILE" <<EOF
MQTT_USER=$MQTT_USER
MQTT_PASS=$MQTT_PASS
EOF
    fi
    chmod 600 "$ENV_FILE"
    info "EnvironmentFile angelegt: $ENV_FILE (chmod 600)"
fi

# --- Enable & Start ---
systemctl daemon-reload
systemctl enable rme-mqtt-bridge.service
systemctl restart rme-mqtt-bridge.service
info "Bridge-Service aktiviert und gestartet."

# --- Optional: Raspotify ---
echo ""
ask "Raspotify (Spotify Connect) installieren? [j/N]:" INSTALL_RASPOTIFY
if [[ "${INSTALL_RASPOTIFY,,}" == "j" ]]; then
    info "Installiere raspotify..."
    apt-get install -y -qq raspotify > /dev/null

    info "Kopiere raspotify-Konfiguration..."
    cp "$SCRIPT_DIR/conf" /etc/raspotify/conf

    info "Kopiere raspotify-Manager..."
    cp "$SCRIPT_DIR/raspotify_manager.py" /usr/local/bin/raspotify_manager.py
    chmod +x /usr/local/bin/raspotify_manager.py
    cp "$SCRIPT_DIR/raspotify-manager.service" /etc/systemd/system/raspotify-manager.service

    systemctl daemon-reload
    systemctl enable --now raspotify.service raspotify-manager.service
    info "Raspotify + Manager aktiviert."
fi

# --- Status ---
echo ""
echo "============================================"
info "Installation abgeschlossen!"
echo "============================================"
echo ""
systemctl status rme-mqtt-bridge.service --no-pager -l
echo ""
info "Logs anzeigen: journalctl -fu rme-mqtt-bridge"
info "DAC pruefen:   amidi -l"
info "Konfiguration: $ENV_FILE"
