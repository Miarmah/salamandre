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
