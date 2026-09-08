"""
timeline.py — Constructeur de la ligne du temps (v2.0)
=========================================================

Livre 2.0, Chapitre 2.1 §2 et §3 :
  « Lissage par chaîne de Markov / programmation dynamique : appliquer
    un algorithme de Viterbi simplifié qui pénalise les changements
    d'accords trop fréquents. »

La v1.0 regroupait les notes détectées en blocs par une simple fenêtre
temporelle glissante (min_interval fixe à 0.4s), sans tenir compte de
la plausibilité harmonique des enchaînements. Cette v2.0 ajoute un
véritable post-traitement de Viterbi : la séquence d'accords est
modélisée comme un modèle de Markov caché (HMM), où les probabilités
d'émission viennent du score de similarité cosinus (chords.py) et les
probabilités de transition d'une matrice harmonique simplifiée
(chords.transition_weight).

La fonction historique detect_chords_from_audio(notes, times, ...) est
conservée pour compatibilité ascendante (v1.0), tandis que
build_smoothed_timeline() est le nouveau point d'entrée utilisé par
analyse.py.
"""

import numpy as np

try:
    import librosa
except ImportError:  # pragma: no cover
    librosa = None

from chords import LABELS, score_frame, transition_weight


# ---------------------------------------------------------------------------
# Fonction historique (v1.0) — conservée telle quelle pour compatibilité.
# ---------------------------------------------------------------------------
def detect_chords_from_audio(notes, times, min_interval=0.4):
    """
    Regroupe une séquence de notes/timestamps en blocs temporels
    cohérents (fenêtre glissante fixe), puis envoie chaque bloc à
    chords.detect_chord(). Conservée depuis la v1.0.
    """
    from chords import detect_chord  # import local pour éviter tout cycle

    timeline = []
    if not notes or not times:
        return timeline

    current_notes = [notes[0]]
    last_time = times[0]

    for i in range(1, len(notes)):
        if times[i] - last_time < min_interval:
            current_notes.append(notes[i])
        else:
            chord = detect_chord(current_notes)
            timeline.append({"time": round(last_time, 2), "chord": chord})
            current_notes = [notes[i]]
            last_time = times[i]

    return timeline


# ---------------------------------------------------------------------------
# Nouveau pipeline v2.0 — fenêtrage synchronisé aux battements + Viterbi.
# ---------------------------------------------------------------------------
def _viterbi_smooth(emission_log_probs: np.ndarray, transition_bonus_weight: float = 2.5):
    """
    Applique un algorithme de Viterbi simplifié sur une séquence de
    probabilités d'émission (une ligne par trame, une colonne par accord
    possible), en pénalisant les transitions harmoniquement improbables.

    Retourne la liste des indices d'accords les plus probables (un par
    trame), selon la matrice TEMPLATES/LABELS de chords.py.
    """
    n_frames, n_labels = emission_log_probs.shape
    if n_frames == 0:
        return []

    # Table de transition (log) précalculée une seule fois.
    log_transition = np.zeros((n_labels, n_labels))
    for a in range(n_labels):
        for b in range(n_labels):
            w = transition_weight(LABELS[a], LABELS[b])
            log_transition[a, b] = np.log(max(w, 1e-6)) * transition_bonus_weight

    # Programmation dynamique (forward pass).
    dp = np.zeros((n_frames, n_labels))
    backpointer = np.zeros((n_frames, n_labels), dtype=int)
    dp[0] = emission_log_probs[0]

    for t in range(1, n_frames):
        # score(t, j) = max_i [ dp(t-1, i) + transition(i -> j) ] + emission(t, j)
        candidate = dp[t - 1][:, None] + log_transition  # (n_labels, n_labels)
        backpointer[t] = np.argmax(candidate, axis=0)
        dp[t] = np.max(candidate, axis=0) + emission_log_probs[t]

    # Backtracking.
    path = np.zeros(n_frames, dtype=int)
    path[-1] = int(np.argmax(dp[-1]))
    for t in range(n_frames - 2, -1, -1):
        path[t] = backpointer[t + 1, path[t + 1]]

    return path.tolist()


def build_smoothed_timeline(y, sr, silence_threshold: float = 0.12):
    """
    Pipeline principal v2.0 :
      1. Chromagramme CQT synchronisé sur les battements réels.
      2. Calcul du score d'émission de chaque gabarit d'accord par battement.
      3. Lissage de la séquence par un algorithme de Viterbi simplifié
         (pénalise les changements d'accords harmoniquement improbables).
      4. Fusion des battements consécutifs partageant le même accord en
         segments {start, end, chord}.

    Retourne (timeline, tempo) où timeline est une liste de segments :
        [{"start": 0.0, "end": 1.6, "chord": "C"}, ...]
    """
    if librosa is None:
        raise RuntimeError("librosa est requis pour l'analyse audio.")

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)

    n_frames = chroma_sync.shape[1]
    if n_frames == 0:
        return [], float(tempo)

    n_labels = len(LABELS)
    emission_scores = np.zeros((n_frames, n_labels))
    frame_energy = np.zeros(n_frames)

    for i in range(n_frames):
        scores, _, _ = score_frame(chroma_sync[:, i])
        emission_scores[i] = scores
        frame_energy[i] = np.max(chroma_sync[:, i])

    # Les scores cosinus sont dans [-1, 1] ; on les met à l'échelle en
    # pseudo-log-probabilités pour la programmation dynamique de Viterbi.
    emission_log_probs = emission_scores * 4.0

    best_path = _viterbi_smooth(emission_log_probs)

    # Construction des segments {start, end, chord}, avec fusion des
    # battements consécutifs identiques et détection des passages "silencieux".
    raw_labels = []
    for i, label_idx in enumerate(best_path):
        if frame_energy[i] < silence_threshold:
            raw_labels.append("...")
        else:
            raw_labels.append(LABELS[label_idx])

    segments = []
    current_chord = raw_labels[0]
    current_start = float(beat_times[0]) if len(beat_times) > 0 else 0.0

    for i in range(1, n_frames):
        if raw_labels[i] != current_chord:
            end_time = float(beat_times[i]) if i < len(beat_times) else current_start
            segments.append({
                "start": round(current_start, 2),
                "end": round(end_time, 2),
                "chord": current_chord,
            })
            current_chord = raw_labels[i]
            current_start = end_time

    total_duration = librosa.get_duration(y=y, sr=sr)
    segments.append({
        "start": round(current_start, 2),
        "end": round(total_duration, 2),
        "chord": current_chord,
    })

    return segments, float(tempo)
