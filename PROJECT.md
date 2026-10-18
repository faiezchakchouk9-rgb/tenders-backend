# Project: Tenders.tn — 4 Chantiers Commerciaux & Améliorations SaaS

## Architecture
- **Backend**: FastAPI 0.143, Uvicorn 0.54, Python 3.12, Jinja2, ReportLab, python-docx.
- **Base de données**: SQLite 3 (`tenders.db`) avec mode WAL (`PRAGMA journal_mode=WAL;`), timeout 5000ms.
- **Sécurité & Auth**: PBKDF2-HMAC-SHA256 (100 000 itérations, sel 16 octets), sessions client `localStorage` côté frontend.
- **Frontend**: HTML5 / Tailwind CSS (CDN v3), vanilla JS inline, architecture miroir `templates/` et `public/` (`public/` prioritaire dans `app.py`).
- **Messagerie & Alertes**: WhatsApp Cloud API / Green-API avec failover automatique (`whatsapp_gateway.py`), ordonnanceur d'arrière-plan autonome dans `app.py`.
- **Génération documentaire**: 5 documents officiels conformes au Décret n° 2014-1039 (format strict 1 page A4).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | OTP Request Endpoint | `POST /api/client/forgot-password/request` génère code 6 chiffres valide 10 min et l'envoie par WhatsApp | M1 | ORIGINAL_REQUEST §R1 |
| 2 | OTP Verify & Reset Endpoint | `POST /api/client/forgot-password/verify` vérifie code et réinitialise mot de passe PBKDF2 | M1 | ORIGINAL_REQUEST §R1 |
| 3 | UI Mot de Passe Oublié | Formulaire/modal étape par étape dans `dashboard.html` pour réinitialisation OTP | M1 | ORIGINAL_REQUEST §R1 |
| 4 | UI Onglet Essai Gratuit Direct | Onglet/bascule dans auth section de `dashboard.html` pour créer compte trial sans friction | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Préservation Auth PBKDF2 & Masquage | Conservation du hachage PBKDF2 et du bouton œil toggle visibilité | M1 | ORIGINAL_REQUEST §R1 |
| 6 | Export Excel Natif (.xlsx) & CSV | `GET /api/client/opportunities/{sub_id}/export?format=xlsx|csv` avec encodage UTF-8/BOM et colonnes requises | M2 | ORIGINAL_REQUEST §R2 |
| 7 | Dépendance `openpyxl` | Installation et ajout dans `requirements.txt` pour génération .xlsx native | M2 | Survey 1 & 3 |
| 8 | UI Boutons Export Opportunités | Boutons d'export Excel & CSV au-dessus de la liste des opportunités dans `dashboard.html` | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Filtrage Instantané Opportunités | Barre de recherche par mot-clé et numéro d'avis dans l'onglet opportunités sans rechargement | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Filtrage Instantané Statut Dossiers | Barre de pills (`TOUS`, `GENERE`, `DEPOSE_TUNEPS`, `RETENU`, `NON_RETENU`) dans "Mes Dossiers" | M2 | ORIGINAL_REQUEST §R2 |
| 11 | Pages Légales `/cgu` & `/confidentialite` | Création templates conformes Décret 2014-1039, Loi INPDP 2004-63 et banques (Konnect, Flouci, GIM-TEL) | M3 | ORIGINAL_REQUEST §R3 |
| 12 | Routes FastAPI `/cgu` & `/confidentialite` | Déclaration des routes retournant HTTP 200 avec contenu juridique complet et design corporate | M3 | ORIGINAL_REQUEST §R3 |
| 13 | Footers Dashboard & Landing Page | Liens clairs vers `/cgu` et `/confidentialite` dans footers de `index.html` et `dashboard.html` | M3 | ORIGINAL_REQUEST §R3 |
| 14 | Formatage Alertes WhatsApp Enrichies | Ajout de liens clairs vers fiche TUNEPS ET dossier de soumission Tenders.tn | M4 | ORIGINAL_REQUEST §R4 |
| 15 | Briefing Hebdomadaire Lundi 08h30 | Tâche cron/scheduler du lundi matin à 08h30 résumant les marchés prioritaires par abonné actif | M4 | ORIGINAL_REQUEST §R4 |
| 16 | Endpoint Déclenchement Essai Briefing | `POST /api/client/weekly-briefing/{sub_id}` et endpoint admin pour test manuel immédiat | M4 | ORIGINAL_REQUEST §R4 |
| 17 | Correction Bug Ordonnanceur `app.py:88` | Remplacement de `dispatch_notifications()` par `dispatch_alerts()` | M4 | Survey 3 |
| 18 | Synchronisation Miroir Templates HTML | Parité absolue 100% entre `templates/` et `public/` pour tous les fichiers modifiés | M5 | ORIGINAL_REQUEST §Intégrité |
| 19 | Préservation Mode SQLite WAL & Non-régression | Maintien du mode WAL et vérification non-régression sur auth, packs ZIP, PDF/DOCX | M5 | ORIGINAL_REQUEST §Intégrité |
| 20 | Test Suite E2E Complète (Tiers 1-4) | Suite de tests opaque-box automatisée couvrant l'intégralité des 4 chantiers R1-R4 | ME2E | ORIGINAL_REQUEST §Intégrité |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| ME2E | E2E Testing Suite | Conception et développement du harnais de test automatisé global (Tiers 1-4) couvrant R1-R4, WAL, templates sync | None | DONE (test_global_e2e.py & TEST_READY.md) |
| M1 | R1: Sécurité & OTP WhatsApp | Table OTP, endpoints forgot-password request/verify, UI auth tab trial & forgot password | None | DONE (PBKDF2 100k, OTP 6-digits, dual-tab auth) |
| M2 | R2: Outils Métier & Export | Dépendance openpyxl, endpoint export Excel/CSV, UI filtres opportunités & pills dossiers | None | DONE (openpyxl installed, BOM UTF-8, instant filters) |
| M3 | R3: Conformité Juridique | Templates cgu & confidentialite, routes HTTP 200, footers index & dashboard | None | DONE (/cgu, /confidentialite, 100% SHA256 parity) |
| M4 | R4: Alertes & Briefing Hebdo | Liens enrichis alertes WhatsApp, briefing lundi 08h30, correction scheduler, endpoint test | None | DONE (notifier enriched, Monday 08h30 cron, endpoints 200) |
| M5 | Final Milestone: Intégrité & E2E Pass | Vérification 100% E2E test suite, sync templates/ vs public/, WAL, audit forensique | M1, M2, M3, M4, ME2E | DONE (Gate PASS: Reviewers APPROVE, Challengers APPROVE, Auditor CLEAN) |

