#!/usr/bin/env python3
"""Gardien externe : surveille le PC et alerte par e-mail.

Tourne sur un Raspberry Pi. Trois modes d'écoute, choisis dans config.ini
([surveillance] mode = ...) :

- ping   : le Pi écoute le PC sur le réseau. Détecte PC éteint, en veille
           ou injoignable. Rien à installer nulle part.
- balise : le PC envoie lui-même son niveau de batterie au Pi via un petit
           script utilisateur (client/balise.ps1 ou client/balise.sh,
           aucun droit administrateur requis). Détecte le passage sur
           batterie ET le niveau de batterie faible.
- prise  : mesure la puissance tirée par le chargeur via une prise
           connectée Shelly (API HTTP locale).

Dépendances : bibliothèque standard Python uniquement.

Usage :
    python3 gardien.py [chemin/config.ini]      # surveillance en continu
    python3 gardien.py --mesure                 # une mesure de la sonde et sort
    python3 gardien.py --test-mail              # envoie un e-mail de test
"""

import argparse
import configparser
import json
import smtplib
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ETAT_SECTEUR = "secteur"
ETAT_DECHARGE = "decharge"
ETAT_BATTERIE_FAIBLE = "batterie_faible"
ETAT_EN_LIGNE = "en_ligne"
ETAT_HORS_LIGNE = "hors_ligne"
ETAT_SILENCIEUX = "silencieux"
ETAT_INJOIGNABLE = "injoignable"

SUJETS = {
    ETAT_DECHARGE: "⚠️ PC sur batterie (décharge en cours)",
    ETAT_BATTERIE_FAIBLE: "🔋 Batterie du PC faible",
    ETAT_SECTEUR: "✅ PC de nouveau sur secteur",
    ETAT_HORS_LIGNE: "⚠️ Le PC ne répond plus",
    ETAT_EN_LIGNE: "✅ Le PC répond de nouveau",
    ETAT_SILENCIEUX: "❓ Plus de nouvelles du PC",
    ETAT_INJOIGNABLE: "❓ Prise connectée injoignable (coupure possible)",
}

