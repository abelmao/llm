# PiKVM — activer le micro (audio bidirectionnel) pour les calls

Source : documentation officielle PiKVM (`docs/audio.md`, `docs/tailscale.md`), KVMD ≥ 4.44.

## 0. Prérequis

- **Matériel** : PiKVM **V4 Mini/Plus ou V3 officiel** uniquement. Les DIY (CSI ou dongle USB)
  n'ont **pas** d'audio — dans ce cas, plan B Sonobus.
- **Protocole** : l'audio ne marche qu'en mode **WebRTC** dans l'interface web (pas MJPEG, pas VNC).
- Mettre à jour d'abord (SSH sur le PiKVM, utilisateur `root`) :
  ```console
  rw
  pikvm-update
  reboot
  ```

## 1. Audio entrant (entendre le PC)

- **V4 Mini/Plus** : actif par défaut (sauf EDID personnalisé).
- **V3** : vérifier que les 4 cavaliers audio sont en place et que `dtoverlay=tc358743-audio`
  figure dans `/boot/config.txt`, puis :
  ```console
  rw
  kvmd-edidconf --set-audio=yes
  reboot
  ```
- **Sur le PC cible** : Paramètres son → **sortie = l'écran HDMI du PiKVM**.
- **Interface web** : menu Système → mode vidéo **WebRTC** → activer **Multimedia** → volume.

## 2. Micro (ta voix vers le PC)

Prérequis : l'audio entrant fonctionne.

1. SSH sur le PiKVM :
   ```console
   rw
   nano /etc/kvmd/override.yaml
   ```
2. Ajouter (indentation en **espaces**, jamais de tabulations ; fusionner avec une éventuelle
   section `otg:` existante) :
   ```yaml
   otg:
       devices:
           audio:
               enabled: true
   ```
3. `reboot`.
4. Après redémarrage, le PC voit un **nouveau micro USB** (périphérique composite PiKVM) :
   Paramètres son du PC → entrée → le sélectionner ; dans Teams/Zoom → Périphériques →
   micro = ce micro USB.
5. **Interface web** : Système → WebRTC → **Multimedia ON** → **Microphone ON** → choisir le micro
   de ton casque dans le sélecteur → autoriser l'accès micro demandé par le navigateur.

## 3. Accès par Internet (Tailscale)

```console
rw
pacman -S tailscale-pikvm
systemctl enable --now tailscaled
tailscale up        # suivre le lien d'autorisation affiché
reboot
ip addr show tailscale0   # noter l'IP 100.x.y.z
```
Installer Tailscale sur ton appareil (téléphone/PC), puis ouvrir `https://<ip_tailscale_du_pikvm>`.
Désactiver l'expiration de clé pour cette machine dans la console Tailscale.

## 4. Test de latence (jour 1, pendant la fenêtre de retour)

- Casque branché sur TON appareil (obligatoire : pas d'annulation d'écho).
- Teams : « Effectuer un appel test » (echo test) → écouter le retour de ta voix.
- Repères : < 200 ms confortable ; 200-400 ms perceptible mais acceptable ; > 400 ms ou son
  haché → voir dépannage, sinon plan B.

## Dépannage

- Logs audio : `journalctl -u kvmd-janus`.
- Tester avec Firefox, ou Chrome en navigation privée (extensions/permissions).
- Pas de son = vérifier mode **WebRTC** actif (pas MJPEG) et sortie son du PC sur le HDMI PiKVM.
- Bug connu : l'audio peut décrocher après de longs silences (issue pikvm#1621) — garder un léger
  fond sonore côté PC ou couper/réactiver Multimedia si le son disparaît.
- Si la latence micro est rédhibitoire : plan B = pont analogique Sonobus (téléphone/Pi → prise
  micro du PC), latence documentée ~30-80 ms.
