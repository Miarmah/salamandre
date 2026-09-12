import logging
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import timedelta
from functools import wraps
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import auth
from flask import (
    Flask, g, render_template, request, redirect, url_for,
    session, jsonify, send_from_directory, flash,
)
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from analyse import analyse_song
from jobs import submit_job, get_job, update_progress

# ---------------------------------------------------------------------------
# Configuration générale
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "i_music.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
COVER_DIR = os.path.join(BASE_DIR, "static", "uploads", "covers")
ALLOWED_EXT = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
ALLOWED_IMG_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
# Initialisation de l'instance limiter (ajustez selon votre configuration Flask)
limiter = Limiter(key_func=get_remote_address)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,30}$")

# Nombre maximal de tentatives de connexion échouées avant blocage temporaire.
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 5 * 60

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("IMUSIC_SECRET_KEY", "i-music-dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 Mo
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(COVER_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("i-music")

# Compteur en mémoire des tentatives de connexion échouées, indexé par
# (identifiant, adresse IP). Suffisant pour une seule instance ; à
# remplacer par Redis en cas de déploiement multi-instance.
_login_attempts = {}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            dark_mode INTEGER DEFAULT 0,
            notifications INTEGER DEFAULT 1,
            plan TEXT DEFAULT 'Pro',
            failed_logins INTEGER DEFAULT 0,
            locked_until TEXT
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            is_favorite INTEGER DEFAULT 0,
            cover_filename TEXT,
            duration REAL,
            play_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            PRIMARY KEY (playlist_id, track_id),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
            FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()

    # Migration sûre pour les bases créées avant l'ajout de ces colonnes.
    existing_cols = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    for col, ddl in (
        ("failed_logins", "ALTER TABLE users ADD COLUMN failed_logins INTEGER DEFAULT 0"),
        ("locked_until", "ALTER TABLE users ADD COLUMN locked_until TEXT"),
    ):
        if col not in existing_cols:
            db.execute(ddl)

    existing_cols = {row[1] for row in db.execute("PRAGMA table_info(tracks)")}
    for col, ddl in (
        ("cover_filename", "ALTER TABLE tracks ADD COLUMN cover_filename TEXT"),
        ("duration", "ALTER TABLE tracks ADD COLUMN duration REAL"),
        ("play_count", "ALTER TABLE tracks ADD COLUMN play_count INTEGER DEFAULT 0"),
    ):
        if col not in existing_cols:
            db.execute(ddl)

    pt_cols = {row[1] for row in db.execute("PRAGMA table_info(playlist_tracks)")}
    if "position" not in pt_cols:
        db.execute("ALTER TABLE playlist_tracks ADD COLUMN position INTEGER DEFAULT 0")

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify({"ok": False, "error": "Authentification requise."}), 401
            flash("Merci de vous connecter pour accéder à cette page.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()


@app.context_processor
def inject_user():
    return {"user": current_user()}


@app.template_filter("fmt_duration")
def fmt_duration(value):
    if not value:
        return None
    value = int(value)
    return f"{value // 60}:{value % 60:02d}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMG_EXT


def validate_signup(username, email, password, confirm):
    """Retourne un message d'erreur (str) ou None si tout est valide."""
    if not username or not email or not password:
        return "Tous les champs sont obligatoires."
    if not USERNAME_RE.match(username):
        return "Le nom d'utilisateur doit contenir entre 3 et 30 caractères (lettres, chiffres, . _ -)."
    if not EMAIL_RE.match(email):
        return "Adresse email invalide."
    if len(password) < 8:
        return "Le mot de passe doit contenir au moins 8 caractères."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        return "Le mot de passe doit contenir au moins une lettre et un chiffre."
    if confirm is not None and password != confirm:
        return "Les mots de passe ne correspondent pas."
    return None


def _throttle_key():
    return f"{request.form.get('identifier', '').strip().lower()}|{request.remote_addr}"


def is_locked_out(key):
    entry = _login_attempts.get(key)
    if not entry:
        return False
    count, last_time = entry
    if count >= MAX_LOGIN_ATTEMPTS and (time.time() - last_time) < LOGIN_LOCKOUT_SECONDS:
        return True
    if (time.time() - last_time) >= LOGIN_LOCKOUT_SECONDS:
        _login_attempts.pop(key, None)
    return False


def register_failed_attempt(key):
    count, _ = _login_attempts.get(key, (0, 0))
    _login_attempts[key] = (count + 1, time.time())


def clear_attempts(key):
    _login_attempts.pop(key, None)

@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per hour")
def api_register():
    data = request.get_json(silent=True) or {}
    try:
        user = auth.register(
            username=data.get("username"),
            email=data.get("email"),
            password=data.get("password"),
        )
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(user), 201


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("20 per hour")
def api_login():
    data = request.get_json(silent=True) or {}
    try:
        user = auth.authenticate(data.get("email"), data.get("password"))
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 401

    return jsonify(auth.issue_tokens(user)), 200


@app.route("/api/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def api_refresh():
    identity = get_jwt_identity()
    new_access_token = create_access_token(identity=identity)
    return jsonify({"access_token": new_access_token}), 200


# ---------------------------------------------------------------------------
# Catalogue de chansons
# ---------------------------------------------------------------------------
@app.route("/api/songs", methods=["GET"])
def api_list_songs():
    search = request.args.get("q", "").lower().strip()
    songs = list(SONGS_BY_ID.values())

    if search:
        songs = [
            s for s in songs
            if search in s.get("title", "").lower() or search in s.get("artist", "").lower()
        ]

    return jsonify({"songs": songs, "count": len(songs)})


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.route("/api/songs/upload", methods=["POST"])
@jwt_required()
@limiter.limit("30 per hour")
def api_upload_song():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier envoyé"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nom de fichier vide"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": "Format non autorisé (mp3/wav uniquement)"}), 400

    upload_id = uuid.uuid4().hex[:10]
    safe_name = secure_filename(file.filename)
    stored_name = f"{upload_id}_{safe_name}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    file.save(file_path)

    UPLOADS_BY_ID[upload_id] = {
        "id": upload_id,
        "original_name": safe_name,
        "file_path": file_path,
        "owner_id": get_jwt_identity(),
    }

    return jsonify({"id": upload_id, "original_name": safe_name}), 201


# ---------------------------------------------------------------------------
# Analyse asynchrone (Chapitre 4.2 §"Analyse asynchrone avec suivi de progression")
# ---------------------------------------------------------------------------
SONG_ANALYSIS_CACHE = {}
TRACK_ANALYSIS_CACHE = {}
_jobs_cache_passthrough = {}

def _run_analysis_task(job_id, file_path, song_id=None):
    """Exécutée dans le pool de threads de jobs.py."""
    update_progress(job_id, 0.05, "Chargement et prétraitement du fichier")
    update_progress(job_id, 0.25, "Détection du tempo")
    update_progress(job_id, 0.5, "Détection de la tonalité (modulations)")
    update_progress(job_id, 0.7, "Reconnaissance des accords (Viterbi)")
    result = analyse_song(file_path)
    update_progress(job_id, 0.95, "Finalisation de la timeline")
    if song_id is not None and "error" not in (result or {}):
        SONG_ANALYSIS_CACHE[song_id] = result
    return result

def _catalog_song_path(song):
    """Résout le chemin disque d'une chanson du catalogue (BD_songs.json
    stocke un chemin relatif à static/, ex. 'songs/Adele.wav')."""
    return os.path.join(app.static_folder, song["file"].strip())

@app.route("/api/songs/<int:song_id>/analyse/start", methods=["GET"])
def api_start_song_analysis(song_id):
    song = SONGS_BY_ID.get(song_id)
    if song is None:
        return jsonify({"error": "Chanson non trouvée"}), 404

    file_path = song["file"].strip()
    if not os.path.exists(file_path):
        return jsonify({"error": f"Fichier de la chanson introuvable : {file_path}"}), 404

    # Analyse déjà en cache : on la ressert immédiatement sans relancer librosa.
    cached = SONG_ANALYSIS_CACHE.get(song_id)
    if cached is not None:
        job_id = f"cached-{song_id}"
        _jobs_cache_passthrough[job_id] = cached
        return jsonify({"job_id": job_id, "status": "queued", "cached": True}), 202

    file_path = _catalog_song_path(song)
    if not os.path.exists(file_path):
        return jsonify({"error": f"Fichier audio introuvable sur le serveur : static/{song['file']}"}), 404

    job_id = submit_job(_run_analysis_task, file_path, song_id=song_id)
    return jsonify({"job_id": job_id, "status": "queued"}), 202

@app.route("/api/uploads/<upload_id>/analyse/start", methods=["GET"])
@jwt_required()
def api_start_upload_analysis(upload_id):
    upload = UPLOADS_BY_ID.get(upload_id)
    if upload is None:
        return jsonify({"error": "Fichier importé introuvable"}), 404

    if str(upload["owner_id"]) != str(get_jwt_identity()):
        return jsonify({"error": "Accès refusé à ce fichier"}), 403

    job_id = submit_job(_run_analysis_task, upload["file_path"])
    return jsonify({"job_id": job_id, "status": "queued"}), 202

@app.route("/api/tracks/<int:track_id>/analyse/start", methods=["GET"])
@login_required
def api_start_track_analysis(track_id):
    db = get_db()
    track = db.execute(
        "SELECT * FROM tracks WHERE id = ? AND user_id = ?", (track_id, session["user_id"])
    ).fetchone()
    if track is None:
        return jsonify({"error": "Morceau introuvable ou accès refusé"}), 404

    cached = TRACK_ANALYSIS_CACHE.get(track_id)
    if cached is not None:
        job_id = f"cached-track-{track_id}"
        _jobs_cache_passthrough[job_id] = cached
        return jsonify({"job_id": job_id, "status": "queued", "cached": True}), 202

    file_path = os.path.join(UPLOAD_DIR, track["filename"])
    if not os.path.exists(file_path):
        return jsonify({"error": "Fichier audio introuvable sur le serveur."}), 404

    job_id = submit_job(_run_analysis_task, file_path, track_id=track_id)
    return jsonify({"job_id": job_id, "status": "queued"}), 202

@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_get_job(job_id):
    if job_id in _jobs_cache_passthrough:
        return jsonify({
            "status": "done", "progress": 1.0, "step": "Terminé (résultat en cache)",
            "result": _jobs_cache_passthrough[job_id], "error": None,
        })
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Tâche inconnue"}), 404
    return jsonify(job)

# ---------------------------------------------------------------------------
# Catalogue — page de navigation (11 chansons) + page timeline d'analyse
# ---------------------------------------------------------------------------
@app.route("/catalog")
@login_required
def catalog():
    songs = list(SONGS_BY_ID.values())
    return render_template("catalog.html", songs=songs)


@app.route("/timeline")
@login_required
def timeline_page():
    song_id = request.args.get("id", type=int)
    song = SONGS_BY_ID.get(song_id) if song_id is not None else None
    if song is None:
        flash("Chanson introuvable dans le catalogue.", "error")
        return redirect(url_for("catalog"))

    file_path = _catalog_song_path(song)
    audio_exists = os.path.exists(file_path)
    audio_src = url_for("static", filename=song["file"])
    cached_result = SONG_ANALYSIS_CACHE.get(song_id)

    return render_template(
        "timeline.html",
        item_kind="song",
        item_id=song_id,
        title=song["title"],
        subtitle=song["artist"],
        badge_label="Malagasy" if song["category"] == "malagasy" else "Étrangère",
        back_url=url_for("catalog"),
        back_label="Retour au catalogue",
        audio_src=audio_src,
        audio_exists=audio_exists,
        missing_file_msg=(
            f"Le fichier audio de ce morceau est introuvable sur le serveur "
            f"(static/{song['file']}). L'écoute et l'analyse ne fonctionneront "
            f"pas tant qu'il n'est pas ajouté à cet emplacement."
        ),
        cached_result=cached_result,
    )

@app.route("/timeline/track/<int:track_id>")
@login_required
def timeline_track_page(track_id):
    db = get_db()
    track = db.execute(
        "SELECT * FROM tracks WHERE id = ? AND user_id = ?", (track_id, session["user_id"])
    ).fetchone()
    if track is None:
        flash("Morceau introuvable dans votre bibliothèque.", "error")
        return redirect(url_for("library"))

    file_path = os.path.join(UPLOAD_DIR, track["filename"])
    audio_exists = os.path.exists(file_path)
    audio_src = url_for("uploaded_file", filename=track["filename"])
    cached_result = TRACK_ANALYSIS_CACHE.get(track_id)

    return render_template(
        "timeline.html",
        item_kind="track",
        item_id=track_id,
        title=track["title"],
        subtitle="Importé dans votre bibliothèque",
        badge_label=None,
        back_url=url_for("library"),
        back_label="Retour à la bibliothèque",
        audio_src=audio_src,
        audio_exists=audio_exists,
        missing_file_msg="Le fichier audio de ce morceau est introuvable sur le serveur. "
                          "Réimportez-le depuis la bibliothèque.",
        cached_result=cached_result,
    )

# ---------------------------------------------------------------------------
# Onboarding / Auth routes
# ---------------------------------------------------------------------------
@app.route("/")
def onboarding():
    if "user_id" in session:
        return redirect(url_for("catalog"))
    return render_template("onboarding.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password")

        error = validate_signup(username, email, password, confirm)

        db = get_db()
        if error is None:
            try:
                existing = db.execute(
                    "SELECT id FROM users WHERE username = ? OR email = ?",
                    (username, email),
                ).fetchone()
                if existing:
                    error = "Ce nom d'utilisateur ou cet email est déjà utilisé."
            except sqlite3.Error:
                logger.exception("Erreur DB lors de la vérification d'unicité au signup")
                error = "Une erreur est survenue, merci de réessayer."

        if error:
            return render_template(
                "signup.html", error=error, username=username, email=email
            ), 400

        try:
            db.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, generate_password_hash(password)),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return render_template(
                "signup.html",
                error="Ce nom d'utilisateur ou cet email est déjà utilisé.",
                username=username, email=email,
            ), 400
        except sqlite3.Error:
            db.rollback()
            logger.exception("Erreur DB lors de la création du compte")
            return render_template(
                "signup.html",
                error="Impossible de créer le compte pour le moment.",
                username=username, email=email,
            ), 500

        return redirect(url_for("login", created=1))

    return render_template("signup.html", error=None, username="", email="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"
        throttle_key = _throttle_key()

        if not identifier or not password:
            return render_template("login.html", error="Merci de renseigner vos identifiants."), 400

        if is_locked_out(throttle_key):
            return render_template(
                "login.html",
                error="Trop de tentatives échouées. Réessayez dans quelques minutes.",
            ), 429

        try:
            db = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE email = ? OR username = ?",
                (identifier, identifier),
            ).fetchone()
        except sqlite3.Error:
            logger.exception("Erreur DB lors de la connexion")
            return render_template("login.html", error="Une erreur est survenue, merci de réessayer."), 500

        # Message volontairement générique pour ne pas révéler si le compte existe.
        if user is None or not check_password_hash(user["password_hash"], password):
            register_failed_attempt(throttle_key)
            return render_template("login.html", error="Email/utilisateur ou mot de passe incorrect."), 401

        clear_attempts(throttle_key)
        session.clear()
        session["user_id"] = user["id"]
        session.permanent = remember

        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("catalog"))

    just_created = request.args.get("created")
    return render_template("login.html", error=None, just_created=just_created)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("onboarding"))

# ---------------------------------------------------------------------------
# Chargement du catalogue de chansons (BD_songs.json)
# ---------------------------------------------------------------------------
try:
    with open(os.path.join(BASE_DIR, "BD_songs.json"), "r", encoding="utf-8") as f:
        _catalog_data = json.load(f)
except FileNotFoundError:
    print("Fichier BD_songs.json non trouvé. Assurez-vous qu'il existe et est au bon endroit.")
    _catalog_data = {"songs": []}

SONGS_BY_ID = {song["id"]: song for song in _catalog_data.get("songs", [])}

# Fichiers importés par les utilisateurs, conservés en mémoire pour la
# session en cours (aucune base de données — voir en-tête de ce fichier).
UPLOADS_BY_ID = {}

# Playlists / favoris en mémoire, indexés par identifiant utilisateur.
PLAYLISTS_BY_USER = {}
FAVORITES_BY_USER = {}

# ---------------------------------------------------------------------------
# Library / tracks
# ---------------------------------------------------------------------------
SORT_COLUMNS = {
    "title": "title COLLATE NOCASE",
    "date": "created_at",
    "duration": "duration IS NULL, duration",
}


def tracks_to_json(tracks):
    return [
        {
            "id": t["id"],
            "title": t["title"],
            "filename": t["filename"],
            "cover": t["cover_filename"],
        }
        for t in tracks
    ]


@app.route("/library")
@login_required
def library():
    show_favorites = request.args.get("fav") == "1"
    sort = request.args.get("sort", "date")
    direction = request.args.get("dir", "desc")
    if sort not in SORT_COLUMNS:
        sort = "date"
    if direction not in ("asc", "desc"):
        direction = "desc"

    if sort == "duration":
        order_sql = f"duration IS NULL, duration {direction.upper()}"
    else:
        order_sql = f"{SORT_COLUMNS[sort]} {direction.upper()}"

    db = get_db()
    where = "user_id = ?" + (" AND is_favorite = 1" if show_favorites else "")
    tracks = db.execute(
        f"SELECT * FROM tracks WHERE {where} ORDER BY {order_sql}",
        (session["user_id"],),
    ).fetchall()
    return render_template(
        "library.html",
        tracks=tracks,
        show_favorites=show_favorites,
        sort=sort,
        direction=direction,
        tracks_json=tracks_to_json(tracks),
    )


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("audio")

    if not file or not file.filename:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("library"))

    if not allowed_file(file.filename):
        flash(f"Format non pris en charge. Formats acceptés : {', '.join(sorted(ALLOWED_EXT))}.", "error")
        return redirect(url_for("library"))

    ext = file.filename.rsplit(".", 1)[1].lower()
    original_name = os.path.basename(file.filename)
    title = os.path.splitext(original_name)[0].strip()
    stored_name = f"{uuid.uuid4().hex}.{ext}"

    try:
        file.save(os.path.join(UPLOAD_DIR, stored_name))
        db = get_db()
        db.execute(
            "INSERT INTO tracks (user_id, title, filename) VALUES (?, ?, ?)",
            (session["user_id"], title or "Piste importée", stored_name),
        )
        db.commit()
    except sqlite3.Error:
        logger.exception("Erreur DB lors de l'ajout d'une piste")
        stray_path = os.path.join(UPLOAD_DIR, stored_name)
        if os.path.exists(stray_path):
            os.remove(stray_path)
        flash("Impossible d'enregistrer ce morceau, merci de réessayer.", "error")
    except OSError:
        logger.exception("Erreur disque lors de l'upload")
        flash("Erreur lors de l'enregistrement du fichier.", "error")
    else:
        flash("Morceau ajouté avec succès.", "success")

    return redirect(url_for("library"))


