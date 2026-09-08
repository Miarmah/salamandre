"""
separation.py — Intégration optionnelle de Demucs / Spleeter
=================================================================

Livre 2.0, Chapitre 2.2 §4 :
  « En isolant la piste "other" (accompagnement harmonique, hors voix
    et batterie), le chromagramme calculé sur cette piste est nettement
    moins bruité par la voix lead ou les fréquences percussives, ce qui
    améliore directement la précision de detect_chord(). »

Livre 2.0, Chapitre 3.2 §16.3 :
  la séparation de sources reste une amélioration OPTIONNELLE,
  activable via une variable de configuration, car gourmande en
  ressources de calcul (CPU/GPU) et en dépendances lourdes.

Ce module ne plante jamais si Demucs/Spleeter ne sont pas installés :
il retombe alors silencieusement sur le fichier audio d'origine
(comportement de repli explicitement recommandé dans le livre).
"""

import os
import shutil
import subprocess
import tempfile

# Activable via variable d'environnement, désactivé par défaut afin de ne
# pas alourdir l'installation sur les postes de développement (Livre 2.0,
# Chapitre 3.2 §16.3 "Recommandation de configuration par environnement").
ENABLE_SOURCE_SEPARATION = os.environ.get("ENABLE_SOURCE_SEPARATION", "false").lower() == "true"
SEPARATION_ENGINE = os.environ.get("SEPARATION_ENGINE", "demucs")  # "demucs" ou "spleeter"


def _is_tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def separate_other_stem(audio_path: str) -> str:
    """
    Tente d'isoler la piste harmonique ("other" = accompagnement, hors
    voix et batterie) d'un fichier audio, afin d'améliorer la précision
    de la détection d'accords.

    Retourne le chemin du fichier isolé si la séparation a réussi, ou le
    chemin d'origine (fallback) si la séparation est désactivée, ou si
    Demucs/Spleeter ne sont pas disponibles sur la machine.
    """
    if not ENABLE_SOURCE_SEPARATION:
        return audio_path

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Fichier introuvable : {audio_path}")

    try:
        if SEPARATION_ENGINE == "demucs":
            return _separate_with_demucs(audio_path)
        elif SEPARATION_ENGINE == "spleeter":
            return _separate_with_spleeter(audio_path)
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        print(f"[separation.py] Séparation impossible ({exc}), "
              f"utilisation du fichier original en repli (fallback).")

    return audio_path


def _separate_with_demucs(audio_path: str) -> str:
    """Isole la piste 'other' via Demucs (modèle Hybrid Transformer)."""
    if not _is_tool_available("demucs"):
        raise RuntimeError("Demucs n'est pas installé sur cette machine.")

    output_dir = tempfile.mkdtemp(prefix="imusic_demucs_")
    subprocess.run(
        ["demucs", "--two-stems=other", "-o", output_dir, audio_path],
        check=True,
        capture_output=True,
    )

    basename = os.path.splitext(os.path.basename(audio_path))[0]
    # Demucs range ses résultats sous <output_dir>/<modele>/<basename>/other.wav
    for root, _dirs, files in os.walk(output_dir):
        if "other.wav" in files and basename in root:
            return os.path.join(root, "other.wav")

    raise RuntimeError("Piste 'other' introuvable dans la sortie de Demucs.")


def _separate_with_spleeter(audio_path: str) -> str:
    """Isole la piste d'accompagnement via Spleeter (2 pistes : vocals/accompaniment)."""
    if not _is_tool_available("spleeter"):
        raise RuntimeError("Spleeter n'est pas installé sur cette machine.")

    output_dir = tempfile.mkdtemp(prefix="imusic_spleeter_")
    subprocess.run(
        ["spleeter", "separate", "-p", "spleeter:2stems", "-o", output_dir, audio_path],
        check=True,
        capture_output=True,
    )

    basename = os.path.splitext(os.path.basename(audio_path))[0]
    candidate = os.path.join(output_dir, basename, "accompaniment.wav")
    if os.path.exists(candidate):
        return candidate

    raise RuntimeError("Piste 'accompaniment' introuvable dans la sortie de Spleeter.")
