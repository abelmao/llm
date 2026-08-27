#!/bin/sh
# Balise du gardien de décharge — Linux et macOS.
# S'exécute en simple utilisateur : aucun droit administrateur, aucune installation.
# Envoie régulièrement le niveau de batterie et l'état secteur au Raspberry Pi.
#
# Usage : ./balise.sh http://IP_DU_PI:8642 [intervalle_secondes]

GARDIEN="${1:-http://192.168.1.40:8642}"
INTERVALLE="${2:-60}"

while true; do
    BATTERIE=""
    SECTEUR=1
    if [ -d /sys/class/power_supply ]; then
        # Linux
        BATTERIE=$(cat /sys/class/power_supply/BAT*/capacity 2>/dev/null | head -n 1)
        ETAT=$(cat /sys/class/power_supply/BAT*/status 2>/dev/null | head -n 1)
        [ "$ETAT" = "Discharging" ] && SECTEUR=0
    elif command -v pmset >/dev/null 2>&1; then
        # macOS
        INFOS=$(pmset -g batt)
        BATTERIE=$(printf '%s' "$INFOS" | grep -o '[0-9]*%' | head -n 1 | tr -d '%')
        printf '%s' "$INFOS" | grep -q "AC Power" || SECTEUR=0
    fi
    if [ -n "$BATTERIE" ]; then
        curl -fsS -m 5 "$GARDIEN/balise?batterie=$BATTERIE&secteur=$SECTEUR" >/dev/null 2>&1
    fi
    sleep "$INTERVALLE"
done
