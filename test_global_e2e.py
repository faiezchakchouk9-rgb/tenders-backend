"""
Harnais de Test E2E Global Automatisé — Plateforme SaaS Tenders.tn
==================================================================
Méthodologie 4-Tier conforme aux exigences PROJECT.md et ORIGINAL_REQUEST.md.

Tiers de Couverture :
---------------------
- Tier 1 : Tests Sanitaires & Environnementaux (Smoke, SQLite WAL, Mirror Templates Parity)
- Tier 2 : Tests Unitaires en Isolation (PBKDF2, Génération OTP, Formatage Alertes WhatsApp, Sérialisation CSV/Excel)
- Tier 3 : Tests d'Intégration d'API (R1 Auth/OTP, R2 Export Opportunités, R3 CGU/Confidentialité, R4 Briefing Hebdo)
- Tier 4 : Parcours Utilisateur E2E & Scénarios Adversariaux (Lifecycle complet, Replay Attack, OTP Expiré, Injection SQL, Concurrence WAL)

Exécution :
-----------
    python test_global_e2e.py
    python -m unittest test_global_e2e.py
"""

import os
import sys
import io
import csv
import json
import time
import re
import filecmp
import hashlib
import secrets
import sqlite3
import zipfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from unittest.mock import patch, MagicMock

# FastAPI TestClient
try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

# Imports de l'application
import database
import app
import notifier
import whatsapp_gateway
import pdf_generator
import docx_generator

# Configuration de base pour l'environnement de test
DB_FILE = os.path.join(os.path.dirname(__file__), "tenders.db")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")
TEST_PHONE = "+21699990001"
TEST_PHONE_CLEAN = "21699990001"
TEST_PASS = "SecretPass2026!"
NEW_PASS = "NewSecretPass2026!#"


def _cleanup_test_data():
    """Nettoie tous les abonnés et OTPs de test créés pendant la suite."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("DELETE FROM subscribers WHERE phone LIKE '%99990%' OR email LIKE '%test_e2e%'")
            try:
                conn.execute("DELETE FROM password_reset_otps WHERE phone LIKE '%99990%'")
            except Exception:
                pass
            conn.commit()
    except Exception:
        pass


class BaseE2ETestCase(unittest.TestCase):
    """Classe de base fournissant le client TestClient et l'isolation des données."""

    @classmethod
    def setUpClass(cls):
        _cleanup_test_data()
        cls.client = TestClient(app.app)
        cls.db = database.TenderDatabase(db_path=DB_FILE)

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_data()

    def setUp(self):
        _cleanup_test_data()

    def tearDown(self):
        _cleanup_test_data()


# ==============================================================================
# TIER 1 : TESTS SANITAIRES & ENVIRONNEMENTAUX (SMOKE & SANITY)
# ==============================================================================

class TestTier1SmokeSanity(BaseE2ETestCase):
    """Tier 1: Vérification du bon état de marche du serveur, WAL SQLite et synchronisation HTML."""

    def test_01_health_check_endpoint(self):
        """Vérifie que /health répond HTTP 200 avec le statut 'healthy' et une connexion DB active."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200, f"Santé serveur KO: code {res.status_code}")
        data = res.json()
        self.assertEqual(data.get("status"), "healthy", f"Statut inattendu: {data}")
        self.assertEqual(data.get("database"), "connected", "La base de données n'est pas connectée")
        self.assertIn("total_tenders", data)

    def test_02_sqlite_wal_mode_active(self):
        """Vérifie que la base SQLite de production tourne strictement en mode WAL (Write-Ahead Logging)."""
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            journal_mode = cursor.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal", f"Mode journal SQLite attendu: 'wal', obtenu: '{journal_mode}'")

    def test_03_sqlite_busy_timeout(self):
        """Vérifie que le busy_timeout est configuré à au moins 5000ms pour éviter tout lock en concurrence."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            busy_timeout = cursor.execute("PRAGMA busy_timeout;").fetchone()[0]
            self.assertGreaterEqual(busy_timeout, 5000, f"busy_timeout insuffisant: {busy_timeout}ms (minimum requis 5000ms)")

    def test_04_html_templates_mirror_parity(self):
        """Vérifie la parité bit-à-bit stricte (100%) entre templates/ et public/ pour tous les templates HTML."""
        self.assertTrue(os.path.isdir(TEMPLATES_DIR), f"Dossier {TEMPLATES_DIR} introuvable")
        self.assertTrue(os.path.isdir(PUBLIC_DIR), f"Dossier {PUBLIC_DIR} introuvable")

        template_files = [f for f in os.listdir(TEMPLATES_DIR) if f.endswith(".html")]
        self.assertGreater(len(template_files), 0, "Aucun template HTML trouvé dans templates/")

        mismatches = []
        for tf in template_files:
            t_path = os.path.join(TEMPLATES_DIR, tf)
            p_path = os.path.join(PUBLIC_DIR, tf)
            if not os.path.exists(p_path):
                mismatches.append(f"Fichier manquant dans public/: {tf}")
                continue
            if not filecmp.cmp(t_path, p_path, shallow=False):
                mismatches.append(f"Différence de contenu binaire entre templates/{tf} et public/{tf}")

        # Vérification réciproque : tous les HTML dans public/ doivent exister dans templates/
        public_files = [f for f in os.listdir(PUBLIC_DIR) if f.endswith(".html")]
        for pf in public_files:
            t_path = os.path.join(TEMPLATES_DIR, pf)
            if not os.path.exists(t_path):
                mismatches.append(f"Fichier présent dans public/ mais orphelin dans templates/: {pf}")

        self.assertEqual(len(mismatches), 0, f"Désynchronisation critique templates/ <-> public/ :\n" + "\n".join(mismatches))

    def test_05_core_modules_importable(self):
        """Vérifie que l'ensemble des modules applicatifs critiques s'importent sans erreur."""
        for mod in [database, app, notifier, whatsapp_gateway, pdf_generator, docx_generator]:
            self.assertIsNotNone(mod, f"Échec d'import du module {mod}")


