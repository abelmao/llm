# Gardien de décharge

Un « gardien » externe sur Raspberry Pi qui **écoute le PC** et prévient par
e-mail quand il passe sur batterie, quand la batterie devient faible, ou
quand il ne donne plus signe de vie — pensé pour un poste où l'on n'est
**pas administrateur**.

## Ce qu'on peut savoir de l'extérieur (et comment)

Sans rien sur le PC, un objet externe ne peut savoir qu'une chose : *le PC
répond-il encore ?* Le niveau de batterie est une information interne — pour
l'avoir, il faut que le PC la dise, ce qu'un simple script **utilisateur**
fait sans aucun droit administrateur. D'où trois modes, du plus léger au
plus complet :

| Mode | Ce qu'il détecte | Côté PC | Matériel en plus |
|---|---|---|---|
| `ping` | PC éteint, en veille, injoignable / de retour | rien | aucun |
| `balise` | passage sur batterie, **% de batterie**, batterie faible, PC silencieux | un script utilisateur (sans admin, sans installation) | aucun |
| `prise` | chargeur qui ne tire plus rien (décharge probable), retour secteur, coupure | rien | prise Shelly ~15 € |

Le mode se choisit dans `config.ini` (`[surveillance] mode = ...`).
Recommandation : `balise` si le poste autorise l'exécution d'un script
utilisateur (c'est le seul mode qui voit vraiment la batterie), sinon `ping`.

## Installation sur le Raspberry Pi (commun à tous les modes)

Aucune dépendance, Python 3 suffit (préinstallé sur Raspberry Pi OS) :

```bash
# copier ce dossier sur le Pi, par exemple dans /home/pi/gardien-decharge
cd /home/pi/gardien-decharge
cp config.example.ini config.ini
nano config.ini        # mode + identifiants e-mail
chmod 600 config.ini
```

Pour Gmail : activer la validation en 2 étapes puis créer un
[mot de passe d'application](https://myaccount.google.com/apppasswords)
à mettre dans `mot_de_passe` (le mot de passe habituel ne fonctionnera pas).

Tester puis activer au démarrage :

```bash
python3 gardien.py --test-mail   # doit envoyer un e-mail de test
python3 gardien.py --mesure      # une mesure de la sonde du mode choisi
python3 gardien.py               # surveillance au premier plan (Ctrl+C pour sortir)

sudo cp gardien.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gardien
journalctl -u gardien -f          # suivre les journaux
```

Adapter les chemins dans `gardien.service` si le dossier n'est pas
`/home/pi/gardien-decharge`.

## Mode `ping` — le Pi écoute le PC sur le réseau

1. Trouver l'IP du PC (`ipconfig` sous Windows, `ip a` sous Linux) et la
   mettre dans `[pc] adresse`. Sur un réseau domestique, fixer un bail DHCP
   statique dans la box pour qu'elle ne change pas.
2. Vérifier depuis le Pi, PC allumé : `ping IP_DU_PC` doit répondre.
   Si le PC ne répond pas au ping même allumé, c'est son pare-feu ;
   l'autoriser demande des droits admin — utiliser alors `balise` ou `prise`.

Alertes : « le PC ne répond plus » (éteint, en veille, réseau perdu — et
s'il était sur batterie, elle est peut-être vide) et « le PC répond de
nouveau ». La mise en veille coupe la réponse au ping : c'est aussi une
information, mais en tenir compte avant de s'inquiéter.

## Mode `balise` — le PC dit lui-même où en est sa batterie

Le Pi écoute en HTTP sur le port `[balise] port` (8642 par défaut) ; le PC
lui envoie toutes les 60 s son niveau de batterie et l'état secteur via un
script **en simple utilisateur** : pas d'installation, pas d'élévation de
droits, et les identifiants e-mail restent sur le Pi — rien de sensible sur
le poste.

**Windows** — copier `client/balise.ps1` sur le PC, puis :

```
powershell -ExecutionPolicy Bypass -File balise.ps1 -Gardien http://IP_DU_PI:8642
```

Pour le lancer à chaque ouverture de session (toujours sans admin) :
`Win + R` → `shell:startup` → créer un raccourci vers :

```
powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\chemin\balise.ps1" -Gardien "http://IP_DU_PI:8642"
```

**Linux / macOS** — copier `client/balise.sh` et le lancer :

```bash
sh balise.sh http://IP_DU_PI:8642
```

Vérifier la réception côté Pi avec `python3 gardien.py --mesure` (attend
une balise pendant 90 s et l'affiche).

Alertes : passage sur batterie (avec le pourcentage), batterie sous
`seuil_batterie` (20 % par défaut), retour secteur, et « plus de nouvelles
du PC » si aucune balise n'arrive pendant `silence_secondes` (PC éteint,
en veille, batterie vide ou script arrêté).

Si le poste est verrouillé au point d'interdire même un script PowerShell
utilisateur (AppLocker…), se rabattre sur `ping` ou `prise`.

## Mode `prise` — mesurer le chargeur

```
Mur ──> Prise connectée Shelly ──> Chargeur ──> Ordinateur
              ▲
              │ mesure de puissance (Wi-Fi, API locale)
        Raspberry Pi ──> e-mail d'alerte
```

Une prise **Shelly Plug S** (API HTTP locale, sans cloud ni compte)
s'intercale entre le mur et le chargeur. Tant que l'ordinateur est alimenté,
le chargeur tire une puissance mesurable ; ~0 W = chargeur débranché ou
courant coupé, donc décharge probable.

1. Brancher la prise entre le mur et le chargeur, la connecter au Wi-Fi
   avec l'application Shelly, lui fixer une IP stable (bail DHCP).
2. Renseigner `[prise] adresse` et vérifier : `python3 gardien.py --mesure`.
3. Régler `seuil_watts` : batterie pleine et ordinateur en veille, certains
   chargeurs descendent très bas — mesurer dans cette situation et choisir
   un seuil juste en dessous.

## Limites connues

- Si une coupure de courant touche aussi le Pi ou la box Internet, l'alerte
  ne peut pas partir. Parade : Pi sur batterie externe (~1 W de
  consommation) et, idéalement, box sur un petit onduleur.
- En mode `ping`, la veille et l'extinction sont indistinguables, et le
  niveau de batterie est inconnu : seul `balise` le voit.
- En mode `balise`, la mise en veille arrête le script : l'alerte « plus de
  nouvelles » couvre ce cas.
