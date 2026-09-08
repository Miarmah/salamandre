## Installation

```bash
cd i-music
python3 -m venv venv
source venv/bin/activate      # sur Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Lancement

```bash
python3 app.py
```

Puis ouvre **http://127.0.0.1:5000** dans ton navigateur.

La base de données SQLite (`i_music.db`) et le dossier `static/uploads/` sont créés automatiquement au premier lancement.

## Structure du projet

```
i-music/
  app.py                # backend Flask (routes, base de données, logique métier)
  requirements.txt
  templates/             # pages HTML (Jinja2)
  static/css/style.css   # design (couleurs/typo reprises de l'app d'origine)
  static/js/app.js       # lecteur audio + visualiseur + interactions
  static/uploads/        # fichiers audio importés par les utilisateurs
```

## Notes 
- Chaque compte a ses propres morceaux et playlists (isolation par `user_id`).
- Le visualiseur utilise l'API Web Audio (`AnalyserNode`) branchée sur le vrai fichier audio en cours de lecture

i-music/
│
├── static/                      # Fichiers statiques web (Front-End)
│   ├── css/
│   │   └── style.css            # Styles et charte graphique
│   ├── js/
│   │   └── app.js               # Logique JS (lecteur audio, visualiseur, requêtes API)[cite: 1]
│   └── uploads/                 # Fichiers audio importés par les utilisateurs[cite: 1]
│
├── templates/                   # Vues HTML Jinja2 (Front-End)[cite: 1]
│   └── index.html               # Page principale de l'application
│
├── app.py                       # Point d'entrée principal Flask & enregistrement des routes/Blueprints[cite: 1]
├── auth.py                      # Gestion de l'authentification (Register, Login, JWT, Sessions)
├── jobs.py                      # Gestion des tâches d'analyse asynchrones (Jobs API)
│
├── analyse.py                   # Orchestrateur/pipeline principal pour l'analyse audio
├── separation.py                # Traitement audio : séparation des sources/stems (Demucs/Spleeter)
├── chords.py                    # Traitement audio : détection des accords
├── tonalite.py                  # Traitement audio : détection de la tonalité/clé musicale
├── note.py                      # Traitement audio : transcription ou extraction des notes
├── timeline.py                  # Génération de la chronologie/timeline d'analyse
│
├── BD_songs.json                # Catalogue ou métadonnées JSON des chansons
├── i_music.db                   # Base de données SQLite locale[cite: 1]
├── swagger.yaml                 # Spécification & contrat OpenAPI 3.0 de l'API REST
├── README.md                    # Documentation et instructions du projet[cite: 1]
├── requirements.txt             # Dépendances Python du projet[cite: 1]
│
└── venv/                        # Environnement virtuel Python (bin, include, lib, pyvenv.cfg)[cite: 1]
