# TEST READY — Harnais de Test E2E Global (Tenders.tn)

**Date d'homologation** : 2026-10-18T10:41:00Z  
**Auteur** : E2E Test Suite Engineer (`test_writer_e2e`)  
**Fichier de test exécutable** : `test_global_e2e.py`  
**Méthodologie** : Architecture Opaque-Box en 4 Tiers (Smoke, Unitaire, API, E2E & Adversarial)

---

## 1. Commande d'Exécution & Environnement

Le harnais de test E2E est autonome, idempotent et ne pollue pas la base de données. Il peut être exécuté indifféremment via :

```powershell
# Exécution directe avec rapport structuré par Tier
python test_global_e2e.py

# Ou via le runner standard unittest
python -m unittest test_global_e2e.py -v
```

### Prérequis d'environnement :
- Python 3.12+
- `fastapi`, `starlette`, `reportlab`, `python-docx` (présents dans l'environnement standard)
- Base de données locale `tenders.db` configurée en mode WAL (`PRAGMA journal_mode=WAL;`)

---

## 2. Matrice de Couverture des 4 Tiers (30 Tests)

| Tier | Périmètre | Nombre de Tests | Statut Actuel | Réf. Exigences |
|---|---|---|---|---|
| **Tier 1** | Tests Sanitaires, Liveness, WAL & Parité Miroir HTML | 5 tests | **5/5 PASS (100%)** | Intégrité & SQLite WAL |
| **Tier 2** | Tests Unitaires en Isolation (PBKDF2, OTP, Formatage, Sérialisation) | 5 tests | **3/5 PASS (60%)** | R1, R2, R4, Scheduler |
| **Tier 3** | Tests d'Intégration d'API (Endpoints HTTP & Contrats JSON) | 11 tests | **5/11 PASS (45%)** | R1, R2, R3, R4 |
| **Tier 4** | Parcours Utilisateur E2E & Scénarios Adversariaux | 9 tests | **6/9 PASS (67%)** | R1, R2, R3, R4, Intégrité |
| **TOTAL** | **Couverture Globale E2E** | **30 tests** | **19 PASS / 11 PENDING** | **R1, R2, R3, R4** |

---

## 3. Inventaire Détaillé des Tests

### Tier 1 : Tests Sanitaires & Environnementaux (Smoke & Sanity)
- [x] **`test_01_health_check_endpoint`** : `GET /health` répond HTTP 200, statut `healthy`, base SQLite connectée.
- [x] **`test_02_sqlite_wal_mode_active`** : `PRAGMA journal_mode;` retourne strictement `wal`.
- [x] **`test_03_sqlite_busy_timeout`** : `PRAGMA busy_timeout;` >= 5000ms pour garantir la concurrence Zero-Ops.
- [x] **`test_04_html_templates_mirror_parity`** : Parité binaire stricte 100% entre `templates/` et `public/` pour tous les fichiers HTML.
- [x] **`test_05_core_modules_importable`** : Import sans erreur de `database`, `app`, `notifier`, `whatsapp_gateway`, `pdf_generator`, `docx_generator`.

### Tier 2 : Tests Unitaires en Isolation (Unit & Component Isolation)
- [x] **`test_06_pbkdf2_hash_and_verify_algorithm`** : Hachage PBKDF2-HMAC-SHA256 (100 000 itérations, sel aléatoire 16 octets / 32 hex, comparaison à temps constant).
- [x] **`test_07_otp_generation_crypto_properties`** : Code OTP 6 chiffres numériques, persistance dans `password_reset_otps`, durée de validité 10 minutes.
- [ ] **`test_08_whatsapp_alert_enrichment_format`** : Formatage du message d'alerte intégrant le lien officiel TUNEPS ET le lien direct vers le dossier de soumission Tenders.tn (*Attente Worker M4*).
- [x] **`test_09_csv_utf8_bom_serialization`** : Sérialisation CSV avec BOM UTF-8 (`\xef\xbb\xbf`) garantissant la lisibilité sous Excel Windows pour le français et l'arabe.
- [ ] **`test_10_scheduler_method_integrity`** : Absence d'appel à `notifier.dispatch_notifications()` dans `app.py:88` au profit de `notifier.dispatch_alerts()` (*Bug identifié à corriger par Worker M4*).

### Tier 3 : Tests d'Intégration d'API (API & Contract Integration)
- [x] **`test_11_subscribe_trial_instant_onboarding`** : `POST /api/subscribe` (plan TRIAL) active immédiatement le compte (`is_active = 1`) et stocke le hash PBKDF2.
- [x] **`test_12_forgot_password_request_success`** : `POST /api/client/forgot-password/request` génère l'OTP et déclenche l'expédition WhatsApp.
- [x] **`test_13_forgot_password_request_unknown_phone`** : `POST /api/client/forgot-password/request` retourne HTTP 404 si le numéro n'est pas inscrit.
- [x] **`test_14_forgot_password_verify_success_and_login`** : `POST /api/client/forgot-password/verify` valide l'OTP, met à jour le mot de passe et autorise la connexion.
- [x] **`test_15_forgot_password_verify_invalid_otp`** : `POST /api/client/forgot-password/verify` avec faux code retourne HTTP 400.
- [ ] **`test_16_export_opportunities_csv_endpoint`** : `GET /api/client/opportunities/{sub_id}/export?format=csv` (HTTP 200, Content-Type CSV, BOM UTF-8, en-têtes requis) (*Attente Worker M2*).
- [ ] **`test_17_export_opportunities_xlsx_endpoint`** : `GET /api/client/opportunities/{sub_id}/export?format=xlsx` (HTTP 200, archive binaire OpenXML .xlsx valide) (*Attente Worker M2*).
- [ ] **`test_18_regulatory_cgu_endpoint`** : `GET /cgu` retourne HTTP 200 avec contenu juridique conforme (Décret 2014-1039, Konnect, Flouci, GIM-TEL) (*Attente Worker M3*).
- [ ] **`test_19_regulatory_confidentialite_endpoint`** : `GET /confidentialite` retourne HTTP 200 conforme à la Loi organique n° 2004-63 relative à l'INPDP (*Attente Worker M3*).
- [ ] **`test_20_weekly_briefing_client_endpoint`** : `POST /api/client/weekly-briefing/{sub_id}` déclenche l'envoi du briefing hebdomadaire pour un abonné (*Attente Worker M4*).
- [ ] **`test_21_weekly_briefing_admin_endpoint`** : `POST /api/admin/dispatch-weekly-briefing` déclenche le briefing pour l'ensemble des abonnés (*Attente Worker M4*).

### Tier 4 : Parcours Utilisateur E2E & Scénarios Adversariaux
- [x] **`test_22_full_user_lifecycle_journey`** : Parcours E2E complet (Souscription TRIAL -> Connexion initiale -> Demande OTP -> Réception WhatsApp -> Réinitialisation -> Connexion nouveau mot de passe -> Rejet ancien mot de passe).
- [ ] **`test_23_export_content_data_fidelity_and_encoding`** : Fidélité des données exportées (Avis, Acheteur, Cautionnement) avec les données réelles en base (*Attente Worker M2*).
- [ ] **`test_24_footer_legal_links_in_all_templates`** : Présence des balises `<a href="/cgu">` et `<a href="/confidentialite">` dans les pieds de page de `index.html` et `dashboard.html` (*Attente Worker M3*).
- [ ] **`test_25_dashboard_frontend_ui_contracts`** : Vérification des composants UI dans `dashboard.html` (modal OTP, onglet essai gratuit, recherche instantanée, filtres statut dossiers `TOUS`/`GENERE`/`DEPOSE_TUNEPS`/`RETENU`/`NON_RETENU`, boutons export) (*Attente Workers M1 & M2*).
- [x] **`test_26_adversarial_expired_otp_rejected`** : Rejet strict (HTTP 400) de tout code OTP dont la date d'expiration (+10 min) est dépassée.
- [x] **`test_27_adversarial_replayed_otp_rejected`** : Protection anti-rejeu : un code OTP marqué `is_used = 1` ne peut pas être réutilisé (HTTP 400).
- [x] **`test_28_adversarial_phone_number_variations`** : Normalisation automatique et tolérance des formats de numéros tunisiens (`+216...`, `216...`, `8 chiffres`, espaces et tirets).
- [x] **`test_29_adversarial_injection_and_tampering`** : Résistance aux attaques par injection SQL (`' OR '1'='1`) et altération de payload (retourne 400/404, jamais 500).
- [x] **`test_30_wal_concurrency_and_pdf_non_regression`** : Vérification de l'absence de régression sur la génération documentaire officielle (PDF/DOCX 1 page A4 conforme Décret 2014-1039) et absence de verrouillage concurrent SQLite.

---

## 4. Anomalies & Points d'Attention Détectés (Escalades QA)

1. **Bug d'appel Ordonnanceur (`app.py:88`)** :
   - `app.py` ligne 88 appelle `notifier.dispatch_notifications()`.
   - Or, la classe `TenderNotifier` implémente `dispatch_alerts(limit=50)`.
   - *Escalade* : Transmis au Worker M4 pour alignement sur `dispatch_alerts()`.

2. **Dépendance manquante pour l'export Excel (`openpyxl`)** :
   - `openpyxl` n'est pas listé dans `requirements.txt` et n'est pas présent dans l'environnement virtuel.
   - *Escalade* : Transmis au Worker M2 pour intégration d'`openpyxl>=3.1.0` dans `requirements.txt`.

3. **Synchronisation Miroir HTML (`templates/` <-> `public/`)** :
   - Le test `test_04_html_templates_mirror_parity` impose une conformité binaire à 100%. Tout ajout de composant UI (footers, modales, filtres) dans `templates/` doit être répercuté à l'identique dans `public/`.

---

## 5. Critères d'Acceptation & Validation Finale

Lorsque l'ensemble des workers spécialisés (M1, M2, M3, M4) auront achevé leurs implémentations respectives :
- Ré-exécuter `python test_global_e2e.py`.
- L'ensemble des **30 tests** doit afficher `OK` avec code de sortie `0`.
- Aucun fichier de template ne doit présenter de divergence entre `templates/` et `public/`.
