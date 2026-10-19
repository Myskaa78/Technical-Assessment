# Web Scraping & Data Ingestion —  Technical Assessment

Ce projet propose un service de web scraping et d'ingestion de données structurées, conçu pour tourner localement sans Docker avec **Node.js** et **Python**.

Il permet de récupérer le contenu propre d'une page web à partir d'une URL, avec gestion du cache en mémoire et exécution du JavaScript pour les sites dynamiques (SPA).

---

## Architecture & Choix techniques 

Le projet est découpé en deux services communicant en local :

1. **API Gateway & Frontend (NestJS — Port 3000)** :
   - Reçoit les requêtes utilisateur sur la route `POST /api/extract`.
   - Gère le cache en mémoire vive pour éviter de rescraper une même URL.
   - Sert l'interface web accessible sur [http://localhost:3000](http://localhost:3000).
   - Communique avec le service Python via des requêtes HTTP internes.

2. **Service de Scraping (FastAPI / Python — Port 8000)** :
   - Vérifie la sécurité avec une protection SSRF.
   - Vérifie le respect du fichier `robots.txt` du site cible.
   - Supporte les sites dynamiques (React, Vue, Angular) grâce à **Playwright Chromium** en mode headless (démarré au lancement via le cycle de vie de FastAPI pour éviter de recréer un navigateur à chaque requête).
   - Extrait le texte principal sans le bruit (menus, pubs, footers) avec **Trafilatura**.
   - Extrait les métadonnées et normalise les images et vidéos (chemins absolus et déduplication) avec **BeautifulSoup**.


## Améliorations futures (With Additional Time)

- **File de traitement asynchrone (Job Queue)** : Utiliser une file de messages (BullMQ avec Redis ou Celery) pour transformer les demandes de scraping en tâches d'arrière-plan, avec un système de statut (`GET /api/extract/:id`) ou de webhook pour les gros volumes.
- **Mode hybride intelligent** : Tester d'abord une requête HTTP rapide (`httpx`), et ne basculer sur le navigateur Playwright que si la page est vide ou détectée comme une SPA (ex: conteneur `<div id="root">` sans texte), pour économiser CPU et mémoire.
- **Persistance des données** : Sauvegarder l'historique et les données extraites dans une base de données (PostgreSQL ou MongoDB) pour pouvoir les exploiter ou les réanalyser plus tard.
- **Rotation de proxies & headers** : Intégrer un pool de proxies rotatifs et des User-Agents dynamiques pour contourner le rate-limiting sur les sites protégés.
- **Monitoring et observabilité** : Ajouter des métriques (taux de succès, durée des requêtes, ratio de cache hit/miss) et des logs structurés pour surveiller le service en production.

---

## Installation et Démarrage

### Prérequis
- Node.js (v18 ou v20) et npm
- Python (3.10 ou supérieur)

Le projet se lance avec deux terminaux ouverts.

### 1. Démarrer le microservice Python
Dans un premier terminal :

```bash
cd scraper

# Création et activation de l'environnement virtuel
python3 -m venv venv
source venv/bin/activate  # Sous Windows : venv\Scripts\activate

# Installation des dépendances et du navigateur pour Playwright
pip install -r requirements.txt
playwright install chromium

# Lancement du serveur sur le port 8000
uvicorn main:app --port 8000 --reload
```

### 2. Démarrer l'API NestJS
Dans un deuxième terminal :

```bash
cd api

# Installation des paquets
npm install

# Démarrage de l'API et du frontend sur le port 3000
npm run start:dev
```

---

## Utilisation

### 1. Interface Web
Ouvrez votre navigateur sur **http://localhost:3000** :
- Saisissez l'URL d'une page ou d'un article.
- Cliquez sur **Extract**.
- Le rendu JavaScript est exécuté automatiquement en arrière-plan.
- Le JSON complet s'affiche, accompagné du temps d'exécution et du statut du cache (**CACHE MISS** à la 1ère requête, puis **CACHE HIT** immédiat aux suivantes).

### 2. En ligne de commande (cURL)

Extraction standard :
```bash
curl -X POST http://localhost:3000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Test du blocage SSRF (bloqué avec une erreur HTTP 403) :
```bash
curl -i -X POST http://localhost:3000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "http://127.0.0.1:8000"}'
```

---


### Tests Python (Unittest)
Vérifie la sécurité SSRF, le rejet des URLs invalides, l'extraction des métadonnées et le dédoublonnage des médias.
```bash
cd scraper
./venv/bin/python -m unittest test_scraper.py
```
## ⚙️ Configuration (Variables d'environnement)

Pour faire fonctionner le projet, créez un fichier `.env` à la racine  et définissez les variables suivantes :

```env
# Port de l'API Gateway NestJS & Frontend
PORT=3000

# URL interne du microservice de scraping Python
SCRAPER_URL=http://localhost:8000/scrape

# Durée d'expiration du cache en millisecondes (TTL)
# 3600000 = 1 heure (valeur par défaut)
# 60000 = 1 minute
# 86400000 = 24 heures
CACHE_TTL_MS=3600000

```

## Structure des fichiers

```
Technical-Assessment/
├── README.md
├── api/                           # Gateway NestJS & Interface Web
│   ├── public/
│   │   └── index.html             # Interface web utilisateur
│   ├── src/
│   │   ├── main.ts                # Bootstrap de l'application
│   │   ├── app.module.ts          # Déclaration du cache RAM et modules
│   │   └── extract/
│   │       ├── dto/extract.dto.ts
│   │       ├── extract.controller.ts
│   │       ├── extract.service.ts
│   └── package.json
└── scraper/                       # Service Python
    ├── main.py                    # Application FastAPI et parsing HTML
    ├── test_scraper.py            # Tests unitaires Python
    └── requirements.txt
```
