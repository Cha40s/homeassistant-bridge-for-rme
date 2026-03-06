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
    error "Please run as root: sudo $0"
fi

echo ""
echo "============================================"
echo "  RME ADI-2 DAC MQTT Bridge - Installation"
echo "============================================"
echo ""

# --- Audio source selection ---
echo "How is audio connected to your RME ADI-2 DAC?"
echo ""
echo "  1) External player (WiiM, CD, etc.) via SPDIF/optical/coax"
echo "     → Set DAC input to SPDIF or optical"
echo ""
echo "  2) This Raspberry Pi via USB (Spotify Connect / raspotify)"
echo "     → Set DAC input to USB"
echo ""
ask "Your choice [1/2]:" AUDIO_SOURCE
echo ""

# --- Dependencies ---
info "Installing dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-paho-mqtt alsa-utils > /dev/null
info "Dependencies installed."

# --- Bridge Script ---
info "Copying bridge script..."
cp "$SCRIPT_DIR/rme_mqtt_bridge.py" "$BRIDGE_SCRIPT"
chmod +x "$BRIDGE_SCRIPT"

# --- Service File ---
info "Copying service file..."
cp "$SCRIPT_DIR/rme-mqtt-bridge.service" "$SERVICE_FILE"

# --- EnvironmentFile (Credentials) ---
if [[ -f "$ENV_FILE" ]]; then
    warn "EnvironmentFile $ENV_FILE already exists, not overwriting."
else
    info "Configure MQTT credentials:"
    ask "  MQTT User [mqtt]:" MQTT_USER
    MQTT_USER="${MQTT_USER:-mqtt}"
    ask "  MQTT Password:" MQTT_PASS

    if [[ -z "$MQTT_PASS" ]]; then
        warn "No password provided, using template from env.example"
        cp "$SCRIPT_DIR/env.example" "$ENV_FILE"
    else
        cat > "$ENV_FILE" <<EOF
MQTT_USER=$MQTT_USER
MQTT_PASS=$MQTT_PASS
EOF
    fi
    chmod 600 "$ENV_FILE"
    info "EnvironmentFile created: $ENV_FILE (chmod 600)"
fi

# --- Enable & Start ---
systemctl daemon-reload
systemctl enable rme-mqtt-bridge.service
systemctl restart rme-mqtt-bridge.service
info "Bridge service enabled and started."

# --- Raspotify (if USB/internal selected) ---
if [[ "${AUDIO_SOURCE}" == "2" ]]; then
    echo ""
    info "Installing raspotify (Spotify Connect)..."
    apt-get install -y -qq raspotify > /dev/null

    info "Copying raspotify configuration..."
    cp "$SCRIPT_DIR/conf" /etc/raspotify/conf

    info "Copying raspotify manager..."
    cp "$SCRIPT_DIR/raspotify_manager.py" /usr/local/bin/raspotify_manager.py
    chmod +x /usr/local/bin/raspotify_manager.py
    cp "$SCRIPT_DIR/raspotify-manager.service" /etc/systemd/system/raspotify-manager.service

    systemctl daemon-reload
    systemctl enable --now raspotify.service raspotify-manager.service
    info "Raspotify + manager enabled."
    echo ""
    warn "Make sure your DAC input is set to USB!"
else
    echo ""
    warn "Make sure your DAC input matches your audio source (SPDIF/optical/coax)."
fi

# --- Status ---
echo ""
echo "============================================"
info "Installation complete!"
echo "============================================"
echo ""
echo "Note: This bridge controls the DAC Line Out volume only."
echo "      It does not control headphone output or input selection."
echo ""
systemctl status rme-mqtt-bridge.service --no-pager -l
echo ""
info "View logs:      journalctl -fu rme-mqtt-bridge"
info "Check DAC:      amidi -l"
info "Configuration:  $ENV_FILE"
