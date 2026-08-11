# Journal des ventes — notes vocales en fon (fongbé)

Pipeline pour comprendre des notes vocales enregistrées dans une boutique au Bénin,
où l'interlocuteur parle en fon (fongbé) mélangé de français et de noms de marques.

## Workflow validé (note n°1, 11/08/2026)

1. **Transcription phonétique** — Whisper turbo (ONNX, via sherpa-onnx) ne connaît pas
   le fon : on décode en plusieurs langues (fr, yo, ln) et plusieurs variantes audio
   (normalisé, ralenti, répété) pour trianguler une lecture phonétique stable.
2. **Décodage guidé** — décodeur ONNX piloté à la main (`transcribe_fon.py`) qui accepte
   un *prompt* de vocabulaire (produits de la boutique, mots fon du glossaire) pour
   biaiser la reconnaissance vers les mots attendus.
3. **Reconstitution fon** — on segmente la phonétique avec la grammaire type :
   `[client]nɔ̀ yí [produit] [quantité], bó yí [produit] [quantité]…`
4. **Vérification** — Google Translate (code langue `fon`) dans les deux sens :
   oracle français→fon pour l'orthographe canonique, fon→français pour valider le sens.
5. **Scoring** — chaque hypothèse de phrase est scorée contre l'audio (log-prob du
   décodeur, teacher forcing) pour départager les lectures concurrentes.
6. **Calibration humaine** — la personne qui connaît le contexte confirme ; chaque note
   validée enrichit `glossaire.md`.

## Exemple validé

Audio : `AUDIO20260811215921.m4a` (4,4 s)

- Phonétique stabilisée : `[ā-tā-sī-nā-i] [ō-mō-a-tɔ̃] [bo-i] [jā-vel] [sis]`
- Fon reconstitué : **« Atassinɔ̀ yí Omo atɔ̀n, bó yí Javel six. »**
- Français : **« La vendeuse d'atassi a pris 3 Omo, et elle a pris 6 Javel. »**

## Dépendances

```
pip install av numpy librosa onnxruntime tiktoken sherpa-onnx
# modèle : https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-turbo.tar.bz2
# tokenizer : https://raw.githubusercontent.com/openai/whisper/main/whisper/assets/multilingual.tiktoken
```

Voir `glossaire.md` (vocabulaire fon du commerce) et `journal_ventes.md` (registre des notes).
