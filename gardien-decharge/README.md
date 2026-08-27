# Gardien de décharge

Un « gardien » externe qui prévient par e-mail quand l'ordinateur passe sur
batterie (chargeur débranché ou coupure de courant), **sans rien installer
sur l'ordinateur** — utile quand on n'est pas administrateur du poste.

## Principe

```
Mur ──> Prise connectée Shelly ──> Chargeur ──> Ordinateur
              ▲
              │ mesure de puissance (Wi-Fi, API locale)
        Raspberry Pi ──> e-mail d'alerte
```

Tant que l'ordinateur est alimenté par le secteur, le chargeur tire une
puissance mesurable (10–60 W en usage, quelques watts batterie pleine).
Si la prise mesure ~0 W, c'est que le chargeur est débranché ou que le
courant est coupé : l'ordinateur se décharge. Le Pi interroge la prise
toutes les 30 s et envoie un e-mail au changement d'état :

- ⚠️ passage sur batterie (décharge en cours) ;
- ✅ retour du secteur ;
- ❓ prise injoignable (coupure de courant probable ou panne Wi-Fi).

## Matériel (~35–45 €)

- Raspberry Pi Zero W / Zero 2 W (ou n'importe quel Pi déjà en service) ;
- une prise connectée **Shelly Plug S** (ou Shelly Plus Plug S) — choisie
  parce qu'elle expose une API HTTP **locale**, sans cloud ni compte ;
- le tout sur le même réseau Wi-Fi.

## Installation

### 1. La prise

1. Brancher la prise entre le mur et le chargeur de l'ordinateur.
2. La connecter au Wi-Fi avec l'application Shelly (ou son portail Web).
3. Lui fixer une IP stable (bail DHCP statique dans la box).
4. Vérifier depuis le Pi : `curl http://IP_DE_LA_PRISE/rpc/Switch.GetStatus?id=0`
   (Gen2) ou `curl http://IP_DE_LA_PRISE/status` (Gen1) doit répondre du JSON.

### 2. Le Raspberry Pi

Aucune dépendance à installer, Python 3 suffit (préinstallé sur Raspberry Pi OS) :

```bash
# copier ce dossier sur le Pi, par exemple dans /home/pi/gardien-decharge
cd /home/pi/gardien-decharge
cp config.example.ini config.ini
nano config.ini        # IP de la prise + identifiants e-mail
chmod 600 config.ini
```

Pour Gmail : activer la validation en 2 étapes puis créer un
[mot de passe d'application](https://myaccount.google.com/apppasswords)
à mettre dans `mot_de_passe` (le mot de passe habituel du compte ne
fonctionnera pas).

### 3. Tester

```bash
python3 gardien.py --mesure      # doit afficher la puissance du chargeur
python3 gardien.py --test-mail   # doit envoyer un e-mail de test
python3 gardien.py               # surveillance au premier plan (Ctrl+C pour sortir)
```

Test grandeur nature : débrancher le chargeur de la prise connectée,
l'e-mail « ordinateur sur batterie » doit arriver au bout de ~1 min 30
(3 confirmations × 30 s, réglable dans `config.ini`).

### 4. Lancer au démarrage (systemd)

```bash
sudo cp gardien.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gardien
journalctl -u gardien -f          # suivre les journaux
```

Adapter les chemins dans `gardien.service` si le dossier n'est pas
`/home/pi/gardien-decharge`.

## Régler le seuil

Le seuil par défaut est `2.0` W. Batterie pleine et ordinateur en veille,
certains chargeurs descendent très bas : lancer `python3 gardien.py --mesure`
dans cette situation et choisir un seuil en dessous de la valeur affichée
(mais au-dessus de la consommation « à vide » de la prise, ~0 W).

## Limites connues

- Si la coupure de courant touche aussi le Pi ou la box Internet, l'alerte
  « injoignable » ne peut pas partir. Parade : alimenter le Pi sur une
  batterie externe (il consomme ~1 W) et, idéalement, la box sur un petit
  onduleur — ou brancher Pi et box sur un autre circuit que l'ordinateur.
- Le gardien voit l'alimentation, pas le niveau de batterie : il sait que
  l'ordinateur se décharge, pas qu'il reste 15 %. C'est la limite d'une
  surveillance 100 % externe sans logiciel sur le poste.
- Une prise d'une autre marque avec mesure de puissance peut convenir, à
  condition d'adapter `lire_puissance()` dans `gardien.py` à son API
  (les Tapo P110, par exemple, demandent une bibliothèque dédiée).
