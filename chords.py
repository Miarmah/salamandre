"""
chords.py — Moteur de reconnaissance des accords (v2.0)
=========================================================

Livre 2.0, Chapitre 2.1 :
  « Étendre le dictionnaire d'accords de 24 à plus de 72 gabarits »

La version 1.0 ne comparait que 24 gabarits (12 majeurs + 12 mineurs).
Cette version 2.0 génère dynamiquement les gabarits à partir d'une
table d'intervalles (CHORD_INTERVALS), ce qui rend l'ajout d'un
nouveau type d'accord trivial (une ligne de configuration plutôt
qu'une duplication de code).

Qualités couvertes : maj, min, dim, aug, 7, maj7, m7, sus2, sus4
soit 9 qualités x 12 fondamentales = 108 gabarits (> 72 gabarits visés).

L'algorithme reste un "template matching" par similarité cosinus
(insensible au volume), comme en v1.0, mais le score de chaque trame
est désormais transmis à timeline.py pour un lissage par algorithme
de Viterbi (voir Livre 2.0, 2.1 §2 et §3), plutôt qu'un simple argmax
trame par trame.
"""

import numpy as np

try:
    import librosa
except ImportError:  # pragma: no cover - librosa est requis en production
    librosa = None

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ---------------------------------------------------------------------------
# Table d'intervalles (en demi-tons depuis la fondamentale) et poids associés.
# Poids : fondamentale = 1.0, tierce/seconde/quarte = 0.8, quinte = 0.9,
# septième = 0.6 (moins déterminante mais utile pour distinguer maj7/m7/7).
# ---------------------------------------------------------------------------
CHORD_INTERVALS = {
    "":     {"intervals": [0, 4, 7],      "weights": [1.0, 0.8, 0.9]},        # majeur
    "m":    {"intervals": [0, 3, 7],      "weights": [1.0, 0.8, 0.9]},        # mineur
    "dim":  {"intervals": [0, 3, 6],      "weights": [1.0, 0.8, 0.7]},        # diminué
    "aug":  {"intervals": [0, 4, 8],      "weights": [1.0, 0.8, 0.7]},        # augmenté
    "7":    {"intervals": [0, 4, 7, 10],  "weights": [1.0, 0.8, 0.9, 0.6]},   # dominante 7
    "maj7": {"intervals": [0, 4, 7, 11],  "weights": [1.0, 0.8, 0.9, 0.6]},   # majeur 7
    "m7":   {"intervals": [0, 3, 7, 10],  "weights": [1.0, 0.8, 0.9, 0.6]},   # mineur 7
    "sus2": {"intervals": [0, 2, 7],      "weights": [1.0, 0.75, 0.9]},       # suspendu 2
    "sus4": {"intervals": [0, 5, 7],      "weights": [1.0, 0.75, 0.9]},       # suspendu 4
}

# Petite matrice de "familiarité" harmonique utilisée par le post-traitement
# de Viterbi (timeline.py). Les degrés sont exprimés en écart de demi-tons
# par rapport à la fondamentale du morceau (approximation simple mais
# suffisante pour pénaliser les sauts d'accords peu plausibles).
# Cf. Livre 2.0, 2.1 §2.1 "Exemple de matrice de transition simplifiée".
COMMON_ROOT_STEPS_SEMITONES = {
    0: 1.00,   # rester sur le même accord (tonique -> tonique)
    5: 0.85,   # I -> IV (quarte juste ascendante)
    7: 0.85,   # I -> V (quinte juste ascendante)
    9: 0.60,   # I -> vi (relatif mineur)
    2: 0.45,   # I -> ii
    4: 0.35,   # I -> iii
}
DEFAULT_TRANSITION_WEIGHT = 0.15  # tout autre saut : pénalisé mais pas interdit


def generate_chords():
    """
    Construit dynamiquement l'ensemble des gabarits d'accords.

    Retourne :
        templates : np.ndarray de forme (n_gabarits, 12)
        labels    : liste de labels correspondants (ex: "C", "Dm7", "G#sus4")
    """
    templates = []
    labels = []

    for root_idx, root_name in enumerate(NOTE_NAMES):
        for quality, config in CHORD_INTERVALS.items():
            template = np.zeros(12)
            for interval, weight in zip(config["intervals"], config["weights"]):
                note_idx = (root_idx + interval) % 12
                template[note_idx] = weight
            templates.append(template)
            labels.append(f"{root_name}{quality}")

    return np.array(templates), labels


