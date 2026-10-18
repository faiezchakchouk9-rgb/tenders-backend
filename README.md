# 🇹🇳 Tenders.tn — Plateforme de Veille sur les Marchés Publics Tunisiens

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://tenders.tn)
[![Python](https://img.shields.io/badge/python-3.12-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)]()

> Solution **Zero-Ops** complète de veille automatisée sur les marchés publics tunisiens (TUNEPS) avec alertes WhatsApp/Telegram en temps réel, génération de documents professionnels et plateforme d'onboarding self-service.

---

## 📋 Table des matières

- [Fonctionnalités](#-fonctionnalités)
- [Architecture](#-architecture)
- [Prérequis](#-prérequis)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Déploiement](#-déploiement)
- [API Reference](#-api-reference)
- [Structure du Projet](#-structure-du-projet)
- [Support](#-support)

---

## ✨ Fonctionnalités

### 🔍 Veille Automatisée TUNEPS
- Collecte en temps réel des appels d'offres depuis l'API TUNEPS
- Déduplication intelligente et stockage en base SQLite indexée FTS5
- Synchronisation automatique toutes les 30 minutes

### 🤖 Qualification IA Bilingue (FR/AR)
- Classification sectorielle automatique (IT, BTP, Santé, Énergie, etc.)
- Détection des 24 gouvernorats tunisiens
- Synthèse exécutive générée par IA pour lecture rapide

### 📱 Alertes Multi-Canal
- **WhatsApp** : Via Meta Cloud API (production) avec fallback Green API
- **Telegram** : Bot intégré avec commandes interactives
- Filtrage multi-critères : Catégorie + Gouvernorat + Mots-clés
- Briefing matinal quotidien automatique à 08h00

### 📄 Génération de Documents Professionnels
- Offres financières (BPU/DPGF) personnalisées
- Propositions techniques avec charte graphique du client
- Demandes de clarification
- Export Word (.docx) et PDF avec logo et identité visuelle

### 💳 Paiement en Ligne
- Intégration Konnect.network / Flouci
- Essai gratuit 7 jours sans engagement
- Plans Starter (49 TND/mois) et Pro (129 TND/mois)

### 🖥️ Dashboard Client
- Tableau de bord interactif avec suivi des marchés
- Profil d'entreprise avec charte graphique
- Historique des documents générés

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│                  Client Web                      │
│         (Dashboard / Landing Page)               │
└──────────────────┬──────────────────────────────┘
                   │ HTTPS
┌──────────────────▼──────────────────────────────┐
│              FastAPI (app.py)                     │
│  ┌───────┐ ┌──────────┐ ┌──────────────────┐    │
│  │Routes │ │Middleware │ │ Error Handlers   │    │
│  │API    │ │Auth/CORS  │ │ Global           │    │
│  └───┬───┘ └──────────┘ └──────────────────┘    │
│      │                                           │
│  ┌───▼─────────────────────────────────────┐    │
│  │          Couche Métier                   │    │
│  │ ┌─────────┐ ┌──────────┐ ┌───────────┐ │    │
│  │ │Collector│ │Enricher  │ │Notifier   │ │    │
│  │ │(TUNEPS) │ │(IA/NLP)  │ │(WA/TG)    │ │    │
│  │ └─────────┘ └──────────┘ └───────────┘ │    │
│  │ ┌─────────────────┐ ┌────────────────┐ │    │
│  │ │DocxGenerator    │ │PdfGenerator    │ │    │
│  │ │(Propositions)   │ │(Offres)        │ │    │
│  │ └─────────────────┘ └────────────────┘ │    │
│  └─────────────────────────────────────────┘    │
│      │                                           │
│  ┌───▼────────────────┐                          │
│  │ SQLite + FTS5      │                          │
│  │ (database.py)      │                          │
│  └────────────────────┘                          │
└──────────────────────────────────────────────────┘
```

---

## 📦 Prérequis

- **Python** 3.12+
- **pip** (gestionnaire de paquets Python)
- **Docker** (optionnel, pour le déploiement conteneurisé)

---

## 🚀 Installation

### Installation locale

```bash
# 1. Cloner le dépôt
git clone https://github.com/votre-org/tenders-tn.git
cd tenders-tn

# 2. Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API

# 5. Lancer le serveur
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

### Installation avec Docker

```bash
# Build et démarrage
docker-compose up -d

# Voir les logs
docker-compose logs -f
```

---

## ⚙️ Configuration

### Variables d'environnement

Copier `.env.example` en `.env` et configurer :

| Variable | Description | Requis |
|----------|-------------|--------|
| `META_PHONE_NUMBER_ID` | ID du numéro WhatsApp Business | ✅ |
| `META_ACCESS_TOKEN` | Token permanent Meta Cloud API | ✅ |
| `GREEN_API_INSTANCE_ID` | ID instance Green API (fallback) | ⚠️ |
| `GREEN_API_TOKEN` | Token Green API | ⚠️ |
| `APP_BASE_URL` | URL publique du serveur | ✅ |
| `KONNECT_API_KEY` | Clé API Konnect (paiement) | ✅ |
| `KONNECT_WALLET_ID` | ID wallet Konnect | ✅ |
| `ADMIN_SECRET_KEY` | Clé d'accès administration | ✅ |
| `ENVIRONMENT` | `development` ou `production` | ✅ |
| `LOG_LEVEL` | Niveau de log (`DEBUG`, `INFO`, `WARNING`) | ❌ |

---

## 🌐 Déploiement

### Render.com (Recommandé)

1. Connecter votre dépôt GitHub à [Render](https://render.com)
2. Le fichier `render.yaml` configure automatiquement le service
3. Ajouter les variables d'environnement dans le dashboard Render
4. Le déploiement est automatique à chaque push

### Docker (VPS / Cloud)

```bash
# Build de l'image
docker build -t tenders-tn .

# Lancement en production
docker run -d \
  --name tenders-tn \
  -p 8000:8000 \
  --env-file .env \
  -v ./data:/app/data \
  --restart unless-stopped \
  tenders-tn
```

### Vérification du déploiement

```bash
# Health check
curl https://votre-domaine.com/health

# Version de l'API
curl https://votre-domaine.com/api/version
```

---

## 📡 API Reference

### Endpoints Publics

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/health` | Vérification de santé |
| `GET` | `/api/version` | Informations de version |
| `GET` | `/api/tenders/search` | Recherche de marchés |
| `GET` | `/api/tenders/{id}` | Détails d'un marché |
| `POST` | `/api/subscribe` | Inscription |
| `GET` | `/api/sync` | Synchronisation manuelle TUNEPS |

### Endpoints Client (Dashboard)

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/client/opportunities/{sub_id}` | Marchés correspondants au profil |
| `PUT` | `/api/client/profile/{sub_id}` | Mise à jour du profil |
| `GET` | `/api/tenders/{id}/proposal.docx` | Télécharger proposition technique |
| `GET` | `/api/tenders/{id}/commercial.docx` | Télécharger offre financière |
| `GET` | `/api/tenders/{id}/proposal.pdf` | Télécharger proposition PDF |
| `GET` | `/api/tenders/{id}/commercial.pdf` | Télécharger offre financière PDF |

### Documentation Interactive

Accédez à la documentation Swagger UI complète : `https://votre-domaine.com/docs`

---

## 📁 Structure du Projet

```
tenders-tn/
├── app.py                  # Serveur FastAPI principal
├── database.py             # Modèle de données SQLite + FTS5
├── collector.py            # Collecteur API TUNEPS
├── enricher.py             # Qualification IA bilingue
├── notifier.py             # Dispatch alertes WhatsApp/Telegram
├── whatsapp_gateway.py     # Passerelle Meta Cloud API
├── telegram_bot.py         # Bot Telegram
├── payment_gateway.py      # Intégration Konnect/Flouci
├── docx_generator.py       # Générateur documents Word
├── pdf_generator.py        # Générateur documents PDF
├── config.py               # Configuration centralisée
├── pipeline.py             # Pipeline de traitement
├── scheduler.py            # Planificateur de tâches
├── templates/              # Templates HTML (Jinja2)
│   ├── index.html          # Landing page commerciale
│   ├── dashboard.html      # Tableau de bord client
│   ├── admin.html          # Panel d'administration
│   └── print_*.html        # Templates d'impression
├── public/                 # Fichiers statiques
├── Dockerfile              # Image Docker production
├── docker-compose.yml      # Orchestration Docker
├── render.yaml             # Blueprint Render.com
├── requirements.txt        # Dépendances Python
├── .env.example            # Template de configuration
└── .gitignore              # Fichiers exclus du dépôt
```

---

## 📞 Support

- **Email** : support@tenders.tn
- **WhatsApp** : +216 XX XXX XXX
- **Documentation** : [https://docs.tenders.tn](https://docs.tenders.tn)

---

## 📜 Mentions Légales

- [Conditions Générales d'Utilisation (CGU)](templates/cgu.html)
- [Politique de Confidentialité](templates/privacy.html)

La plateforme respecte le **Décret n° 2014-1039** relatif à la réglementation des marchés publics en Tunisie et la **Loi Organique n° 2004-63** portant sur la protection des données à caractère personnel.

---

**© 2026 Tenders.tn — Tous droits réservés**