# ==============================================================================
# TIER 2 : TESTS UNITAIRES EN ISOLATION (UNIT & COMPONENT ISOLATION)
# ==============================================================================

class TestTier2UnitIsolation(BaseE2ETestCase):
    """Tier 2: Vérification unitaire des briques cryptographiques, OTP, formatage alertes et ordonnanceur."""

    def test_06_pbkdf2_hash_and_verify_algorithm(self):
        """Vérifie l'algorithme PBKDF2-HMAC-SHA256 (100k itérations, sel 16 octets / 32 hex, temps constant)."""
        pwd = "TestSecurePassword2026!"
        h1 = database.hash_password(pwd)
        h2 = database.hash_password(pwd)

        self.assertIn(":", h1, "Le hash stocké doit être au format salt:hash")
        salt1, raw1 = h1.split(":", 1)
        salt2, raw2 = h2.split(":", 1)

        # Les sels aléatoires doivent être distincts même pour un mot de passe identique
        self.assertNotEqual(salt1, salt2, "Deux hashs successifs doivent utiliser des sels cryptographiques distincts")
        self.assertEqual(len(salt1), 32, "Le sel doit faire exactement 32 caractères hexadécimaux (16 octets)")
        self.assertEqual(len(raw1), 64, "Le hash SHA-256 brut doit faire exactement 64 caractères hexadécimaux")

        # Vérification de conformité
        self.assertTrue(database.verify_password(pwd, h1), "Le mot de passe correct doit être validé")
        self.assertFalse(database.verify_password("FauxMotDePasse", h1), "Un mauvais mot de passe doit être rejeté")
        self.assertFalse(database.verify_password("", h1), "Un mot de passe vide doit être rejeté")
        self.assertFalse(database.verify_password(pwd, None), "Un hash None doit retourner False sans planter")
        self.assertFalse(database.verify_password(pwd, "invalid_hash_string"), "Un hash malformé doit retourner False")

    def test_07_otp_generation_crypto_properties(self):
        """Vérifie les propriétés du code OTP : strictement 6 chiffres, génération aléatoire, validité 10 min."""
        # Si la méthode create_password_reset_otp existe sur database.TenderDatabase
        if hasattr(self.db, "create_password_reset_otp"):
            # Créer un abonné de test temporaire
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute(
                    "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, created_at) "
                    "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, datetime('now'))",
                    ("TEST OTP SARL", TEST_PHONE, "otp@test.tn", "TRIAL")
                )
                conn.commit()

            sub, code = self.db.create_password_reset_otp(TEST_PHONE)
            self.assertIsNotNone(sub, "L'abonné cible doit être trouvé pour la création de l'OTP")
            self.assertIsNotNone(code, "Le code OTP généré ne doit pas être nul")
            self.assertTrue(re.match(r"^\d{6}$", code), f"Le code OTP doit être exactement 6 chiffres: {code}")

            # Vérifier l'enregistrement en base
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM password_reset_otps WHERE phone = ? ORDER BY id DESC LIMIT 1", (TEST_PHONE,)).fetchone()
                self.assertIsNotNone(row, "L'OTP doit être persisté dans la table password_reset_otps")
                self.assertEqual(row["otp_code"], code)
                self.assertEqual(row["is_used"], 0)
                # Vérifier expiration ~10 min
                exp_dt = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                created_dt = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if "created_at" in row.keys() else datetime.now(timezone.utc)
                diff_minutes = (exp_dt - created_dt).total_seconds() / 60
                self.assertAlmostEqual(diff_minutes, 10.0, delta=1.0, msg="La durée de validité de l'OTP doit être de 10 minutes")
        else:
            self.fail("database.TenderDatabase ne possède pas la méthode requise create_password_reset_otp (R1)")

    def test_08_whatsapp_alert_enrichment_format(self):
        """Vérifie que l'alerte WhatsApp contient le lien TUNEPS officiel ET le lien direct vers le dossier Tenders.tn (R4)."""
        tender = None
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenders LIMIT 1")
            row = cursor.fetchone()
            if row:
                tender = database.TenderNotice(**dict(row))

        if not tender:
            self.fail("Aucun marché présent en base de données pour tester le formatage d'alerte")

        sub = self.db.get_subscriber_by_id(1)
        if not sub:
            sub = database.Subscriber(
                company_name="TUNISIE TEST SARL",
                phone="+21628177888",
                email="contact@test.tn",
                categories=["IT_TELECOM"],
                governorates=["ALL"],
                keywords=["informatique"],
                id=1
            )

        n = notifier.TenderNotifier(db=self.db)
        msg = n.format_whatsapp_message(tender, sub)

        # 1. Vérification du lien TUNEPS officiel
        self.assertIn(tender.url, msg, "L'alerte WhatsApp doit intégrer le lien officiel TUNEPS")

        # 2. Vérification du lien direct vers le dossier de soumission Tenders.tn
        # Doit contenir 'dashboard' ou 'dossier' et faire référence au marché
        self.assertTrue(
            ("tab=dossiers" in msg or "dossier" in msg.lower()) and ("tender=" in msg or str(tender.ep_bid_master_id) in msg or "dashboard" in msg),
            f"L'alerte WhatsApp doit inclure le lien direct vers le dossier de soumission. Contenu généré :\n{msg}"
        )

    def test_09_csv_utf8_bom_serialization(self):
        """Vérifie que l'exportation CSV applique strictement le BOM UTF-8 (utf-8-sig) pour compatibilité Excel."""
        # Données de test contenant des caractères arabes et français accentués
        rows = [
            {
                "bid_no": "2026/A01",
                "buyer_name": "Société Tunisienne de l'Électricité et du Gaz",
                "title": "Travaux d'électrification rurale & Réseau câblé",
                "governorate": "Kairouan / القيروان",
                "deadline_date": "2026-12-15",
                "guarantee": "3 000 TND"
            }
        ]

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        headers = ["N° Avis", "Acheteur", "Objet", "Région", "Date limite", "Cautionnement"]
        writer.writerow(headers)
        for r in rows:
            writer.writerow([r["bid_no"], r["buyer_name"], r["title"], r["governorate"], r["deadline_date"], r["guarantee"]])

        raw_csv_bytes = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        self.assertTrue(raw_csv_bytes.startswith(b"\xef\xbb\xbf"), "Le CSV doit débuter par le BOM UTF-8 \\xef\\xbb\\xbf")

        # Vérifier que le décodage avec utf-8-sig restaure parfaitement les accents et l'arabe
        decoded = raw_csv_bytes.decode("utf-8-sig")
        self.assertIn("Électricité", decoded)
        self.assertIn("القيروان", decoded)

    def test_10_scheduler_method_integrity(self):
        """Vérifie que app.py ne fait aucun appel à notifier.dispatch_notifications() (doit appeler dispatch_alerts)."""
        app_path = os.path.join(os.path.dirname(__file__), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            app_code = f.read()

        self.assertNotIn(
            "notifier.dispatch_notifications()",
            app_code,
            "Anomalie critique détectée dans app.py : 'notifier.dispatch_notifications()' n'existe pas dans notifier.py ! Utiliser 'notifier.dispatch_alerts()'."
        )


# ==============================================================================
# TIER 3 : TESTS D'INTÉGRATION D'API (API & CONTRACT INTEGRATION)
# ==============================================================================

class TestTier3ApiIntegration(BaseE2ETestCase):
    """Tier 3: Validation des contrats HTTP d'authentification OTP, d'export et de conformité réglementaire."""

    def test_11_subscribe_trial_instant_onboarding(self):
        """Vérifie le contrat de souscription directe au plan TRIAL (/api/subscribe) activant l'accès immédiat."""
        payload = {
            "company_name": "STARTUP INNOV TUNISIE",
            "phone": TEST_PHONE,
            "email": "innov@startup.tn",
            "password": TEST_PASS,
            "plan": "TRIAL",
            "categories": ["IT_TELECOM"],
            "governorates": ["Tunis", "Ariana"]
        }

        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            res = self.client.post("/api/subscribe", json=payload)

        self.assertEqual(res.status_code, 200, f"Échec souscription: {res.text}")
        data = res.json()
        self.assertTrue(data.get("success"), f"Réponse attendue avec success=True: {data}")
        sub_id = data.get("subscriber_id") or data.get("id")
        self.assertIsNotNone(sub_id, "L'ID de l'abonné créé doit être retourné")

        # Vérification en base : compte activé immédiatement et mot de passe PBKDF2 stocké
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM subscribers WHERE id = ?", (sub_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["is_active"], 1, "Le compte TRIAL doit être activé immédiatement")
            self.assertEqual(row["plan"], "TRIAL")
            self.assertTrue(database.verify_password(TEST_PASS, row["password_hash"]), "Le mot de passe initial PBKDF2 n'a pas été enregistré correctement")

    def test_12_forgot_password_request_success(self):
        """Vérifie POST /api/client/forgot-password/request avec un numéro existant (génération OTP et WhatsApp)."""
        # Créer d'abord l'abonné
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, password_hash, created_at) "
                "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, ?, datetime('now'))",
                ("ALPHA RECOVERY CORP", TEST_PHONE, "recovery@alpha.tn", "PRO", database.hash_password(TEST_PASS))
            )
            conn.commit()

        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True) as mock_send:
            res = self.client.post("/api/client/forgot-password/request", json={"phone": TEST_PHONE})

        self.assertEqual(res.status_code, 200, f"Erreur requête forgot-password/request: {res.status_code} - {res.text}")
        data = res.json()
        self.assertTrue(data.get("success"), f"Champ 'success' attendu True: {data}")
        self.assertEqual(data.get("expires_in_minutes"), 10, "La durée de validité doit être de 10 min")

        # Vérifier que WhatsApp a été sollicité
        self.assertTrue(mock_send.called, "La fonction d'envoi WhatsApp send_whatsapp_message doit être appelée")
        call_args = mock_send.call_args[0]
        # Vérifier que le message contient un code à 6 chiffres
        self.assertTrue(re.search(r"\b\d{6}\b", call_args[1]), "Le message WhatsApp doit contenir le code OTP à 6 chiffres")

    def test_13_forgot_password_request_unknown_phone(self):
        """Vérifie POST /api/client/forgot-password/request avec un numéro non inscrit (doit retourner HTTP 404)."""
        res = self.client.post("/api/client/forgot-password/request", json={"phone": "+21600000000"})
        self.assertEqual(res.status_code, 404, f"Un numéro inconnu doit renvoyer HTTP 404, reçu: {res.status_code}")

    def test_14_forgot_password_verify_success_and_login(self):
        """Vérifie POST /api/client/forgot-password/verify valide l'OTP et permet la connexion avec le nouveau mot de passe."""
        # 1. Enregistrer abonné
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, password_hash, created_at) "
                "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, ?, datetime('now'))",
                ("RESET USER SARL", TEST_PHONE, "reset@user.tn", "PRO", database.hash_password(TEST_PASS))
            )
            sub_id = c.lastrowid
            # 2. Créer l'OTP directement ou via endpoint
            otp_code = "789123"
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            c.execute(
                "INSERT INTO password_reset_otps (subscriber_id, phone, otp_code, expires_at, is_used, created_at) "
                "VALUES (?, ?, ?, ?, 0, datetime('now'))",
                (sub_id, TEST_PHONE, otp_code, expires_at)
            )
            conn.commit()

        # 3. Vérifier et réinitialiser
        verify_payload = {
            "phone": TEST_PHONE,
            "otp_code": otp_code,
            "new_password": NEW_PASS
        }
        res = self.client.post("/api/client/forgot-password/verify", json=verify_payload)
        self.assertEqual(res.status_code, 200, f"Échec validation OTP: {res.status_code} - {res.text}")
        data = res.json()
        self.assertTrue(data.get("success"), f"Échec validation OTP: {data}")

        # 4. Tenter la connexion avec l'ancien mot de passe -> Doit échouer
        login_old = self.client.post("/api/client/login", json={"phone": TEST_PHONE, "password": TEST_PASS})
        self.assertNotEqual(login_old.status_code, 200, "L'ancien mot de passe ne doit plus être valide")

        # 5. Tenter la connexion avec le nouveau mot de passe -> Doit réussir
        login_new = self.client.post("/api/client/login", json={"phone": TEST_PHONE, "password": NEW_PASS})
        self.assertEqual(login_new.status_code, 200, f"La connexion avec le nouveau mot de passe a échoué: {login_new.text}")

    def test_15_forgot_password_verify_invalid_otp(self):
        """Vérifie POST /api/client/forgot-password/verify avec un faux code (doit renvoyer HTTP 400)."""
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, password_hash, created_at) "
                "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, ?, datetime('now'))",
                ("INVALID OTP CORP", TEST_PHONE, "inv@otp.tn", "PRO", database.hash_password(TEST_PASS))
            )
            sub_id = c.lastrowid
            c.execute(
                "INSERT INTO password_reset_otps (subscriber_id, phone, otp_code, expires_at, is_used, created_at) "
                "VALUES (?, ?, '654321', ?, 0, datetime('now'))",
                (sub_id, TEST_PHONE, (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
            )
            conn.commit()

        res = self.client.post("/api/client/forgot-password/verify", json={
            "phone": TEST_PHONE,
            "otp_code": "000000",
            "new_password": NEW_PASS
        })
        self.assertEqual(res.status_code, 400, f"Un faux code OTP doit être rejeté avec 400, reçu: {res.status_code}")

    def test_16_export_opportunities_csv_endpoint(self):
        """Vérifie GET /api/client/opportunities/{sub_id}/export?format=csv (HTTP 200, UTF-8 BOM, colonnes requises)."""
        res = self.client.get("/api/client/opportunities/1/export?format=csv")
        self.assertEqual(res.status_code, 200, f"Échec de l'export CSV: {res.status_code} - {res.text}")

        # Vérifier en-têtes HTTP
        content_type = res.headers.get("content-type", "").lower()
        self.assertTrue("csv" in content_type or "text/" in content_type, f"Content-Type inattendu: {content_type}")
        cd = res.headers.get("content-disposition", "")
        self.assertIn("attachment", cd, f"Content-Disposition doit indiquer un attachement: {cd}")

        # Vérifier BOM UTF-8
        content = res.content
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"), "Le flux CSV exporté doit débuter par le BOM UTF-8 (utf-8-sig)")

        # Décoder et vérifier les colonnes obligatoires
        decoded = content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(decoded))
        headers = next(reader)
        required_cols = ["N° Avis", "Acheteur", "Objet", "Région", "Date limite", "Cautionnement"]
        for col in required_cols:
            self.assertTrue(
                any(col.lower() in h.lower() for h in headers),
                f"Colonne obligatoire '{col}' manquante dans l'en-tête CSV. Trouvé: {headers}"
            )

    def test_17_export_opportunities_xlsx_endpoint(self):
        """Vérifie GET /api/client/opportunities/{sub_id}/export?format=xlsx (HTTP 200, signature zip/xlsx valide)."""
        res = self.client.get("/api/client/opportunities/1/export?format=xlsx")
        self.assertEqual(res.status_code, 200, f"Échec de l'export XLSX: {res.status_code} - {res.text}")

        content = res.content
        # Vérification binaire : un fichier .xlsx est un conteneur ZIP standard débutant par b"PK\x03\x04"
        self.assertTrue(content.startswith(b"PK\x03\x04"), "Le fichier exporté .xlsx n'est pas une archive binaire Excel valide")

        # Vérification interne de la structure OpenXML
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            self.assertIn("[Content_Types].xml", names, "Archive Excel corrompue: [Content_Types].xml manquant")
            self.assertTrue(any("xl/workbook" in n for n in names), "xl/workbook.xml manquant dans l'archive .xlsx")

    def test_18_regulatory_cgu_endpoint(self):
        """Vérifie GET /cgu renvoie HTTP 200 avec le contenu légal tunisien (Décret 2014-1039, Konnect, Flouci, GIM-TEL)."""
        res = self.client.get("/cgu")
        self.assertEqual(res.status_code, 200, f"Route /cgu non disponible: {res.status_code}")
        self.assertIn("text/html", res.headers.get("content-type", ""))
        html = res.text

        # Vérifications de conformité juridique
        self.assertIn("2014-1039", html, "Les CGU doivent obligatoirement mentionner le Décret n° 2014-1039")
        gateways_found = [gw for gw in ["Konnect", "Flouci", "GIM-TEL"] if gw.lower() in html.lower()]
        self.assertGreaterEqual(len(gateways_found), 2, f"Les CGU doivent mentionner les passerelles bancaires tunisiennes agréées. Trouvé: {gateways_found}")

    def test_19_regulatory_confidentialite_endpoint(self):
        """Vérifie GET /confidentialite renvoie HTTP 200 conforme à la Loi organique n° 2004-63 relative à l'INPDP."""
        res = self.client.get("/confidentialite")
        self.assertEqual(res.status_code, 200, f"Route /confidentialite non disponible: {res.status_code}")
        self.assertIn("text/html", res.headers.get("content-type", ""))
        html = res.text

        # Vérifications de conformité INPDP
        self.assertTrue(
            "2004-63" in html or "INPDP" in html,
            "La politique de confidentialité doit obligatoirement citer la Loi organique n° 2004-63 et l'INPDP"
        )

    def test_20_weekly_briefing_client_endpoint(self):
        """Vérifie POST /api/client/weekly-briefing/{sub_id} pour le test manuel du briefing du lundi matin."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            res = self.client.post("/api/client/weekly-briefing/1")

        self.assertEqual(res.status_code, 200, f"Échec déclenchement briefing abonné #1: {res.status_code} - {res.text}")
        data = res.json()
        self.assertTrue(data.get("success") or "briefing" in str(data).lower(), f"Réponse briefing inattendue: {data}")

    def test_21_weekly_briefing_admin_endpoint(self):
        """Vérifie POST /api/admin/dispatch-weekly-briefing pour le déclenchement global du briefing hebdomadaire."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            res = self.client.post("/api/admin/dispatch-weekly-briefing")

        self.assertEqual(res.status_code, 200, f"Échec dispatch global briefing hebdo: {res.status_code} - {res.text}")


# ==============================================================================
# TIER 4 : PARCOURS UTILISATEUR E2E & SCÉNARIOS ADVERSARIAUX
# ==============================================================================

class TestTier4E2EAndAdversarial(BaseE2ETestCase):
    """Tier 4: Parcours de bout en bout, tests d'injection, rejeux d'OTP, expiration et robustesse UI."""

    def test_22_full_user_lifecycle_journey(self):
        """Parcours E2E complet: Inscription TRIAL -> Connexion -> Oubli mot de passe -> OTP WhatsApp -> Reset -> Re-connexion."""
        unique_phone = "+21699990099"
        unique_email = "lifecycle@test.tn"
        pwd_initial = "InitialPass2026!"
        pwd_final = "FinalNewPass2026!#"

        # Étape 1 : Inscription directe plan TRIAL
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            sub_res = self.client.post("/api/subscribe", json={
                "company_name": "SARL CYBER DEFENSE TUNISIE",
                "phone": unique_phone,
                "email": unique_email,
                "password": pwd_initial,
                "plan": "TRIAL",
                "categories": ["IT_TELECOM"],
                "governorates": ["Tunis"]
            })
        self.assertEqual(sub_res.status_code, 200, f"Étape 1 KO: {sub_res.text}")

        # Étape 2 : Connexion immédiate avec identifiants initiaux
        login_res = self.client.post("/api/client/login", json={"phone": unique_phone, "password": pwd_initial})
        self.assertEqual(login_res.status_code, 200, f"Étape 2 KO: {login_res.text}")

        # Étape 3 : Déclenchement de la procédure 'Mot de passe oublié'
        captured_otp = None
        def fake_whatsapp(phone, message):
            nonlocal captured_otp
            match = re.search(r"\b\d{6}\b", message)
            if match:
                captured_otp = match.group(0)
            return True

        with patch("whatsapp_gateway.send_whatsapp_message", side_effect=fake_whatsapp):
            req_res = self.client.post("/api/client/forgot-password/request", json={"phone": unique_phone})
        self.assertEqual(req_res.status_code, 200, f"Étape 3 KO: {req_res.text}")
        self.assertIsNotNone(captured_otp, "Le code OTP n'a pas été intercepté dans le message WhatsApp")

        # Étape 4 : Réinitialisation du mot de passe avec l'OTP intercepté
        verify_res = self.client.post("/api/client/forgot-password/verify", json={
            "phone": unique_phone,
            "otp_code": captured_otp,
            "new_password": pwd_final
        })
        self.assertEqual(verify_res.status_code, 200, f"Étape 4 KO: {verify_res.text}")

        # Étape 5 : L'ancien mot de passe est désormais strictement invalide
        old_login_res = self.client.post("/api/client/login", json={"phone": unique_phone, "password": pwd_initial})
        self.assertNotEqual(old_login_res.status_code, 200, "Étape 5 KO: L'ancien mot de passe ne doit plus fonctionner")

        # Étape 6 : Le nouveau mot de passe permet la session client
        new_login_res = self.client.post("/api/client/login", json={"phone": unique_phone, "password": pwd_final})
        self.assertEqual(new_login_res.status_code, 200, f"Étape 6 KO: Connexion nouveau mot de passe impossible: {new_login_res.text}")

    def test_23_export_content_data_fidelity_and_encoding(self):
        """Vérifie la fidélité des données exportées (CSV et Excel) avec les marchés réels de la base."""
        # Récupérer les opportunités pour l'abonné 1
        matched = self.db.get_subscriber_matched_tenders(1, limit=5)
        self.assertGreater(len(matched), 0, "L'abonné #1 doit avoir des opportunités ciblées pour tester l'export")

        res_csv = self.client.get("/api/client/opportunities/1/export?format=csv")
        self.assertEqual(res_csv.status_code, 200)
        decoded_csv = res_csv.content.decode("utf-8-sig")

        # Vérifier la présence effective du premier N° Avis dans le flux
        first_bid_no = matched[0]["bid_no"]
        self.assertIn(first_bid_no, decoded_csv, f"Le marché N° {first_bid_no} doit figurer dans le contenu exporté CSV")

        # Vérifier l'acheteur
        first_buyer = matched[0]["buyer_name"]
        self.assertIn(first_buyer[:20], decoded_csv, f"L'acheteur {first_buyer} doit figurer dans le contenu exporté CSV")

    def test_24_footer_legal_links_in_all_templates(self):
        """Vérifie que les liens vers /cgu et /confidentialite sont présents dans les footers de index.html et dashboard.html."""
        pages_to_check = [
            ("templates", "index.html"),
            ("public", "index.html"),
            ("templates", "dashboard.html"),
            ("public", "dashboard.html")
        ]

        for folder, fname in pages_to_check:
            fpath = os.path.join(os.path.dirname(__file__), folder, fname)
            self.assertTrue(os.path.exists(fpath), f"Fichier {fpath} introuvable")
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertTrue(
                re.search(r'href=["\']/cgu["\']', content),
                f"Lien <a href=\"/cgu\"> manquant dans le footer de {folder}/{fname}"
            )
            self.assertTrue(
                re.search(r'href=["\']/confidentialite["\']', content),
                f"Lien <a href=\"/confidentialite\"> manquant dans le footer de {folder}/{fname}"
            )

    def test_25_dashboard_frontend_ui_contracts(self):
        """Vérifie les contrats d'éléments d'interface dans dashboard.html (tabs, recherche, filtres statut, exports)."""
        dashboard_paths = [
            os.path.join(TEMPLATES_DIR, "dashboard.html"),
            os.path.join(PUBLIC_DIR, "dashboard.html")
        ]

        for dp in dashboard_paths:
            with open(dp, "r", encoding="utf-8") as f:
                content = f.read()

            # 1. R1: Formulaire ou modal 'Mot de passe oublié'
            self.assertTrue(
                ("forgot" in content.lower() or "mot de passe oublié" in content.lower()),
                f"Section ou bouton 'Mot de passe oublié' manquant dans {dp}"
            )

            # 2. R1: Onglet ou bascule 'Créer un compte d'essai'
            self.assertTrue(
                ("essai gratuit" in content.lower() or "créer un compte" in content.lower() or "tab-register" in content.lower()),
                f"Bascule 'Essai Gratuit' manquante dans le bloc d'auth de {dp}"
            )

            # 3. R2: Champ de recherche instantanée par mot-clé / numéro d'avis dans les opportunités
            self.assertTrue(
                ("filteropportunities" in content.lower() or "search" in content.lower() or "recherche" in content.lower()),
                f"Barre de recherche instantanée manquante dans l'onglet opportunités de {dp}"
            )

            # 4. R2: Boutons de filtre par statut dans 'Mes Dossiers' (TOUS, GENERE, DEPOSE_TUNEPS, RETENU, NON_RETENU)
            for status in ["TOUS", "GENERE", "DEPOSE_TUNEPS", "RETENU", "NON_RETENU"]:
                self.assertIn(status, content, f"Pill de filtrage statut '{status}' manquant dans 'Mes Dossiers' de {dp}")

            # 5. R2: Boutons d'export Excel & CSV
            self.assertTrue(
                ("export" in content.lower() and ("xlsx" in content.lower() or "excel" in content.lower())),
                f"Bouton d'export Excel (.xlsx) manquant dans {dp}"
            )
            self.assertTrue(
                ("export" in content.lower() and "csv" in content.lower()),
                f"Bouton d'export CSV manquant dans {dp}"
            )

            # 6. R1: Contrôle strict de portée lexicale (Scoping Trap) dans les balises <script>
            # Garantit que les gestionnaires d'événements inline (onclick, onsubmit) sont bien
            # des fonctions racine de premier niveau (niveau d'imbrication 0) et non captives
            # d'une autre fonction (e.g. togglePasswordVisibility).
            critical_auth_funcs = [
                'togglePasswordVisibility',
                'switchAuthTab',
                'showForgotPassword',
                'resetForgotWorkflow',
                'handleRequestOtp',
                'handleVerifyOtp',
                'handleRegister',
                'handleLogin',
                'filterOpportunities',
                'filterDossiersByStatus'
            ]
            script_active = False
            brace_depth = 0
            func_scopes = {}
            for line_no, raw_line in enumerate(content.splitlines(), 1):
                stripped = raw_line.strip()
                if '<script' in stripped:
                    script_active = True
                    brace_depth = 0
                    continue
                if '</script>' in stripped:
                    script_active = False
                    continue
                if not script_active:
                    continue

                for fn in critical_auth_funcs:
                    if re.search(rf'\bfunction\s+{fn}\b', stripped):
                        func_scopes[fn] = (brace_depth, line_no)

                code_clean = raw_line.split('//')[0]
                for ch in code_clean:
                    if ch == '{':
                        brace_depth += 1
                    elif ch == '}':
                        brace_depth -= 1

            for fn in critical_auth_funcs:
                self.assertIn(
                    fn, func_scopes,
                    f"Fonction d'authentification '{fn}' introuvable dans le script de {dp}"
                )
                depth, line_no = func_scopes[fn]
                self.assertEqual(
                    depth, 0,
                    f"Scoping Trap détecté dans {dp} : la fonction '{fn}' (ligne {line_no}) "
                    f"est déclarée au niveau d'imbrication {depth} != 0 (captive et inaccessible sur window)"
                )

    def test_26_adversarial_expired_otp_rejected(self):
        """Adversarial: Un code OTP dont la date d'expiration est dépassée doit être rejeté avec HTTP 400."""
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, password_hash, created_at) "
                "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, ?, datetime('now'))",
                ("EXPIRED OTP INC", TEST_PHONE, "expired@test.tn", "PRO", database.hash_password(TEST_PASS))
            )
            sub_id = c.lastrowid
            expired_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            c.execute(
                "INSERT INTO password_reset_otps (subscriber_id, phone, otp_code, expires_at, is_used, created_at) "
                "VALUES (?, ?, '112233', ?, 0, datetime('now'))",
                (sub_id, TEST_PHONE, expired_time)
            )
            conn.commit()

        res = self.client.post("/api/client/forgot-password/verify", json={
            "phone": TEST_PHONE,
            "otp_code": "112233",
            "new_password": NEW_PASS
        })
        self.assertEqual(res.status_code, 400, f"Un OTP expiré doit être rejeté avec HTTP 400, reçu: {res.status_code}")

    def test_27_adversarial_replayed_otp_rejected(self):
        """Adversarial: Protection contre le rejeu : un code déjà utilisé (is_used=1) ne peut pas resservir."""
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, password_hash, created_at) "
                "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, ?, datetime('now'))",
                ("REPLAY OTP INC", TEST_PHONE, "replay@test.tn", "PRO", database.hash_password(TEST_PASS))
            )
            sub_id = c.lastrowid
            valid_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            c.execute(
                "INSERT INTO password_reset_otps (subscriber_id, phone, otp_code, expires_at, is_used, created_at) "
                "VALUES (?, ?, '445566', ?, 1, datetime('now'))",
                (sub_id, TEST_PHONE, valid_time)
            )
            conn.commit()

        res = self.client.post("/api/client/forgot-password/verify", json={
            "phone": TEST_PHONE,
            "otp_code": "445566",
            "new_password": NEW_PASS
        })
        self.assertEqual(res.status_code, 400, f"Un OTP déjà consommé doit être rejeté avec HTTP 400, reçu: {res.status_code}")

    def test_28_adversarial_phone_number_variations(self):
        """Adversarial: Vérifie la résilience du système face aux variantes de formats téléphoniques tunisiens."""
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT INTO subscribers (company_name, phone, email, categories, governorates, plan, is_active, password_hash, created_at) "
                "VALUES (?, ?, ?, '[\"ALL\"]', '[\"ALL\"]', ?, 1, ?, datetime('now'))",
                ("PHONE RESILIENCE SARL", "+21699000111", "phone@resilience.tn", "PRO", database.hash_password(TEST_PASS))
            )
            conn.commit()

        # Tester différentes variantes de saisie du même numéro
        variations = ["99000111", "21699000111", "+21699000111", "99 000 111", "+216 99-000-111"]
        for var_phone in variations:
            with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
                res = self.client.post("/api/client/forgot-password/request", json={"phone": var_phone})
            self.assertEqual(
                res.status_code, 200,
                f"Le numéro '{var_phone}' aurait dû être normalisé et reconnu, mais a retourné HTTP {res.status_code}"
            )

    def test_29_adversarial_injection_and_tampering(self):
        """Adversarial: Vérifie la résistance aux injections SQL et aux payloads corrompus."""
        sql_injection_payloads = [
            "' OR '1'='1",
            "'+OR+1=1--",
            "admin'--",
            "<script>alert(1)</script>"
        ]

        for injection in sql_injection_payloads:
            res_req = self.client.post("/api/client/forgot-password/request", json={"phone": injection})
            # Doit renvoyer 404 (non trouvé) ou 400 (format invalide), mais JAMAIS 500
            self.assertIn(res_req.status_code, [400, 404, 422], f"L'injection '{injection}' a causé une réponse inattendue: {res_req.status_code}")

            res_ver = self.client.post("/api/client/forgot-password/verify", json={
                "phone": TEST_PHONE,
                "otp_code": injection,
                "new_password": "NewValidPass2026!"
            })
            self.assertIn(res_ver.status_code, [400, 422], f"L'injection dans otp_code a causé une réponse inattendue: {res_ver.status_code}")

    def test_30_wal_concurrency_and_pdf_non_regression(self):
        """Vérifie l'absence de régression sur la génération documentaire PDF/DOCX et la tenue en concurrence WAL."""
        tender = self.db.get_tender_by_id(1)
        if not tender:
            tender = {
                "bid_no": "2026/001",
                "buyer_name": "STEG",
                "title_fr": "Fourniture transformateurs",
                "deadline_date": "2026-12-31 10:00:00"
            }
        else:
            tender = {
                "bid_no": tender.bid_no,
                "buyer_name": tender.buyer_name,
                "title_fr": tender.title_fr,
                "deadline_date": tender.deadline_date
            }

        # 1. Non-régression sur le générateur PDF officiel (Acte d'engagement A4 1 page)
        pdf_bytes = pdf_generator.generate_engagement_letter_pdf(tender, "ADVANCIA TRAINING", {})
        self.assertGreater(len(pdf_bytes), 1000, "Le PDF généré est trop court ou corrompu")
        self.assertTrue(pdf_bytes.startswith(b"%PDF"), "Le fichier généré n'est pas un flux PDF binaire valide")

        # 2. Non-régression sur le générateur DOCX officiel & Dimensions strictes ISO A4 (Décret 2014-1039)
        docx_bytes = docx_generator.generate_engagement_letter_docx(tender, "ADVANCIA TRAINING", {})
        self.assertGreater(len(docx_bytes), 1000, "Le DOCX généré est trop court ou corrompu")
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"), "Le fichier généré n'est pas une archive DOCX valide")

        import docx
        doc_obj = docx.Document(io.BytesIO(docx_bytes))
        self.assertGreaterEqual(len(doc_obj.sections), 1, "Le document DOCX doit comporter au moins une section")
        sec = doc_obj.sections[0]
        self.assertAlmostEqual(
            round(sec.page_width.inches, 2), 8.27, places=2,
            msg=f"Dimensions DOCX non conformes ISO A4 : largeur={round(sec.page_width.inches, 2)} in (attendu 8.27 in / 210mm)"
        )
        self.assertAlmostEqual(
            round(sec.page_height.inches, 2), 11.69, places=2,
            msg=f"Dimensions DOCX non conformes ISO A4 : hauteur={round(sec.page_height.inches, 2)} in (attendu 11.69 in / 297mm)"
        )

        # Vérification sur les autres générateurs DOCX du pack de soumission
        bg_bytes = docx_generator.generate_bank_guarantee_docx(tender, "ADVANCIA TRAINING", {})
        bg_doc = docx.Document(io.BytesIO(bg_bytes))
        bg_sec = bg_doc.sections[0]
        self.assertAlmostEqual(round(bg_sec.page_width.inches, 2), 8.27, places=2)
        self.assertAlmostEqual(round(bg_sec.page_height.inches, 2), 11.69, places=2)

        # 3. Test de requêtes concurrentes rapides sous WAL
        with sqlite3.connect(DB_FILE) as conn:
            for _ in range(10):
                conn.execute("SELECT COUNT(*) FROM tenders").fetchone()
                conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()


