"""
analyse.py — Orchestrateur du traitement du signal (v2.0)
=============================================================

Centralise l'appel aux autres modules et applique les prétraitements
recommandés au Livre 2.0, Chapitre 2.2 §1, §3 et §4 :

  1. Prétraitement du signal : normalisation, suppression des silences,
     ré-échantillonnage à un taux fixe (22050 Hz).
  2. Séparation de sources optionnelle (separation.py) pour isoler la
     piste harmonique avant l'analyse d'accords.
  3. Détection du tempo, y compris une courbe de tempo dynamique
     (gestion des ralentis/rubato).
  4. Détection de la tonalité par segments (modulation).
  5. Détection des accords avec dictionnaire étendu + lissage Viterbi.

La fonction historique analyse_song(path) est conservée en point
d'entrée unique, mais son contenu est entièrement revu.
"""

import os
import traceback

import numpy as np

try:
    import librosa
except ImportError:  # pragma: no cover
    librosa = None

from note import freq_to_note  # noqa: F401 (utilitaire exposé pour d'autres modules)
from tonalite import detect_key_segments
from timeline import build_smoothed_timeline
from separation import separate_other_stem

TARGET_SAMPLE_RATE = 22050


def _preprocess(path: str):
    y, sr = librosa.load(path, sr=TARGET_SAMPLE_RATE)
    y = librosa.util.normalize(y)
    y_trimmed, _ = librosa.effects.trim(y, top_db=30)
    return y_trimmed, sr


def _dynamic_tempo(y, sr):
    tempo_global, _ = librosa.beat.beat_track(y=y, sr=sr)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    dynamic = librosa.beat.tempo(onset_envelope=onset_env, sr=sr, aggregate=None)

    # Sous-échantillonne la courbe pour rester légère à transmettre au Front-End.
    step = max(1, len(dynamic) // 60)
    tempo_curve = [round(float(v), 1) for v in dynamic[::step]]

    return float(tempo_global), tempo_curve


def analyse_song(path: str, use_source_separation: bool = False):
    if librosa is None:
        return {"error": "librosa n'est pas installé sur ce serveur."}

    if not os.path.exists(path):
        return {"error": f"Fichier introuvable : {path}"}

    try:
        analysis_path = path
        if use_source_separation:
            analysis_path = separate_other_stem(path)

        y, sr = _preprocess(analysis_path)

        tempo_global, tempo_curve = _dynamic_tempo(y, sr)
        key_segments = detect_key_segments(y, sr)
        timeline, _beat_tempo = build_smoothed_timeline(y, sr)

        return {
            "tempo": round(tempo_global, 1),
            "tempo_curve": tempo_curve,
            "key": key_segments,
            "timeline": timeline,
        }

    except Exception as exc:
        print(traceback.format_exc())
        return {"error": f"Erreur lors de l'analyse : {exc}"}
