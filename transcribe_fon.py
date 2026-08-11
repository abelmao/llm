import base64, numpy as np, av, librosa, tiktoken, onnxruntime as ort

D = "sherpa-onnx-whisper-turbo"
SOT, EOT, NOTS, PREV = 50258, 50257, 50364, 50362
TRANSCRIBE = 50360
LANG = {"fr": 50265, "yo": 50325, "en": 50259}

ranks = {}
for line in open("multilingual.tiktoken", "rb"):
    tok, rank = line.split()
    ranks[base64.b64decode(tok)] = int(rank)
enc = tiktoken.Encoding(name="whisper", pat_str=r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+""",
                        mergeable_ranks=ranks, special_tokens={})

def load_audio(path):
    rs = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
    c = av.open(path); chunks = []
    for fr in c.decode(audio=0):
        for f in rs.resample(fr): chunks.append(f.to_ndarray())
    pcm = np.concatenate(chunks, axis=1).flatten().astype(np.float32) / 32768.0
    return (pcm / np.abs(pcm).max() * 0.95).astype(np.float32)

def logmel(audio):
    a = np.zeros(480000, dtype=np.float32); a[:len(audio)] = audio[:480000]
    stft = librosa.stft(a, n_fft=400, hop_length=160, window="hann", center=True)
    mag = np.abs(stft[:, :-1]) ** 2
    mel = librosa.filters.mel(sr=16000, n_fft=400, n_mels=128) @ mag
    log = np.log10(np.maximum(mel, 1e-10))
    log = np.maximum(log, log.max() - 8.0)
    return (((log + 4.0) / 4.0).astype(np.float32))[None]

encs = ort.InferenceSession(f"{D}/turbo-encoder.int8.onnx", providers=["CPUExecutionProvider"])
decs = ort.InferenceSession(f"{D}/turbo-decoder.int8.onnx", providers=["CPUExecutionProvider"])

def encode_audio(mel):
    k, v = encs.run(None, {"mel": mel}); return k, v

def new_cache():
    return (np.zeros((4,1,448,1280), np.float32), np.zeros((4,1,448,1280), np.float32))

def dec_step(tokens, kc, vc, ck, cv, offset):
    logits, kc, vc = decs.run(None, {"tokens": np.array([tokens], np.int64),
        "in_n_layer_self_k_cache": kc, "in_n_layer_self_v_cache": vc,
        "n_layer_cross_k": ck, "n_layer_cross_v": cv,
        "offset": np.array([offset], np.int64)})
    return logits[0, -1], kc, vc

def generate(ck, cv, lang="fr", prompt=None, max_new=80):
    init = ([PREV] + enc.encode(" " + prompt.strip()) if prompt else []) + [SOT, LANG[lang], TRANSCRIBE, NOTS]
    kc, vc = new_cache()
    logits, kc, vc = dec_step(init, kc, vc, ck, cv, 0)
    offset = len(init); out = []
    for _ in range(max_new):
        logits[50257:50364] = -np.inf  # suppress specials except allow EOT
        nxt = int(np.argmax(np.concatenate([logits[:50257], logits[50257:50258]*0 + logits[50257:50258]])) ) if False else int(np.argmax(np.where(np.arange(51866)==EOT, logits, np.where(np.arange(51866)>=50257, -np.inf, logits))))
        if nxt == EOT: break
        out.append(nxt)
        logits, kc, vc = dec_step([nxt], kc, vc, ck, cv, offset); offset += 1
    return enc.decode(out)

def score(ck, cv, text, lang="fr"):
    toks = enc.encode(" " + text.strip())
    seq = [SOT, LANG[lang], TRANSCRIBE, NOTS] + toks + [EOT]
    kc, vc = new_cache()
    logits, kc, vc = dec_step(seq[:1], kc, vc, ck, cv, 0)
    total = 0.0
    for i in range(1, len(seq)):
        lp = logits - logits.max(); lp = lp - np.log(np.exp(lp).sum())
        if i >= 4:  # score only content tokens + EOT
            total += lp[seq[i]]
        if i < len(seq) - 1:
            logits, kc, vc = dec_step([seq[i]], kc, vc, ck, cv, i)
    n = len(toks) + 1
    return total / n, total

# ---------------------------------------------------------------------------
# Usage CLI : python3 transcribe_fon.py <audio> [prompt vocabulaire]
# Décode l'audio en phonétique (fr + yo), puis en décodage guidé par le
# vocabulaire de la boutique. Voir README.md pour les modèles à télécharger.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    vocab = sys.argv[2] if len(sys.argv) > 2 else (
        "Boutique au Bénin. Omo, Javel, savon, sucre, cube maggi. "
        "atassinɔ, yí, bo yi, atɔn, wè, ɛnɛ, atɔɔn, six, cent francs.")
    audio = load_audio(path)
    mel = logmel(audio)
    ck, cv = encode_audio(mel)
    print("phonétique fr :", generate(ck, cv, "fr"))
    print("phonétique yo :", generate(ck, cv, "yo"))
    print("guidé (vocab) :", generate(ck, cv, "fr", prompt=vocab))