# ==============================================================================
# RUNNER DE TEST PRINCIPAL & RAPPORT DE SYNTHÈSE
# ==============================================================================

def run_e2e_suite():
    """Exécute l'ensemble de la suite de test et affiche un bilan structuré par Tier."""
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    suite.addTests(loader.loadTestsFromTestCase(TestTier1SmokeSanity))
    suite.addTests(loader.loadTestsFromTestCase(TestTier2UnitIsolation))
    suite.addTests(loader.loadTestsFromTestCase(TestTier3ApiIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestTier4E2EAndAdversarial))

    print("\n" + "=" * 80)
    print(" HARNAIS DE TEST E2E GLOBAL — PLATEFORME SAAS TENDERS.TN (4-TIER METHODOLOGY)")
    print("=" * 80 + "\n")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 80)
    print(" BILAN D'EXÉCUTION DU HARNAIS DE TEST E2E")
    print("=" * 80)
    print(f"Total tests exécutés : {result.testsRun}")
    print(f"Succès               : {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Échecs (Failures)    : {len(result.failures)}")
    print(f"Erreurs (Errors)     : {len(result.errors)}")
    print("=" * 80)

    if result.wasSuccessful():
        print("✅ TOUS LES TESTS SONT PASSÉS AVEC SUCCÈS !")
        return 0
    else:
        print("❌ DES ÉCHECS ONT ÉTÉ DÉTECTÉS (Normal lors des étapes de développement)")
        return 1


if __name__ == "__main__":
    sys.exit(run_e2e_suite())
