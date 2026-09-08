"""
tonalite.py — Analyseur de clé musicale (v2.0)
=================================================

Livre 2.0, Chapitre 2.2 §2 :
  « Détecter les modulations de tonalité par fenêtres glissantes plutôt
    qu'une seule tonalité globale. »

La v1.0 calculait un seul coefficient de corrélation de
Krumhansl-Schmuckler sur la moyenne du chromagramme de toute la
chanson (detect_key). Cette v2.0 conserve cette fonction telle quelle
(elle reste utile pour un aperçu rapide), mais ajoute
detect_key_segments(), qui découpe le morceau en fenêtres glissantes
et ne signale une modulation que si la tonalité change et reste
stable sur au moins deux fenêtres consécutives, afin d'éviter les
faux positifs liés au bruit.
"""

import numpy as np

try:
    import librosa
except ImportError:  # pragma: no cover
    librosa = None

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Profils standard de Krumhansl-Schmuckler pour les gammes majeures/mineures.
MAJ_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MIN_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _correlate_chroma_to_key(chroma_avg: np.ndarray):
    """Corrèle un chromagramme moyen aux 24 profils (12 majeurs + 12
    mineurs) et renvoie le nom de la meilleure clé + son score."""
    best_corr = -1.0
    best_key = "Inconnue"

    for i in range(12):
        for name, profile in [("majeur", MAJ_PROFILE), ("mineur", MIN_PROFILE)]:
            shifted = np.roll(profile, i)
            corr = np.corrcoef(chroma_avg, shifted)[0, 1]
            if corr > best_corr:
                best_corr = corr
                best_key = f"{NOTE_NAMES[i]} {name}"

    return best_key, best_corr


def detect_key(y, sr):
    """
    Détecte la tonalité globale d'un morceau (une seule valeur pour
    l'ensemble du signal). Conservée depuis la v1.0.
    """
    if librosa is None:
        raise RuntimeError("librosa est requis pour l'analyse audio.")

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

    # Préaccentuation : amplifie les hautes fréquences, atténue les basses
    # (souvent polluées par la basse/le kick), pour mieux isoler les
    # harmoniques utiles à la détection de tonalité.
    y_filt = librosa.effects.preemphasis(y)
    chroma_filt = librosa.feature.chroma_cqt(y=y_filt, sr=sr)

    chroma_avg = np.mean(chroma_filt, axis=1)
    if np.max(chroma_avg) > 0:
        chroma_avg = chroma_avg / np.max(chroma_avg)

    key, _ = _correlate_chroma_to_key(chroma_avg)
    return key


def detect_key_segments(y, sr, window_seconds: float = 12.0, min_stable_windows: int = 2):
    """
    Détecte la tonalité par fenêtres glissantes afin de repérer les
    modulations (Livre 2.0, 2.2 §2). Retourne une liste de segments :

        [{"start": 0.0, "end": 96.0, "key": "Do majeur"}, ...]

    Une modulation n'est signalée comme un nouveau segment que si la
    tonalité détectée reste stable sur au moins `min_stable_windows`
    fenêtres consécutives, afin d'éviter les faux positifs liés au bruit.
    """
    if librosa is None:
        raise RuntimeError("librosa est requis pour l'analyse audio.")

    duration = librosa.get_duration(y=y, sr=sr)
    window_samples = int(window_seconds * sr)
    hop_samples = window_samples  # fenêtres jointives (non chevauchantes)

    raw_windows = []  # [(start_time, end_time, key_name)]
    for start_sample in range(0, len(y), hop_samples):
        end_sample = min(start_sample + window_samples, len(y))
        chunk = y[start_sample:end_sample]
        if len(chunk) < sr * 2:  # ignorer les micro-fenêtres finales (<2s)
            continue

        chroma = librosa.feature.chroma_cqt(y=chunk, sr=sr)
        chroma_avg = np.mean(chroma, axis=1)
        if np.max(chroma_avg) > 0:
            chroma_avg = chroma_avg / np.max(chroma_avg)

        key, _ = _correlate_chroma_to_key(chroma_avg)
        start_t = start_sample / sr
        end_t = end_sample / sr
        raw_windows.append((start_t, end_t, key))

    if not raw_windows:
        return [{"start": 0.0, "end": duration, "key": "Inconnue"}]

    # Fusionne les fenêtres consécutives de même tonalité, et n'accepte un
    # changement de tonalité que s'il est confirmé par au moins
    # `min_stable_windows` fenêtres consécutives.
    segments = []
    current_key = raw_windows[0][2]
    current_start = raw_windows[0][0]
    pending_key = None
    pending_count = 0

    for i in range(1, len(raw_windows)):
        _, end_t, key = raw_windows[i]

        if key == current_key:
            pending_key = None
            pending_count = 0
            continue

        if key == pending_key:
            pending_count += 1
        else:
            pending_key = key
            pending_count = 1

        if pending_count >= min_stable_windows:
            # Modulation confirmée : clôturer le segment courant.
            change_start = raw_windows[i - pending_count + 1][0]
            segments.append({"start": round(current_start, 2), "end": round(change_start, 2), "key": current_key})
            current_key = key
            current_start = change_start
            pending_key = None
            pending_count = 0

    segments.append({"start": round(current_start, 2), "end": round(duration, 2), "key": current_key})
    return segments
