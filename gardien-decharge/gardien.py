#!/usr/bin/env python3
"""Gardien externe de décharge.

Tourne sur un Raspberry Pi et surveille la puissance tirée par le chargeur
de l'ordinateur à travers une prise connectée Shelly (Plug S ou équivalent).
Quand la puissance tombe sous le seuil (chargeur débranché, coupure de
courant, ordinateur passé sur batterie), un e-mail d'alerte est envoyé.
Aucune installation sur l'ordinateur surveillé : tout se passe côté Pi.

Dépendances : bibliothèque standard Python uniquement.

Usage :
    python3 gardien.py [chemin/config.ini]      # surveillance en continu
    python3 gardien.py --mesure                 # affiche une mesure et sort
    python3 gardien.py --test-mail              # envoie un e-mail de test
"""

import argparse
import configparser
import json
import smtplib
import socket
import sys
import time
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

ETAT_SECTEUR = "secteur"
ETAT_DECHARGE = "decharge"
ETAT_INJOIGNABLE = "injoignable"

SUJETS = {
    ETAT_DECHARGE: "⚠️ Ordinateur sur batterie (décharge en cours)",
    ETAT_SECTEUR: "✅ Alimentation secteur rétablie",
    ETAT_INJOIGNABLE: "❓ Prise connectée injoignable (coupure possible)",
}

MESSAGES = {
    ETAT_DECHARGE: (
        "La prise connectée ne mesure plus de consommation ({puissance}).\n"
        "Le chargeur est débranché ou la prise n'est plus alimentée :\n"
        "l'ordinateur est très probablement en train de se décharger."
    ),
    ETAT_SECTEUR: (
        "La consommation est de retour ({puissance}).\n"
        "L'ordinateur est de nouveau alimenté par le secteur."
    ),
    ETAT_INJOIGNABLE: (
        "Impossible de joindre la prise connectée depuis le Raspberry Pi.\n"
        "Causes possibles : coupure de courant sur ce circuit, prise\n"
        "débranchée, ou problème Wi-Fi."
    ),
}


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def charger_config(chemin):
    cfg = configparser.ConfigParser()
    if not cfg.read(chemin):
        sys.exit(f"Config introuvable : {chemin} (copier config.example.ini)")
    try:
        prise = cfg["prise"]
        email = cfg["email"]
        return {
            "adresse": prise["adresse"].rstrip("/"),
            "seuil_watts": prise.getfloat("seuil_watts", 2.0),
            "intervalle_secondes": prise.getint("intervalle_secondes", 30),
            "confirmations": max(1, prise.getint("confirmations", 3)),
            "smtp_hote": email["smtp_hote"],
            "smtp_port": email.getint("smtp_port", 587),
            "utilisateur": email["utilisateur"],
            "mot_de_passe": email["mot_de_passe"],
            "destinataire": email["destinataire"],
        }
    except KeyError as e:
        sys.exit(f"Clé manquante dans {chemin} : {e}")


def lire_puissance(adresse, timeout=5):
    """Puissance instantanée en watts. Essaie l'API Shelly Gen2 (RPC) puis Gen1."""
    try:
        with urllib.request.urlopen(
            f"{adresse}/rpc/Switch.GetStatus?id=0", timeout=timeout
        ) as reponse:
            return float(json.load(reponse)["apower"])
    except (urllib.error.HTTPError, KeyError, ValueError):
        with urllib.request.urlopen(f"{adresse}/status", timeout=timeout) as reponse:
            return float(json.load(reponse)["meters"][0]["power"])


def envoyer_mail(cfg, sujet, corps):
    message = EmailMessage()
    message["From"] = cfg["utilisateur"]
    message["To"] = cfg["destinataire"]
    message["Subject"] = sujet
    message["Date"] = formatdate(localtime=True)
    message.set_content(
        f"{corps}\n\n— Gardien de décharge ({socket.gethostname()})"
    )
    if cfg["smtp_port"] == 465:
        with smtplib.SMTP_SSL(cfg["smtp_hote"], cfg["smtp_port"], timeout=30) as smtp:
            smtp.login(cfg["utilisateur"], cfg["mot_de_passe"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(cfg["smtp_hote"], cfg["smtp_port"], timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg["utilisateur"], cfg["mot_de_passe"])
            smtp.send_message(message)


def alerter(cfg, etat, puissance):
    puissance_txt = "aucune mesure" if puissance is None else f"{puissance:.1f} W"
    corps = MESSAGES[etat].format(puissance=puissance_txt)
    try:
        envoyer_mail(cfg, SUJETS[etat], corps)
        log(f"Alerte envoyée à {cfg['destinataire']} : {SUJETS[etat]}")
    except Exception as e:
        # L'envoi retentera au prochain changement d'état ; on ne plante pas.
        log(f"ERREUR envoi mail : {e}")


def surveiller(cfg):
    log(
        f"Surveillance de {cfg['adresse']} — seuil {cfg['seuil_watts']} W, "
        f"mesure toutes les {cfg['intervalle_secondes']} s, "
        f"{cfg['confirmations']} confirmations avant alerte"
    )
    etat = None
    candidat = None
    serie = 0
    while True:
        try:
            puissance = lire_puissance(cfg["adresse"])
            mesure = (
                ETAT_SECTEUR
                if puissance >= cfg["seuil_watts"]
                else ETAT_DECHARGE
            )
        except Exception as e:
            puissance = None
            mesure = ETAT_INJOIGNABLE
            log(f"Prise injoignable : {e}")

        if mesure == candidat:
            serie += 1
        else:
            candidat = mesure
            serie = 1

        if serie >= cfg["confirmations"] and mesure != etat:
            precedent = etat
            etat = mesure
            puissance_txt = "-" if puissance is None else f"{puissance:.1f} W"
            log(f"État : {precedent or 'démarrage'} -> {etat} ({puissance_txt})")
            if precedent is not None:
                alerter(cfg, etat, puissance)

        time.sleep(cfg["intervalle_secondes"])


def main():
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "config",
        nargs="?",
        default=str(Path(__file__).parent / "config.ini"),
        help="chemin du fichier de configuration (défaut : config.ini)",
    )
    parseur.add_argument(
        "--mesure",
        action="store_true",
        help="affiche une mesure de puissance et sort",
    )
    parseur.add_argument(
        "--test-mail",
        action="store_true",
        help="envoie un e-mail de test et sort",
    )
    arguments = parseur.parse_args()
    cfg = charger_config(arguments.config)

    if arguments.mesure:
        puissance = lire_puissance(cfg["adresse"])
        print(f"{puissance:.1f} W (seuil configuré : {cfg['seuil_watts']} W)")
        return
    if arguments.test_mail:
        envoyer_mail(
            cfg,
            "Test du gardien de décharge",
            "La configuration e-mail fonctionne.",
        )
        print(f"E-mail de test envoyé à {cfg['destinataire']}.")
        return
    surveiller(cfg)


if __name__ == "__main__":
    main()