## Interface Contracts

### M1: Auth & OTP WhatsApp
- `POST /api/client/forgot-password/request`
  - Input JSON: `{"phone": "+216XXXXXXXX" | "XXXXXXXX"}`
  - Output JSON: `{"success": true, "message": "Code OTP expédié via WhatsApp", "expires_in_minutes": 10}`
  - Error: 404 si abonné non trouvé (`"Numéro non associé à un compte"`), 400 si format invalide.
- `POST /api/client/forgot-password/verify`
  - Input JSON: `{"phone": "+216XXXXXXXX", "otp_code": "123456", "new_password": "..."}`
  - Output JSON: `{"success": true, "message": "Mot de passe réinitialisé avec succès"}`
  - Error: 400 si code invalide ou expiré (`"Code OTP invalide ou expiré"`).
- `POST /api/subscribe` (existant, supporté pour onboarding direct):
  - Input: `{"company_name": "...", "phone": "...", "email": "...", "password": "...", "plan": "TRIAL", "categories": [...], "governorates": [...]}`
  - Output JSON: `{"success": true, "subscriber_id": int, "plan": "TRIAL"}`

### M2: Export Opportunités & Filtrage
- `GET /api/client/opportunities/{sub_id}/export?format=xlsx` (ou direct `/export.xlsx`)
  - Output: `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `Content-Disposition: attachment; filename="opportunites_tenders_tn_....xlsx"`
  - En-têtes: `N° Avis`, `Acheteur`, `Objet`, `Région`, `Date limite`, `Cautionnement`, `Secteur`, `Lien TUNEPS`.
- `GET /api/client/opportunities/{sub_id}/export?format=csv` (ou direct `/export.csv`)
  - Output: `Content-Type: text/csv; charset=utf-8`, encodé avec BOM UTF-8 (`utf-8-sig`) pour compatibilité Excel Windows.
- Filtrage client `dashboard.html`:
  - Champ de recherche instantanée: filtrage en temps réel sur `clientOpportunities` selon `bid_no`, `title_fr`, `buyer_name`.
  - Boutons de statut "Mes Dossiers": filtrage instantané sur les cartes du conteneur `#dossiers-list-container` selon le statut sélectionné (`TOUS`, `GENERE`, `DEPOSE_TUNEPS`, `RETENU`, `NON_RETENU`).