# Gabarits calculés une seule fois au chargement du module.
TEMPLATES, LABELS = generate_chords()
# Normalisation L2 des gabarits pour permettre une similarité cosinus directe.
_TEMPLATE_NORMS = np.linalg.norm(TEMPLATES, axis=1)
_TEMPLATE_NORMS[_TEMPLATE_NORMS == 0] = 1.0
TEMPLATES_UNIT = TEMPLATES / _TEMPLATE_NORMS[:, None]


def _cosine_scores(chroma_vector: np.ndarray) -> np.ndarray:
    """Calcule le score de similarité cosinus entre un vecteur chroma et
    chacun des gabarits d'accords. Retourne un vecteur de scores (un par
    gabarit dans TEMPLATES/LABELS), insensible au volume du signal."""
    norm = np.linalg.norm(chroma_vector)
    if norm == 0:
        return np.zeros(len(LABELS))
    unit_vec = chroma_vector / norm
    return TEMPLATES_UNIT @ unit_vec


def root_index_of_label(label: str) -> int:
    """Retrouve l'indice (0-11) de la fondamentale à partir d'un label
    d'accord tel que 'C', 'G#m7' ou 'Bsus4'."""
    if len(label) > 1 and label[1] == "#":
        root = label[:2]
    else:
        root = label[:1]
    return NOTE_NAMES.index(root)


def transition_weight(label_a: str, label_b: str) -> float:
    """
    Renvoie un poids de transition harmonique entre deux accords, utilisé
    par le post-traitement de Viterbi (timeline.py) pour pénaliser les
    enchaînements peu plausibles (Livre 2.0, 2.1 §2.1 et §3).
    """
    step = (root_index_of_label(label_b) - root_index_of_label(label_a)) % 12
    return COMMON_ROOT_STEPS_SEMITONES.get(step, DEFAULT_TRANSITION_WEIGHT)


def score_frame(chroma_vector: np.ndarray):
    """
    Calcule, pour une trame (un vecteur chroma à 12 dimensions), le score
    de chacun des gabarits d'accords. Utilisé par timeline.py pour
    construire la matrice d'émission nécessaire au lissage par Viterbi.

    Retourne (scores, best_label, best_score).
    """
    scores = _cosine_scores(chroma_vector)
    best_idx = int(np.argmax(scores))
    return scores, LABELS[best_idx], float(scores[best_idx])


def detect_chord(notes):
    """
    Détecte l'accord le plus probable à partir d'une liste de notes
    détectées (ex: ["C", "E", "G"]). Conservée depuis la v1.0 pour la
    compatibilité ascendante (utilisée par certains tests unitaires
    et par timeline.py en mode "legacy" sans lissage).
    """
    if not notes:
        return "Unknown"

    vec = np.zeros(12)
    for n in notes:
        # Sécurise une chaîne de caractères et élève l'octave si présente
        if isinstance(n, str):
            name = n[:-1] if (len(n) > 1 and n[-1].isdigit()) else n
        else:
            name = n
        if name in NOTE_NAMES:
            idx = NOTE_NAMES.index(name)
            vec[idx] += 1

    scores = _cosine_scores(vec)
    best_idx = int(np.argmax(scores))

    if scores[best_idx] < 0.55:  # seuil de confiance minimal
        return "Unknown"

    return LABELS[best_idx]


def detect_chords_from_audio(y, sr):
    """
    Version "brute" (sans lissage) de la détection d'accords à partir du
    signal audio : calcule le chromagramme CQT, le synchronise sur les
    battements réels, puis renvoie le meilleur gabarit par battement.

    Cette fonction reste disponible telle quelle pour compatibilité,
    mais le pipeline v2.0 (analyse.py) utilise plutôt
    timeline.detect_chords_from_audio(), qui applique en plus le
    post-traitement de Viterbi décrit au Chapitre 2.1.
    """
    if librosa is None:
        raise RuntimeError("librosa est requis pour l'analyse audio.")

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)

    timeline = []
    last_chord = None

    for i in range(chroma_sync.shape[1]):
        _, chord, score = score_frame(chroma_sync[:, i])

        if score < 0.35:
            chord = "..."

        time_sec = round(float(beat_times[i]), 2) if i < len(beat_times) else 0.0

        if chord != last_chord:
            timeline.append({"time": time_sec, "chord": chord})
            last_chord = chord

    return timeline, tempo