@app.route("/track/<int:track_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(track_id):
    db = get_db()
    db.execute(
        "UPDATE tracks SET is_favorite = 1 - is_favorite WHERE id = ? AND user_id = ?",
        (track_id, session["user_id"]),
    )
    db.commit()
    return redirect(request.referrer or url_for("library"))


@app.route("/track/<int:track_id>/rename", methods=["POST"])
@login_required
def rename_track(track_id):
    new_title = request.form.get("title", "").strip()
    if new_title:
        db = get_db()
        db.execute(
            "UPDATE tracks SET title = ? WHERE id = ? AND user_id = ?",
            (new_title, track_id, session["user_id"]),
        )
        db.commit()
    else:
        flash("Le titre ne peut pas être vide.", "error")
    return redirect(request.referrer or url_for("library"))


@app.route("/track/<int:track_id>/cover", methods=["POST"])
@login_required
def upload_cover(track_id):
    db = get_db()
    track = db.execute(
        "SELECT * FROM tracks WHERE id = ? AND user_id = ?", (track_id, session["user_id"])
    ).fetchone()
    if not track:
        flash("Piste introuvable.", "error")
        return redirect(url_for("library"))

    file = request.files.get("cover")
    if not file or not file.filename:
        flash("Aucune image sélectionnée.", "error")
        return redirect(request.referrer or url_for("library"))

    if not allowed_image(file.filename):
        flash(f"Format d'image non pris en charge. Formats acceptés : {', '.join(sorted(ALLOWED_IMG_EXT))}.", "error")
        return redirect(request.referrer or url_for("library"))

    ext = file.filename.rsplit(".", 1)[1].lower()
    old_cover = track["cover_filename"]
    stored_name = f"{uuid.uuid4().hex}.{ext}"

    try:
        file.save(os.path.join(COVER_DIR, stored_name))
        db.execute(
            "UPDATE tracks SET cover_filename = ? WHERE id = ?", (stored_name, track_id)
        )
        db.commit()
        if old_cover:
            old_path = os.path.join(COVER_DIR, old_cover)
            if os.path.exists(old_path):
                os.remove(old_path)
    except (sqlite3.Error, OSError):
        logger.exception("Erreur lors de l'upload de la pochette")
        flash("Impossible d'enregistrer la pochette.", "error")

    return redirect(request.referrer or url_for("library"))


@app.route("/track/<int:track_id>/duration", methods=["POST"])
@login_required
def save_duration(track_id):
    duration = request.form.get("duration", type=float)
    if duration and duration > 0:
        db = get_db()
        db.execute(
            "UPDATE tracks SET duration = ? WHERE id = ? AND user_id = ?",
            (duration, track_id, session["user_id"]),
        )
        db.commit()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Durée invalide."}), 400


@app.route("/track/<int:track_id>/play", methods=["POST"])
@login_required
def register_play(track_id):
    db = get_db()
    db.execute(
        "UPDATE tracks SET play_count = play_count + 1 WHERE id = ? AND user_id = ?",
        (track_id, session["user_id"]),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/covers/<path:filename>")
@login_required
def cover_file(filename):
    return send_from_directory(COVER_DIR, filename)


@app.route("/track/<int:track_id>/delete", methods=["POST"])
@login_required
def delete_track(track_id):
    db = get_db()
    track = db.execute(
        "SELECT * FROM tracks WHERE id = ? AND user_id = ?", (track_id, session["user_id"])
    ).fetchone()
    if track:
        path = os.path.join(UPLOAD_DIR, track["filename"])
        if os.path.exists(path):
            os.remove(path)
        if track["cover_filename"]:
            cover_path = os.path.join(COVER_DIR, track["cover_filename"])
            if os.path.exists(cover_path):
                os.remove(cover_path)
        db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        db.commit()
        flash("Piste supprimée.", "success")
    else:
        flash("Piste introuvable.", "error")
    return redirect(request.referrer or url_for("library"))


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------------------------
# Search (simple JSON API used by the search page)
# ---------------------------------------------------------------------------
@app.route("/search")
@login_required
def search_page():
    return render_template("search.html")


@app.route("/api/search")
@login_required
def api_search():
    q = request.args.get("q", "").strip()
    db = get_db()
    if q:
        rows = db.execute(
            "SELECT * FROM tracks WHERE user_id = ? AND title LIKE ? ORDER BY created_at DESC",
            (session["user_id"], f"%{q}%"),
        ).fetchall()
    else:
        rows = []
    return jsonify([
        {
            "id": r["id"], "title": r["title"], "filename": r["filename"],
            "is_favorite": r["is_favorite"], "cover": r["cover_filename"],
        }
        for r in rows
    ])


# ---------------------------------------------------------------------------
# Playlists
# ---------------------------------------------------------------------------
@app.route("/api/playlists")
@login_required
def api_playlists():
    db = get_db()
    rows = db.execute(
        "SELECT id, name FROM playlists WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])


@app.route("/api/playlists/<int:playlist_id>/add/<int:track_id>", methods=["POST"])
@login_required
def api_add_to_playlist(playlist_id, track_id):
    db = get_db()
    owns = db.execute(
        "SELECT 1 FROM playlists WHERE id = ? AND user_id = ?",
        (playlist_id, session["user_id"]),
    ).fetchone()
    if not owns:
        return jsonify({"ok": False, "error": "Playlist introuvable."}), 403
    next_pos = db.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_tracks WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()[0]
    db.execute(
        "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
        (playlist_id, track_id, next_pos),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/playlists")
@login_required
def playlists():
    db = get_db()
    rows = db.execute(
        """
        SELECT p.*, COUNT(pt.track_id) AS track_count
        FROM playlists p
        LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id
        WHERE p.user_id = ?
        GROUP BY p.id
        ORDER BY p.id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template("playlists.html", playlists=rows)


@app.route("/playlists/create", methods=["POST"])
@login_required
def create_playlist():
    name = request.form.get("name", "").strip()
    if name:
        db = get_db()
        db.execute(
            "INSERT INTO playlists (user_id, name) VALUES (?, ?)",
            (session["user_id"], name),
        )
        db.commit()
        flash("Playlist créée.", "success")
    else:
        flash("Le nom de la playlist est requis.", "error")
    return redirect(url_for("playlists"))


@app.route("/playlists/<int:playlist_id>")
@login_required
def playlist_detail(playlist_id):
    db = get_db()
    playlist = db.execute(
        "SELECT * FROM playlists WHERE id = ? AND user_id = ?",
        (playlist_id, session["user_id"]),
    ).fetchone()
    if playlist is None:
        flash("Playlist introuvable.", "error")
        return redirect(url_for("playlists"))

    tracks_in = db.execute(
        """
        SELECT t.* FROM tracks t
        JOIN playlist_tracks pt ON pt.track_id = t.id
        WHERE pt.playlist_id = ?
        ORDER BY pt.position ASC, t.created_at DESC
        """,
        (playlist_id,),
    ).fetchall()

    all_tracks = db.execute(
        "SELECT * FROM tracks WHERE user_id = ? ORDER BY created_at DESC",
        (session["user_id"],),
    ).fetchall()
    in_ids = {t["id"] for t in tracks_in}
    available = [t for t in all_tracks if t["id"] not in in_ids]

    return render_template(
        "playlist_detail.html", playlist=playlist, tracks=tracks_in, available=available,
        tracks_json=tracks_to_json(tracks_in),
    )


@app.route("/playlists/<int:playlist_id>/reorder", methods=["POST"])
@login_required
def reorder_playlist(playlist_id):
    db = get_db()
    owns = db.execute(
        "SELECT 1 FROM playlists WHERE id = ? AND user_id = ?",
        (playlist_id, session["user_id"]),
    ).fetchone()
    if not owns:
        return jsonify({"ok": False, "error": "Playlist introuvable."}), 403

    order = request.get_json(silent=True) or {}
    track_ids = order.get("order", [])
    if not isinstance(track_ids, list):
        return jsonify({"ok": False, "error": "Format invalide."}), 400

    for position, track_id in enumerate(track_ids):
        db.execute(
            "UPDATE playlist_tracks SET position = ? WHERE playlist_id = ? AND track_id = ?",
            (position, playlist_id, track_id),
        )
    db.commit()
    return jsonify({"ok": True})


@app.route("/playlists/<int:playlist_id>/add/<int:track_id>", methods=["POST"])
@login_required
def add_to_playlist(playlist_id, track_id):
    db = get_db()
    owns = db.execute(
        "SELECT 1 FROM playlists WHERE id = ? AND user_id = ?",
        (playlist_id, session["user_id"]),
    ).fetchone()
    if owns:
        next_pos = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_tracks WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
            (playlist_id, track_id, next_pos),
        )
        db.commit()
    else:
        flash("Playlist introuvable.", "error")
    return redirect(url_for("playlist_detail", playlist_id=playlist_id))


@app.route("/playlists/<int:playlist_id>/remove/<int:track_id>", methods=["POST"])
@login_required
def remove_from_playlist(playlist_id, track_id):
    db = get_db()
    db.execute(
        "DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?",
        (playlist_id, track_id),
    )
    db.commit()
    return redirect(url_for("playlist_detail", playlist_id=playlist_id))


@app.route("/playlists/<int:playlist_id>/delete", methods=["POST"])
@login_required
def delete_playlist(playlist_id):
    db = get_db()
    db.execute(
        "DELETE FROM playlists WHERE id = ? AND user_id = ?",
        (playlist_id, session["user_id"]),
    )
    db.commit()
    flash("Playlist supprimée.", "success")
    return redirect(url_for("playlists"))

# ---------------------------------------------------------------------------
# Playlists (session en cours, sans persistance)
# ---------------------------------------------------------------------------
@app.route("/api/playlists", methods=["GET"])
@jwt_required()
def api_list_playlists():
    user_id = get_jwt_identity()
    return jsonify({"playlists": PLAYLISTS_BY_USER.get(user_id, [])})


@app.route("/api/playlists", methods=["POST"])
@jwt_required()
def api_create_playlist():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "Le nom de la playlist est requis"}), 400

    playlist = {"id": uuid.uuid4().hex[:8], "name": name, "song_ids": []}
    PLAYLISTS_BY_USER.setdefault(user_id, []).append(playlist)
    return jsonify(playlist), 201


# ---------------------------------------------------------------------------
# Favoris (session en cours, sans persistance)
# ---------------------------------------------------------------------------
@app.route("/api/favorites", methods=["GET"])
@jwt_required()
def api_list_favorites():
    user_id = get_jwt_identity()
    return jsonify({"favorites": list(FAVORITES_BY_USER.get(user_id, set()))})


@app.route("/api/favorites", methods=["POST"])
@jwt_required()
def api_add_favorite():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    song_id = data.get("song_id")

    if song_id is None:
        return jsonify({"error": "song_id requis"}), 400

    FAVORITES_BY_USER.setdefault(user_id, set()).add(str(song_id))
    return jsonify({"favorites": list(FAVORITES_BY_USER[user_id])}), 201


@app.route("/api/favorites/<song_id>", methods=["DELETE"])
@jwt_required()
def api_remove_favorite(song_id):
    user_id = get_jwt_identity()
    FAVORITES_BY_USER.get(user_id, set()).discard(str(song_id))
    return jsonify({"favorites": list(FAVORITES_BY_USER.get(user_id, set()))})

# ---------------------------------------------------------------------------
# Statistiques
# ---------------------------------------------------------------------------
@app.route("/stats/export.csv")
@login_required
def export_stats_csv():
    import csv
    import io
    from flask import Response

    db = get_db()
    rows = db.execute(
        "SELECT title, play_count, duration, is_favorite, created_at FROM tracks WHERE user_id = ? ORDER BY play_count DESC",
        (session["user_id"],),
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Titre", "Écoutes", "Durée (secondes)", "Favori", "Ajouté le"])
    for r in rows:
        writer.writerow([r["title"], r["play_count"], r["duration"] or "", "Oui" if r["is_favorite"] else "Non", r["created_at"]])

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=i-music-statistiques.csv"},
    )


@app.route("/stats")
@login_required
def stats():
    db = get_db()
    top_tracks = db.execute(
        "SELECT * FROM tracks WHERE user_id = ? AND play_count > 0 ORDER BY play_count DESC LIMIT 10",
        (session["user_id"],),
    ).fetchall()
    totals = db.execute(
        """
        SELECT COUNT(*) AS track_count,
               COALESCE(SUM(play_count), 0) AS total_plays,
               COALESCE(SUM(duration), 0) AS total_duration
        FROM tracks WHERE user_id = ?
        """,
        (session["user_id"],),
    ).fetchone()
    playlist_count = db.execute(
        "SELECT COUNT(*) FROM playlists WHERE user_id = ?", (session["user_id"],)
    ).fetchone()[0]
    max_plays = top_tracks[0]["play_count"] if top_tracks else 0
    return render_template(
        "stats.html", top_tracks=top_tracks, totals=totals,
        playlist_count=playlist_count, max_plays=max_plays,
    )


# ---------------------------------------------------------------------------
# Paramètres du compte
# ---------------------------------------------------------------------------
ALLOWED_TOGGLE_FIELDS = {"dark_mode", "notifications"}


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/settings/toggle", methods=["POST"])
@login_required
def settings_toggle():
    field = request.form.get("field")
    if field in ALLOWED_TOGGLE_FIELDS:
        db = get_db()
        db.execute(
            f"UPDATE users SET {field} = 1 - {field} WHERE id = ?",
            (session["user_id"],),
        )
        db.commit()
    else:
        flash("Paramètre inconnu.", "error")
    return redirect(url_for("settings"))


@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    if not user or not check_password_hash(user["password_hash"], current_password):
        flash("Mot de passe actuel incorrect.", "error")
        return redirect(url_for("settings"))

    if len(new_password) < 8 or not re.search(r"[A-Za-z]", new_password) or not re.search(r"[0-9]", new_password):
        flash("Le nouveau mot de passe doit contenir au moins 8 caractères, une lettre et un chiffre.", "error")
        return redirect(url_for("settings"))

    if new_password != confirm_password:
        flash("Les mots de passe ne correspondent pas.", "error")
        return redirect(url_for("settings"))

    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), session["user_id"]),
    )
    db.commit()
    flash("Mot de passe mis à jour.", "success")
    return redirect(url_for("settings"))


# ---------------------------------------------------------------------------
# Gestion d'erreurs globale
# ---------------------------------------------------------------------------
@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message="Requête invalide."), 400


@app.errorhandler(401)
def unauthorized(e):
    return render_template("error.html", code=401, message="Authentification requise."), 401


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Accès refusé."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page introuvable."), 404


@app.errorhandler(429)
def too_many_requests(e):
    return render_template("error.html", code=429, message="Trop de tentatives, réessayez plus tard."), 429


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(e):
    flash("Le fichier envoyé est trop volumineux (50 Mo maximum).", "error")
    return redirect(request.referrer or url_for("library")), 413


@app.errorhandler(500)
def server_error(e):
    logger.exception("Erreur serveur non gérée")
    return render_template("error.html", code=500, message="Une erreur interne est survenue."), 500


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    # Laisse Flask/Werkzeug gérer normalement ses propres exceptions HTTP
    # (404, 405, etc.) via les handlers dédiés ci-dessus.
    if isinstance(e, HTTPException):
        return e
    logger.exception("Exception non interceptée")
    return render_template("error.html", code=500, message="Une erreur inattendue est survenue."), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)