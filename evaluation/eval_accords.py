"""
evaluation/eval_accords.py — Script d'évaluation de précision (mir_eval)
=============================================================================

Livre 2.0, Chapitre 2.3 :
  « Une amélioration ne peut être considérée comme réelle que si elle
    est mesurée. [...] La bibliothèque mir_eval [...] fournit des
    implémentations prêtes à l'emploi de ces métriques. »

Usage :

    python evaluation/eval_accords.py --ground-truth reference/song1.json \
                                       --audio songs/song1.wav

Le fichier de référence (ground truth) est un JSON au format :

    [
      {"start": 0.0, "end": 2.0, "chord": "C"},
      {"start": 2.0, "end": 4.0, "chord": "G"},
      ...
    ]

Ce script :
  1. Charge le fichier de référence (transcrit manuellement, Ch. 2.3 §1).
  2. Lance l'analyse I-Music sur le même fichier audio.
  3. Compare les deux timelines avec mir_eval.chord et affiche les
     métriques recommandées (root, majmin, sh10... et accuracy pondérée).

Ce script ne nécessite aucune base de données : le jeu de référence
est un simple fichier JSON versionné avec le code (répertoire
evaluation/reference/, à créer par l'équipe au fil des transcriptions).
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import mir_eval
except ImportError:
    mir_eval = None

# Permet d'exécuter ce script directement (python evaluation/eval_accords.py)
# en important les modules du dossier parent (I-Musicpy/).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyse import analyse_song  # noqa: E402


def _segments_to_arrays(segments):
    """Convertit une liste de segments {start, end, chord} en tableaux
    (intervals, labels) attendus par mir_eval.chord."""
    intervals = np.array([[s["start"], s["end"]] for s in segments], dtype=float)
    labels = [s["chord"] for s in segments]
    return intervals, labels


def _normalize_label_for_mir_eval(label: str) -> str:
    """
    mir_eval attend une syntaxe de type "C:maj", "D:min7", "N" (aucun
    accord). Traduit les labels internes d'I-Music (ex: "C", "Dm7",
    "...", "Unknown") vers cette syntaxe.
    """
    if label in ("...", "Unknown", None):
        return "N"

    # Sépare la fondamentale (1 ou 2 caractères) du suffixe de qualité.
    root = label[:2] if len(label) > 1 and label[1] == "#" else label[:1]
    quality = label[len(root):]

    quality_map = {
        "": "maj", "m": "min", "dim": "dim", "aug": "aug",
        "7": "7", "maj7": "maj7", "m7": "min7", "sus2": "sus2", "sus4": "sus4",
    }
    return f"{root}:{quality_map.get(quality, 'maj')}"


def evaluate(ground_truth_path: str, audio_path: str):
    if mir_eval is None:
        print("mir_eval n'est pas installé (pip install mir_eval).")
        sys.exit(1)

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        reference_segments = json.load(f)

    print(f"Analyse de {audio_path} ...")
    result = analyse_song(audio_path)

    if "error" in result:
        print(f"Erreur d'analyse : {result['error']}")
        sys.exit(1)

    predicted_segments = result["timeline"]

    ref_intervals, ref_labels = _segments_to_arrays(reference_segments)
    est_intervals, est_labels = _segments_to_arrays(predicted_segments)

    ref_labels = [_normalize_label_for_mir_eval(l) for l in ref_labels]
    est_labels = [_normalize_label_for_mir_eval(l) for l in est_labels]

    # Aligne les intervalles estimés sur la durée de référence, comme
    # recommandé par la documentation de mir_eval.
    est_intervals, est_labels = mir_eval.util.adjust_intervals(
        est_intervals, est_labels,
        t_min=ref_intervals.min(), t_max=ref_intervals.max(),
    )

    (intervals, ref_labels_merged, est_labels_merged) = mir_eval.util.merge_labeled_intervals(
        ref_intervals, ref_labels, est_intervals, est_labels,
    )
    durations = mir_eval.util.intervals_to_durations(intervals)

    metrics = {
        "root": mir_eval.chord.root(ref_labels_merged, est_labels_merged),
        "majmin": mir_eval.chord.majmin(ref_labels_merged, est_labels_merged),
        "sevenths": mir_eval.chord.sevenths(ref_labels_merged, est_labels_merged),
    }

    print("\n=== Résultats d'évaluation (Livre 2.0, Chapitre 2.3) ===")
    for name, scores in metrics.items():
        weighted = mir_eval.chord.weighted_accuracy(scores, durations)
        print(f"  Accuracy {name:<10s} : {weighted * 100:.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Évalue la précision harmonique d'I-Music (mir_eval).")
    parser.add_argument("--ground-truth", required=True, help="Chemin du fichier JSON de référence")
    parser.add_argument("--audio", required=True, help="Chemin du fichier audio à analyser")
    args = parser.parse_args()

    evaluate(args.ground_truth, args.audio)
