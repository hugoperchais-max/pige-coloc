# Bot pige appart — Strasbourg

Bot qui surveille les annonces de **location d'appartements** à Strasbourg et
t'envoie une alerte **Telegram** dès qu'une nouvelle correspond à tes critères.
Tourne tout seul, gratuitement, sur **GitHub Actions** (toutes les 15 min) — ton
PC peut être éteint.

> Cas d'usage : tu cherches un **appartement entier à louer en coloc à deux**
> (T3+), de préférence non meublé. La source principale est **PAP** (de
> particulier à particulier, **zéro frais d'agence**).

## Sources
| Source | Statut | Pourquoi |
|---|---|---|
| **PAP** (`pap.py`) | ✅ active | Particuliers, sans frais. Marche partout. |
| **LeBonCoin** (`leboncoin.py`) | ✅ active | Gros volume, particuliers + agences. ⚠️ DataDome (voir ci-dessous). |
| **Bien'ici** (`bienici.py`) | ✅ active | **Agences** (Citya, Century 21, Foncia…), API JSON. Marche partout. |

Sites testés et **écartés** : SeLoger, Logic-Immo, Ouest-France-Immo, Avendrealouer,
Superimmo (bloqués DataDome) ; Vivastreet, Topannonces, EntreParticuliers
(redondants avec LeBonCoin) ; Studapart, Immojeune, CROUS (login / annuaire statique).

### Ajouter une source
1. Crée `masource.py` exposant `fetch_all_listings(query) -> list[Listing]` et `SOURCE`
   (utilise `httpclient.make_session()` + renvoie des `models.Listing`).
2. Ajoute-la à `SOURCE_MODULES` dans `main.py`, puis référence-la dans `sources`
   d'un profil (`config.json`). Rien d'autre à toucher.

## Architecture (fichiers)
| Fichier | Rôle |
|---|---|
| `models.py` | Schéma typé `Listing` + logique métier (matching, empreinte de dédup) |
| `httpclient.py` | Session HTTP partagée (impersonation TLS) + retries |
| `pap.py` / `leboncoin.py` / `bienici.py` | Sources : récupèrent et normalisent en `Listing` |
| `main.py` | Orchestration : fetch parallèle → filtre → dédup → envoi |
| `notify.py` | Envoi Telegram robuste (429, retries) |
| `test_pige.py` | Tests sans réseau |

Chaque profil de `config.json` liste ses sources dans `sources` (clé = nom du
module, valeur = requête : chemin PAP, ou identifiant lieu LeBonCoin type
`Strasbourg_67000`). Le registre des modules est dans `main.py` (`SOURCE_MODULES`).

> ⚠️ **LeBonCoin + GitHub Actions** : LeBonCoin (DataDome) passe depuis une IP
> résidentielle (ton PC). Les serveurs GitHub utilisent des IP de datacenter que
> DataDome bloque plus facilement → LeBonCoin **peut renvoyer 0 depuis le cron**.
> Le bot gère ça proprement (il saute la source, ne plante pas). Si LeBonCoin ne
> remonte rien en prod, deux options : (a) faire tourner le bot sur **ton PC**
> (Planificateur de tâches Windows) où l'IP est résidentielle, ou (b) router
> LeBonCoin via **Firecrawl/Apify**. PAP, lui, marche partout.

## Comment ça marche
1. `main.py` récupère **toutes les sources en parallèle** (avec cache des requêtes
   identiques et 3 retries sur erreur réseau).
2. Il filtre selon `config.json`, **déduplique entre sources** (un même bien
   cross-posté sur LeBonCoin + Bien'ici + PAP = une seule alerte, liens groupés),
   écarte les annonces déjà vues (`seen.json`).
3. Il envoie les nouveautés via `notify.py` (Telegram).
4. Le workflow GitHub Actions relance tout ça toutes les 15 min et mémorise l'état.

## Mise en route (une fois)

### 1. Bot Telegram
- Sur Telegram, écris à **@BotFather** → `/newbot` → copie le **token**.
- Récupère ton **chat_id** : écris à ton bot, puis ouvre
  `https://api.telegram.org/bot<TON_TOKEN>/getUpdates` → champ `"chat":{"id":...}`.

### 2. GitHub
- Crée un dépôt **privé**, pousse le dossier `pige-immo/`.
- **Settings → Secrets and variables → Actions** → ajoute `TELEGRAM_BOT_TOKEN`
  et `TELEGRAM_CHAT_ID`.
- Onglet **Actions** → active les workflows.

Au **premier passage**, le bot t'envoie un résumé + les annonces récentes, puis
ne te prévient ensuite que des **nouvelles**.

## Régler tes critères — `config.json`
La config contient une liste de **profils** de recherche, traités en parallèle.
Par défaut deux profils :
1. **Coloc T3 avec ami — Strasbourg** (loyer total ≤ 1000 €, ≥ 3 pièces).
2. **Solo studio/T2 — Schiltigheim proche centre** (≤ 800 €, 1 à 2 pièces).

Champs d'un profil :
| Champ | Rôle |
|---|---|
| `label` | Nom du profil (affiché dans l'alerte Telegram) |
| `sources` | Dict {nom de source : requête} (chemin PAP, lieu LeBonCoin, zoneId Bien'ici) |
| `min_rent` | Loyer **min** (€/mois) — écarte les prix à la nuit / parkings / erreurs |
| `max_rent` | Loyer **total** max (€/mois) |
| `min_rooms` / `max_rooms` | Bornes de pièces (`max_rooms: 0` = pas de plafond) |
| `min_surface` | Surface minimum (m²) |
| `unfurnished_only` | Ne garder que le **non meublé** |
| `furnished_only` | Ne garder que le meublé |
| `exclude_keywords` / `include_keywords` | Filtres mots-clés |

👉 Une annonce qui colle aux deux profils n'est envoyée qu'**une fois**, avec les
deux étiquettes. Mets `unfurnished_only: true` pour verrouiller le non-meublé.

> Note : la page Schiltigheim de PAP inclut les annonces de Strasbourg « à ~3 km »,
> ce qui couvre justement le corridor Gare ↔ Schiltigheim (proche centre + proche IUT).

## Tester en local
```bash
pip install -r requirements.txt
python test_pige.py   # suite de tests (filtres, dédup, échappement) — sans réseau
python main.py        # sans token Telegram = affiche les annonces dans le terminal
python pap.py         # voir les annonces brutes d'une source (idem leboncoin.py, bienici.py)
```

## Robustesse (déjà en place)
- Envoi Telegram **anti-spam** : une annonce n'est marquée « vue » qu'**après** envoi
  réussi, et l'état est sauvegardé même en cas d'erreur → jamais de re-spam sur crash.
- Gestion du **rate-limit Telegram** (429) + plafond d'alertes/run + throttle.
- **Échappement HTML** des titres (pas de plantage sur un `<` ou `&`).
- Une annonce malformée n'interrompt pas la source ; une source KO n'interrompt pas le run.
- `seen.json` **borné** (8000 entrées) pour ne pas gonfler à l'infini.
- LeBonCoin & Bien'ici triés **par date** → les nouvelles annonces sont vues en premier.
- Tests lancés en CI avant chaque passage (fail-fast).

## Limites & suite
- PAP = peu d'annonces (~20, c'est normal pour du particulier), mais **exactement**
  ton créneau (appart entier, sans frais).
- Pour plus de volume : **LeBonCoin** (particuliers + agences) — nécessite une API
  de scraping (DataDome). À brancher ensuite.
- Filtrage par **secteur précis** (Quartier Gare / Centre) possible en v2.
