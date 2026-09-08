"""
auth.py — Authentification réelle (v2.0)
============================================

Livre 2.0, Chapitre 4.4 :
  1. Hachage du mot de passe côté serveur avec bcrypt.
  2. Émission d'un access token JWT de courte durée et d'un refresh
     token de longue durée.
  3. Vérification systématique du token sur les routes protégées via
     le décorateur @jwt_required (voir app.py).


Absence de base de données (Livre 2.0, Chapitre 1 §1.3) : les comptes
sont conservés en mémoire, pour la durée de vie du processus serveur.
La fonction register()/authenticate() ne dépend d'aucun détail de
stockage particulier, ce qui permettra de brancher une base de données
relationnelle plus tard sans changer l'interface publique de ce module.
"""

import re
import threading

import bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8

_users_by_email = {}
_next_user_id = 1
_lock = threading.Lock()


class AuthError(Exception):
    """Erreur métier d'authentification (email déjà pris, identifiants
    invalides, mot de passe trop faible, etc.)."""


def _validate_email(email: str):
    if not email or not EMAIL_REGEX.match(email):
        raise AuthError("Adresse email invalide.")


def _validate_password(password: str):
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères.")


def register(username: str, email: str, password: str) -> dict:
    """
    Crée un nouveau compte utilisateur. Le mot de passe est haché avec
    bcrypt avant d'être stocké : il n'est JAMAIS conservé en clair.
    """
    global _next_user_id

    if not username or not username.strip():
        raise AuthError("Le nom d'utilisateur est requis.")

    _validate_email(email)
    _validate_password(password)

    with _lock:
        if email in _users_by_email:
            raise AuthError("Un compte existe déjà avec cette adresse email.")

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

        user = {
            "id": _next_user_id,
            "username": username.strip(),
            "email": email.lower().strip(),
            "password_hash": password_hash,
        }
        _users_by_email[user["email"]] = user
        _next_user_id += 1

    return _public_user(user)


def authenticate(email: str, password: str) -> dict:
    """Vérifie les identifiants et renvoie l'utilisateur si valides."""
    if not email or not password:
        raise AuthError("Email et mot de passe requis.")

    with _lock:
        user = _users_by_email.get(email.lower().strip())

    if user is None:
        raise AuthError("Identifiants invalides.")

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"]):
        raise AuthError("Identifiants invalides.")

    return user


def issue_tokens(user: dict) -> dict:
    """Émet un access token (courte durée) et un refresh token (longue
    durée) pour l'utilisateur donné (Livre 2.0, Chapitre 4.4 §1)."""
    identity = str(user["id"])
    return {
        "access_token": create_access_token(identity=identity),
        "refresh_token": create_refresh_token(identity=identity),
        "user": _public_user(user),
    }


def get_user_by_id(user_id: str):
    with _lock:
        for user in _users_by_email.values():
            if str(user["id"]) == str(user_id):
                return user
    return None


def _public_user(user: dict) -> dict:
    """Ne renvoie jamais le hash du mot de passe au client."""
    return {"id": user["id"], "username": user["username"], "email": user["email"]}