MESSAGES = {
    ETAT_DECHARGE: (
        "Le PC n'est plus alimenté par le secteur ({detail}) :\n"
        "il est en train de se décharger."
    ),
    ETAT_BATTERIE_FAIBLE: (
        "Le PC est sur batterie et sous le seuil critique ({detail}).\n"
        "Brancher le chargeur rapidement."
    ),
    ETAT_SECTEUR: "L'alimentation secteur est de retour ({detail}).",
    ETAT_HORS_LIGNE: (
        "Le PC ne répond plus au ping ({detail}).\n"
        "Il est éteint, en veille, ou a perdu le réseau. S'il était sur\n"
        "batterie, celle-ci est peut-être vide."
    ),
    ETAT_EN_LIGNE: "Le PC répond de nouveau au ping ({detail}).",
    ETAT_SILENCIEUX: (
        "Aucune balise reçue du PC depuis {detail}.\n"
        "PC éteint, en veille, batterie vide, ou script balise arrêté."
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
        surveillance = cfg["surveillance"] if cfg.has_section("surveillance") else {}
        mode = surveillance.get("mode", "prise")
        if mode not in ("ping", "balise", "prise"):
            sys.exit(f"Mode inconnu : {mode} (attendu : ping, balise ou prise)")
        email = cfg["email"]
        resultat = {
            "mode": mode,
            "intervalle_secondes": cfg.getint(
                "surveillance", "intervalle_secondes", fallback=30
            ),
            "confirmations": max(
                1, cfg.getint("surveillance", "confirmations", fallback=3)
            ),
            "smtp_hote": email["smtp_hote"],
            "smtp_port": email.getint("smtp_port", 587),
            "utilisateur": email["utilisateur"],
            "mot_de_passe": email["mot_de_passe"],
            "destinataire": email["destinataire"],
        }
        if mode == "ping":
            resultat["pc_adresse"] = cfg["pc"]["adresse"]
        elif mode == "balise":
            resultat["port"] = cfg.getint("balise", "port", fallback=8642)
            resultat["seuil_batterie"] = cfg.getint(
                "balise", "seuil_batterie", fallback=20
            )
            resultat["silence_secondes"] = cfg.getint(
                "balise", "silence_secondes", fallback=300
            )
        else:
            resultat["prise_adresse"] = cfg["prise"]["adresse"].rstrip("/")
            resultat["seuil_watts"] = cfg.getfloat("prise", "seuil_watts", fallback=2.0)
        return resultat
    except KeyError as e:
        sys.exit(f"Section ou clé manquante dans {chemin} : {e}")


# --- Sonde « ping » : le Pi écoute le PC sur le réseau ---------------------


def pinger(hote, timeout=3):
    return (
        subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), hote],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


# --- Sonde « balise » : le PC parle, le Pi écoute --------------------------


def demarrer_serveur_balise(port):
    """Reçoit GET /balise?batterie=87&secteur=1 et mémorise la dernière balise."""
    partage = {"horodatage": None, "batterie": None, "secteur": None}
    verrou = threading.Lock()

    class Requete(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/balise":
                self.send_error(404)
                return
            champs = parse_qs(url.query)
            try:
                batterie = int(champs["batterie"][0])
                secteur = champs["secteur"][0] not in ("0", "false", "False")
            except (KeyError, ValueError, IndexError):
                self.send_error(400, "parametres attendus : batterie, secteur")
                return
            with verrou:
                partage["horodatage"] = time.monotonic()
                partage["batterie"] = batterie
                partage["secteur"] = secteur
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    serveur = ThreadingHTTPServer(("", port), Requete)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return partage, verrou


# --- Sonde « prise » : puissance du chargeur via Shelly --------------------


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


def creer_sonde(cfg):
    """Renvoie une fonction sans argument -> (etat, detail).

    etat peut valoir None tant qu'aucun état n'est encore déterminable
    (mode balise : aucune balise reçue depuis le démarrage, délai non écoulé).
    """
    if cfg["mode"] == "ping":

        def sonde():
            etat = ETAT_EN_LIGNE if pinger(cfg["pc_adresse"]) else ETAT_HORS_LIGNE
            return etat, cfg["pc_adresse"]

        return sonde

    if cfg["mode"] == "balise":
        partage, verrou = demarrer_serveur_balise(cfg["port"])
        demarrage = time.monotonic()
        log(f"Serveur balise à l'écoute sur le port {cfg['port']}")

        def sonde():
            with verrou:
                horodatage = partage["horodatage"]
                batterie = partage["batterie"]
                secteur = partage["secteur"]
            maintenant = time.monotonic()
            if horodatage is None:
                if maintenant - demarrage < cfg["silence_secondes"]:
                    return None, ""  # on attend la première balise
                return ETAT_SILENCIEUX, "le démarrage du gardien"
            age = maintenant - horodatage
            if age > cfg["silence_secondes"]:
                return ETAT_SILENCIEUX, f"{int(age // 60)} min"
            detail = f"batterie à {batterie} %"
            if secteur:
                return ETAT_SECTEUR, detail
            if batterie <= cfg["seuil_batterie"]:
                return ETAT_BATTERIE_FAIBLE, detail
            return ETAT_DECHARGE, detail

        return sonde

    def sonde():
        try:
            puissance = lire_puissance(cfg["prise_adresse"])
        except Exception as e:
            log(f"Prise injoignable : {e}")
            return ETAT_INJOIGNABLE, "aucune mesure"
        detail = f"puissance mesurée : {puissance:.1f} W"
        if puissance >= cfg["seuil_watts"]:
            return ETAT_SECTEUR, detail
        return ETAT_DECHARGE, detail

    return sonde


# --- Alerte e-mail ---------------------------------------------------------


def envoyer_mail(cfg, sujet, corps):
    message = EmailMessage()
    message["From"] = cfg["utilisateur"]
    message["To"] = cfg["destinataire"]
    message["Subject"] = sujet
    message["Date"] = formatdate(localtime=True)
    message.set_content(f"{corps}\n\n— Gardien de décharge ({socket.gethostname()})")
    if cfg["smtp_port"] == 465:
        with smtplib.SMTP_SSL(cfg["smtp_hote"], cfg["smtp_port"], timeout=30) as smtp:
            smtp.login(cfg["utilisateur"], cfg["mot_de_passe"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(cfg["smtp_hote"], cfg["smtp_port"], timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg["utilisateur"], cfg["mot_de_passe"])
            smtp.send_message(message)


def alerter(cfg, etat, detail):
    corps = MESSAGES[etat].format(detail=detail or "sans précision")
    try:
        envoyer_mail(cfg, SUJETS[etat], corps)
        log(f"Alerte envoyée à {cfg['destinataire']} : {SUJETS[etat]}")
    except Exception as e:
        # L'envoi retentera au prochain changement d'état ; on ne plante pas.
        log(f"ERREUR envoi mail : {e}")


# --- Boucle de surveillance ------------------------------------------------


def surveiller(cfg, sonde):
    log(
        f"Surveillance en mode « {cfg['mode']} » — mesure toutes les "
        f"{cfg['intervalle_secondes']} s, {cfg['confirmations']} "
        f"confirmations avant alerte"
    )
    etat = None
    candidat = None
    serie = 0
    while True:
        mesure, detail = sonde()
        if mesure is not None:
            if mesure == candidat:
                serie += 1
            else:
                candidat = mesure
                serie = 1
            if serie >= cfg["confirmations"] and mesure != etat:
                precedent = etat
                etat = mesure
                log(f"État : {precedent or 'démarrage'} -> {etat} ({detail or '-'})")
                if precedent is not None:
                    alerter(cfg, etat, detail)
        time.sleep(cfg["intervalle_secondes"])


def afficher_une_mesure(cfg):
    if cfg["mode"] == "balise":
        sonde = creer_sonde(cfg)
        print(
            f"En attente d'une balise sur le port {cfg['port']} (90 s max)…\n"
            f"Lancer client/balise.ps1 ou client/balise.sh sur le PC."
        )
        for _ in range(90):
            etat, detail = sonde()
            if etat is not None and etat != ETAT_SILENCIEUX:
                print(f"Balise reçue : {etat} ({detail})")
                return
            time.sleep(1)
        print("Aucune balise reçue. Vérifier l'adresse du Pi côté PC et le port.")
        return
    etat, detail = creer_sonde(cfg)()
    print(f"{etat} ({detail})")


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
        help="affiche une mesure de la sonde et sort",
    )
    parseur.add_argument(
        "--test-mail",
        action="store_true",
        help="envoie un e-mail de test et sort",
    )
    arguments = parseur.parse_args()
    cfg = charger_config(arguments.config)

    if arguments.mesure:
        afficher_une_mesure(cfg)
        return
    if arguments.test_mail:
        envoyer_mail(
            cfg,
            "Test du gardien de décharge",
            "La configuration e-mail fonctionne.",
        )
        print(f"E-mail de test envoyé à {cfg['destinataire']}.")
        return
    surveiller(cfg, creer_sonde(cfg))


if __name__ == "__main__":
    main()
