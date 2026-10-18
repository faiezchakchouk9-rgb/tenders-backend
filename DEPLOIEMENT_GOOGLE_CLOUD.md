# 🚀 Guide de Déploiement : Firebase + Google Cloud Run (24/7 Alertes WhatsApp)

Ce guide détaille la mise en production de la plateforme **Tenders.tn** sur l'infrastructure **Google Cloud & Firebase**, garantissant :
- **0 délai de démarrage** (CDN Google pour le tableau de bord et la landing page) ;
- **Veille autonome 24h/24 et 7j/7** via **Google Cloud Scheduler** ;
- **Envoi instantané des alertes WhatsApp** dès qu'un nouvel appel d'offres TUNEPS est publié ;
- **Briefing hebdomadaire du lundi à 08h30** envoyé automatiquement par WhatsApp.

---

## 🏗️ Architecture Technique

```
                              ┌──────────────────────────────────────────────┐
                              │               Utilisateur                    │
                              └──────────────────────┬───────────────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │       Firebase Hosting       │
                                      │      (CDN Mondial Google)    │
                                      └──────┬────────────────┬──────┘
                                             │                │
                        Fichiers Statiques   │                │ Rewrites /api/*
              (index, dashboard, CGU, etc.)  ▼                ▼
                                      ┌──────────────┐ ┌─────────────┴────────────────┐
                                      │ Navigateur   │ │       Google Cloud Run       │
                                      │ Client (PME) │ │ (FastAPI Python / Dockerfile)│
                                      └──────────────┘ └──────────────┬───────────────┘
                                                                      │
                      ┌───────────────────────────────────────────────┼──────────────────────────────┐
                      │                                               │                              │
                      ▼                                               ▼                              ▼
        ┌───────────────────────────┐                   ┌───────────────────────────┐  ┌───────────────────────────┐
        │   Google Cloud Storage    │                   │   Scraping TUNEPS         │  │   Meta Cloud API          │
        │   (Volume persistant DB)  │                   │   (Veille temps réel)     │  │   (Alertes WhatsApp 24/7) │
        └───────────────────────────┘                   └─────────────▲─────────────┘  └───────────────────────────┘
                                                                      │
                                                        Toutes les 15 minutes (24/7)
                                                                      │
                                                        ┌─────────────┴─────────────┐
                                                        │   Google Cloud Scheduler  │
                                                        │   (Tâches automatisées)   │
                                                        └───────────────────────────┘
```

---

## 📋 Prérequis (5 minutes)

1. Un compte Google (avec accès à la console [console.cloud.google.com](https://console.cloud.google.com))
2. Ouvrez **Google Cloud Shell** directement dans votre navigateur (bouton `>_` en haut à droite de la console Google Cloud) :
   - Tout y est déjà pré-installé gratuitement (`gcloud`, `docker`, `firebase`).

---

## 🛠️ Étape 1 : Activer les Services Google Cloud

Dans votre Cloud Shell (ou terminal configuré), exécutez :

```bash
# Définir l'identifiant de votre projet
gcloud config set project VOTRE_PROJECT_ID

# Activer les APIs nécessaires (Cloud Run, Scheduler, Build, Storage)
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com
```

---

## 🐳 Étape 2 : Déployer le Backend sur Google Cloud Run

### Option A : Déploiement en 1 clic depuis Cloud Shell
Dans le dossier du projet :

```bash
gcloud run deploy tenders-backend \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --set-env-vars "ENVIRONMENT=production,DB_PATH=/app/data/tenders.db,META_PHONE_NUMBER_ID=VOTRE_ID,META_ACCESS_TOKEN=VOTRE_TOKEN,WHATSAPP_PROVIDER=meta"
```

*Note : Cloud Run vous retournera l'URL officielle du service (ex: `https://tenders-backend-xxxxx-ew.a.run.app`).*

---

## ⏰ Étape 3 : Configurer les Alertes WhatsApp 24/7 (Cloud Scheduler)

C'est cette étape qui garantit la veille permanente sans jamais dépendre d'un ordinateur allumé :

### 1. Veille TUNEPS & Alertes Immédiates (Toutes les 15 minutes, 24h/24)
```bash
gcloud scheduler jobs create http tuneps-sync-24-7 \
  --schedule="*/15 * * * *" \
  --time-zone="Africa/Tunis" \
  --uri="https://tenders-backend-xxxxx-ew.a.run.app/api/sync" \
  --http-method=GET \
  --description="Scan continu TUNEPS et dispatch alertes WhatsApp 24/7"
```

### 2. Briefing Hebdomadaire du Lundi Matin (08h30)
```bash
gcloud scheduler jobs create http weekly-briefing-monday \
  --schedule="30 8 * * 1" \
  --time-zone="Africa/Tunis" \
  --uri="https://tenders-backend-xxxxx-ew.a.run.app/api/client/weekly-briefing/trigger" \
  --http-method=POST \
  --description="Briefing hebdomadaire des meilleurs marchés envoyé aux abonnés"
```

---

## 🌐 Étape 4 : Déployer le Frontend sur Firebase Hosting

1. Dans `firebase.json`, remplacez `tenders-backend` et `europe-west1` par le nom et la région de votre service Cloud Run :
```json
{
  "hosting": {
    "public": "public",
    "cleanUrls": true,
    "rewrites": [
      {
        "source": "/api/**",
        "run": {
          "serviceId": "tenders-backend",
          "region": "europe-west1"
        }
      },
      {
        "source": "/health",
        "run": {
          "serviceId": "tenders-backend",
          "region": "europe-west1"
        }
      },
      {
        "source": "/dashboard",
        "destination": "/dashboard.html"
      },
      {
        "source": "/cgu",
        "destination": "/cgu.html"
      },
      {
        "source": "/confidentialite",
        "destination": "/confidentialite.html"
      },
      {
        "source": "**",
        "destination": "/index.html"
      }
    ]
  }
}
```

2. Déployez avec la commande Firebase :
```bash
firebase deploy --only hosting
```

Votre site est alors en ligne sur votre domaine Firebase (ex: `https://votre-projet.web.app`) et vous pouvez y associer votre domaine personnalisé (ex: `https://tenders.tn`).

---

## 💾 Étape 5 : Persistance des Données (Base SQLite `tenders.db`)

Cloud Run supporte le montage natif d'un bucket **Google Cloud Storage** en tant que volume de disque :

1. Créez un bucket de stockage :
   ```bash
   gcloud storage buckets create gs://tenders-tn-data --location=europe-west1
   ```
2. Dans la console Cloud Run > **tenders-backend** > **Modifier et déployer une nouvelle révision** :
   - Allez dans **Volumes** > **Ajouter un volume**.
   - Choisissez **Bucket Cloud Storage** : `tenders-tn-data`.
   - Point de montage : `/app/data`.
   - Variable d'environnement : `DB_PATH=/app/data/tenders.db`.

Vos données d'abonnés, logos, historiques de candidatures et marchés indexés sont ainsi **sauvegardés de manière permanente et résiliente**.

---

## ✅ Résultat Final

- ⚡ **Affichage instantané** du Dashboard et de la Landing Page depuis le CDN mondial Google (0 seconde d'attente).
- 📲 **Veille 24/7/365** assurée par Google Cloud Scheduler sans interruption.
- 🎯 **Réception des alertes WhatsApp** en temps réel sur le numéro `+21628177888` et pour tous les abonnés de la plateforme.
- 📑 **Dossiers de soumission** Word/PDF générés à la volée avec l'image de marque officielle.
