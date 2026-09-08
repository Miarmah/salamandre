"""
note.py — Utilitaire mathématique (Fréquence vers Note)
=========================================================

Traduit la physique acoustique (une fréquence en Hertz) en théorie
musicale compréhensible par un humain (ex: "A4", "C#3").

La logique repose sur le standard MIDI : la note de référence "La" (A4)
est fixée à 440 Hz et correspond au numéro MIDI 69.

    midi = 69 + 12 * log2(freq / 440.0)

Conservé tel quel depuis la version 1.0 (Livre 2.0, Chapitre 2.1) :
cette fonction n'a pas besoin d'être réécrite, seule la couche de
détection d'accords qui l'entoure est enrichie.
"""

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def freq_to_note(freq: float):
    """
    Convertit une fréquence brute (Hz) en une chaîne "Note+Octave" (ex: "A4").

    Retourne None si la fréquence est nulle ou négative, pour éviter
    une erreur mathématique lors du calcul logarithmique.
    """
    if freq is None or freq <= 0:
        return None

    midi = int(round(69 + 12 * np.log2(freq / 440.0)))
    note = NOTE_NAMES[midi % 12]
    octave = midi // 12 - 1

    return f"{note}{octave}"


def note_to_midi(note_name: str, octave: int) -> int:
    """Opération inverse : nom de note + octave -> numéro MIDI."""
    if note_name not in NOTE_NAMES:
        raise ValueError(f"Note inconnue : {note_name}")
    return NOTE_NAMES.index(note_name) + (octave + 1) * 12


# Table de correspondance anglo-saxonne <-> notation latine (Livre 2.0, 3.3)
LATIN_NOTATION = {
    "C": "Do", "C#": "Do#", "D": "Ré", "D#": "Ré#", "E": "Mi",
    "F": "Fa", "F#": "Fa#", "G": "Sol", "G#": "Sol#", "A": "La",
    "A#": "La#", "B": "Si",
}


def to_latin_notation(chord_label: str) -> str:
    """
    Traduit un label d'accord anglo-saxon (ex: 'C', 'G7', 'Am') vers la
    notation latine (ex: 'Do', 'Sol7', 'Lam'), sans toucher au suffixe
    de qualité (m, 7, maj7, sus4, ...).
    """
    if not chord_label or chord_label == "Unknown" or chord_label == "...":
        return chord_label

    # Le nom de la fondamentale peut faire 1 ou 2 caractères (ex: "C#")
    root = chord_label[:2] if len(chord_label) > 1 and chord_label[1] == "#" else chord_label[:1]
    suffix = chord_label[len(root):]

    latin_root = LATIN_NOTATION.get(root, root)
    return f"{latin_root}{suffix}"