### M3: Conformité Juridique
- `GET /cgu`:
  - Output: HTML complet HTTP 200 reprenant le style de la plateforme, mentionnant la législation tunisienne (Décret n° 2014-1039, Code des Obligations et des Contrats) et les conditions de paiement (Konnect, Flouci, GIM-TEL).
- `GET /confidentialite`:
  - Output: HTML complet HTTP 200 conforme à la Loi organique n° 2004-63 (INPDP) et aux règles de confidentialité WhatsApp Cloud API.
- Liens dans footers:
  - `<a href="/cgu">Conditions Générales d'Utilisation</a>`
  - `<a href="/confidentialite">Politique de Confidentialité</a>`

### M4: Alertes WhatsApp & Briefing Hebdomadaire
- Format WhatsApp Alert:
  - Intègre:
    `🔗 *Fiche officielle TUNEPS :* {tender.url}`
    `📂 *Dossier de soumission Tenders.tn :* {app_url}/dashboard?tab=dossiers&tender={ep_bid_master_id}`
- Ordonnancement Briefing Hebdo:
  - Déclenchement automatique chaque lundi à 08h30 (fuseau Tunis `Africa/Tunis`, UTC+1).
- Endpoints de test & déclenchement:
  - `POST /api/client/weekly-briefing/{sub_id}`: déclenche l'envoi du briefing hebdo pour l'abonné ciblé.
  - `POST /api/admin/dispatch-weekly-briefing`: déclenche pour tous les abonnés actifs.

## Code Layout
- `app.py`: Serveur FastAPI, routes `/cgu`, `/confidentialite`, `/api/client/forgot-password/*`, `/api/client/opportunities/{sub_id}/export`, `/api/client/weekly-briefing/*`, scheduler loop.
- `database.py`: Table et méthodes pour OTP (`password_reset_otps`), PBKDF2 hashing, WAL connection.
- `notifier.py`: Formatage des alertes WhatsApp enrichies, méthode `send_weekly_briefing`.
- `whatsapp_gateway.py`: Passerelle Meta Cloud API / Green-API.
- `templates/dashboard.html` & `public/dashboard.html`: UI auth tab trial & forgot password, toolbar opportunités (recherche & export), filter bar statut dossiers, footer.
- `templates/index.html` & `public/index.html`: Footer avec liens `/cgu` et `/confidentialite`.
- `templates/cgu.html` & `public/cgu.html`: Page CGU conforme.
- `templates/confidentialite.html` & `public/confidentialite.html`: Page Confidentialité conforme.
- `requirements.txt`: Ajout de `openpyxl>=3.1.0`.
- `test_global_e2e.py`: Harnais de test E2E global vérifiant tous les modules.
