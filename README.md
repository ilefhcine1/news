# Veille quotidienne IA · Tech · Cyber

Chaque matin vers 7h, un email en français avec les 5 actus les plus importantes
des dernières 24 h en IA, tech/IT et cybersécurité (attaques, failles, IT en général).

Pour chaque actu :
- titre ;
- résumé de 2-3 phrases, rédigé avec ses propres mots ;
- « Pourquoi c'est important » pour une équipe IT d'entreprise de conseil ;
- source (avec lien) et les autres médias qui l'ont couverte ;
- article de recherche, **uniquement** s'il est réellement cité dans l'article.

**Aucune API d'IA externe** : le modèle (`qwen3.5:4b`) tourne en local avec
[Ollama](https://ollama.com). Seul l'email sort du PC.

## Fonctionnement

1. Lecture d'une vingtaine de flux RSS (liste `FEEDS` dans `news_digest.py`).
2. Regroupement des articles qui parlent du même sujet.
3. Le modèle choisit les 5 sujets les plus importants parmi `MAX_CANDIDATES`.
   S'il échoue ou en renvoie moins de 5, on complète avec les sujets les plus couverts.
4. Pour chaque sujet, le script lit l'article et le modèle rédige titre, résumé et
   « pourquoi c'est important ». Un lien de recherche n'est affiché que s'il figure
   dans l'article lui-même (jamais inventé).
5. Envoi de l'email HTML. Les liens envoyés sont mémorisés dans `seen_urls.json`
   pour ne jamais envoyer deux fois la même actu.

## Installation (Windows)

```powershell
# 1. Ollama et le modèle (~3,3 Go)
winget install Ollama.Ollama
ollama pull qwen3.5:4b

# 2. Environnement Python (3.11+)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configuration
copy .env.example .env      # puis remplir la partie email

# 4. Essai sans envoi (écrit digest.html, ne touche pas à l'historique)
$env:DRY_RUN=1; .\.venv\Scripts\python.exe news_digest.py; Remove-Item Env:DRY_RUN

# 5. Planification quotidienne à 06:15
powershell -ExecutionPolicy Bypass -File setup_task.ps1
```

La tâche planifiée réveille le PC s'il est en veille (pas s'il est éteint),
s'exécute dès que possible si 06:15 a été manqué, et fonctionne sur batterie.
Sur un portable sans GPU dédié, une exécution prend plusieurs minutes.

Les logs sont écrits dans `digest.log`.

## Réglages (`.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `LLM_MODEL` | `qwen3.5:4b` | modèle Ollama |
| `NUM_CTX` | `6144` | taille du contexte ; plus grand = plus de RAM (trop petit : candidats réduits automatiquement) |
| `KEEP_ALIVE` | `0` | `0` = modèle déchargé après chaque appel (≈1 Go de RAM en moins) |
| `MAX_CANDIDATES` | `60` | sujets montrés au modèle pour la sélection |
| `THINK` | `0` | mode « réflexion » de qwen3.5 (très lent sur CPU) |
| `NUM_STORIES` | `5` | nombre d'actus dans l'email |
| `LOOKBACK_HOURS` | `26` | fenêtre de collecte |
| `AUDIENCE` | équipe IT de conseil | public visé par les prompts |
| `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | – | envoi de l'email (Gmail : mot de passe d'application) |
| `SMTP_HOST`, `SMTP_PORT` | `smtp.gmail.com`, `465` | serveur SMTP (SSL) |
| `DRY_RUN` | `0` | `1` = écrit `digest.html` sans envoyer ni mémoriser |
