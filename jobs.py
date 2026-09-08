"""
jobs.py — File d'attente asynchrone + suivi de progression
===============================================================

Livre 2.0, Chapitre 4.2 §"Analyse asynchrone avec suivi de progression" :

  1. Le Front-End envoie le fichier (ou l'identifiant de chanson) et
     reçoit immédiatement un job_id avec le statut 'queued'.
  2. Le Back-End traite l'analyse en tâche de fond (ThreadPoolExecutor
     pour un projet de cette envergure — Celery/Redis en alternative
     plus lourde si le besoin de mise à l'échelle se confirme).
  3. Le Front-End interroge périodiquement GET /api/jobs/<job_id>.

Aucune base de données n'étant disponible dans cette itération (voir
Livre 2.0, Chapitre 1 §1.3 et Chapitre 4.6), l'état des tâches est
conservé en mémoire, pour la durée de vie du processus serveur. Ce
choix est assumé : il suffit à démontrer et tester le mécanisme
asynchrone, tout en restant remplaçable par un stockage persistant
(Redis, base relationnelle) sans changer l'interface publique de ce
module (submit_job / get_job).
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

MAX_WORKERS = 4

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_jobs = {}
_jobs_lock = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _set_job(job_id, **fields):
    with _jobs_lock:
        _jobs[job_id].update(fields)
        _jobs[job_id]["updated_at"] = _now_iso()


def update_progress(job_id: str, progress: float, step: str):
    """
    À appeler depuis l'intérieur d'une tâche d'analyse pour signaler sa
    progression au Front-End (ex: 0.32, "Détection du tempo").
    """
    _set_job(job_id, progress=round(float(progress), 2), step=step)


def _run_job(job_id, func, args, kwargs):
    _set_job(job_id, status="processing", progress=0.0, step="Démarrage de l'analyse")
    try:
        result = func(job_id, *args, **kwargs)
        _set_job(job_id, status="done", progress=1.0, step="Terminé", result=result)
    except Exception as exc:  # pragma: no cover - dépend du contenu analysé
        _set_job(job_id, status="failed", error=str(exc))


def submit_job(func, *args, **kwargs) -> str:
    """
    Enregistre une nouvelle tâche d'analyse et la programme sur le pool
    de threads. `func` doit accepter `job_id` en premier argument, afin
    de pouvoir appeler update_progress(job_id, ...) pendant son exécution.

    Retourne l'identifiant de tâche (job_id) à renvoyer immédiatement au
    Front-End avec le statut 'queued'.
    """
    job_id = uuid.uuid4().hex[:12]

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress": 0.0,
            "step": "En attente",
            "result": None,
            "error": None,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }

    _executor.submit(_run_job, job_id, func, args, kwargs)
    return job_id


def get_job(job_id: str):
    """Retourne l'état courant d'une tâche, ou None si elle est inconnue."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
