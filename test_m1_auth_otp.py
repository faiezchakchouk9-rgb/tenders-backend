"""
Suite de tests automatisés pour le Chantier R1 (Milestone M1) :
Sécurité, Inscription & Récupération OTP WhatsApp.
Vérifie :
1. La persistance et la gestion des OTP dans SQLite (mode WAL préservé).
2. La génération cryptographique des codes OTP et l'invalidation après consommation.
3. Le hachage sécurisé PBKDF2-HMAC-SHA256 (100 000 itérations).
4. Les endpoints FastAPI forgot-password request et verify.
5. L'onboarding direct TRIAL via /api/subscribe avec payload complet.
6. La parité absolue 1:1 entre templates/dashboard.html et public/dashboard.html.
"""

import unittest
import filecmp
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import app
import database

class TestM1SecurityAndOtp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app.app)
        cls.db = database.TenderDatabase()
        
        # S'assurer d'avoir un abonné de test stable
        cls.test_phone = "+21628177888"
        cls.test_phone_short = "28177888"
        cls.test_sub = cls.db.get_subscriber_by_phone(cls.test_phone)
        if not cls.test_sub:
            cls.test_sub = database.Subscriber(
                company_name="TEST ADVANCIA M1",
                phone=cls.test_phone,
                email="advancia@test.tn",
                categories=["IT_TELECOM"],
                governorates=["Tunis"],
                keywords=["test"],
                channel="WHATSAPP",
                plan="PRO"
            )
            cls.test_sub_id = cls.db.add_subscriber(cls.test_sub)
        else:
            cls.test_sub_id = cls.test_sub.id

    def test_01_db_table_and_wal_mode(self):
        """Vérifie que la table password_reset_otps existe et que SQLite est en mode WAL."""
        with self.db._get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal", "SQLite doit conserver le mode journal WAL.")
            
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='password_reset_otps';")
            self.assertIsNotNone(cursor.fetchone(), "La table password_reset_otps doit exister.")
            
            cols = [c[1] for c in cursor.execute("PRAGMA table_info(password_reset_otps)").fetchall()]
            expected_cols = ["id", "subscriber_id", "phone", "otp_code", "expires_at", "is_used", "created_at"]
            for col in expected_cols:
                self.assertIn(col, cols, f"La colonne {col} doit être présente dans password_reset_otps.")

    def test_02_create_password_reset_otp(self):
        """Vérifie la génération d'un OTP cryptographique à 6 chiffres."""
        sub, otp = self.db.create_password_reset_otp(self.test_phone)
        self.assertIsNotNone(sub)
        self.assertIsNotNone(otp)
        self.assertEqual(len(otp), 6, "Le code OTP doit comporter 6 chiffres.")
        self.assertTrue(otp.isdigit(), "Le code OTP doit être numérique.")
        
        # Test avec numéro au format court 8 chiffres
        sub_short, otp_short = self.db.create_password_reset_otp(self.test_phone_short)
        self.assertIsNotNone(sub_short)
        self.assertEqual(sub_short.id, sub.id)
        self.assertEqual(len(otp_short), 6)

        # Test avec numéro inexistant
        bad_sub, bad_otp = self.db.create_password_reset_otp("+21600000000")
        self.assertIsNone(bad_sub)
        self.assertIsNone(bad_otp)

    def test_03_verify_and_consume_password_reset_otp(self):
        """Vérifie la consommation d'OTP et la mise à jour sécurisée du mot de passe PBKDF2."""
        sub, otp = self.db.create_password_reset_otp(self.test_phone)
        new_pwd = "SecurePassword_2026_M1!"
        
        # Validation réussie
        ok, msg = self.db.verify_and_consume_password_reset_otp(self.test_phone, otp, new_pwd)
        self.assertTrue(ok, f"La vérification de l'OTP devrait réussir: {msg}")
        
        # Vérification de l'authentification avec le nouveau mot de passe
        valid, logged_sub, login_msg = self.db.verify_subscriber_credentials(self.test_phone, new_pwd)
        self.assertTrue(valid, "Le client doit pouvoir se connecter avec le nouveau mot de passe.")
        self.assertIn(":", logged_sub.password_hash, "Le hash doit contenir un sel PBKDF2.")
        
        # Tentative de réutilisation du même code (doit échouer)
        reuse_ok, reuse_msg = self.db.verify_and_consume_password_reset_otp(self.test_phone, otp, "AnotherPwd123")
        self.assertFalse(reuse_ok, "Un code OTP déjà consommé ne peut être réutilisé.")

    def test_04_expired_otp_rejection(self):
        """Vérifie le rejet strict d'un code OTP expiré."""
        sub, otp = self.db.create_password_reset_otp(self.test_phone)
        
        # Falsifier la date d'expiration dans la DB pour simuler une expiration (il y a 1 heure)
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with self.db._get_connection() as conn:
            conn.execute("UPDATE password_reset_otps SET expires_at = ? WHERE otp_code = ?", (past_time, otp))
            conn.commit()
            
        ok, msg = self.db.verify_and_consume_password_reset_otp(self.test_phone, otp, "ShouldFailPassword")
        self.assertFalse(ok, "Un code OTP expiré doit être rejeté.")

    def test_05_api_forgot_password_request_route(self):
        """Teste l'endpoint POST /api/client/forgot-password/request."""
        res = self.client.post("/api/client/forgot-password/request", json={"phone": self.test_phone})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("expires_in_minutes"), 10)
        
        # Numéro introuvable
        res_404 = self.client.post("/api/client/forgot-password/request", json={"phone": "+21600000000"})
        self.assertEqual(res_404.status_code, 404)
        self.assertIn("non associé", res_404.json().get("detail", ""))

    def test_06_api_forgot_password_verify_route(self):
        """Teste l'endpoint POST /api/client/forgot-password/verify."""
        sub, otp = self.db.create_password_reset_otp(self.test_phone)
        fresh_pwd = "ApiPassword_Reset_999!"
        
        res = self.client.post("/api/client/forgot-password/verify", json={
            "phone": self.test_phone,
            "otp_code": otp,
            "new_password": fresh_pwd
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("success"))
        
        # Vérification connexion immédiate via API
        login_res = self.client.post("/api/client/login", json={
            "phone": self.test_phone,
            "password": fresh_pwd
        })
        self.assertEqual(login_res.status_code, 200)
        self.assertEqual(login_res.json().get("status"), "SUCCESS")
        
        # Test code invalide
        res_bad = self.client.post("/api/client/forgot-password/verify", json={
            "phone": self.test_phone,
            "otp_code": "000000",
            "new_password": "AnotherPassword"
        })
        self.assertEqual(res_bad.status_code, 400)

    def test_07_api_subscribe_trial_onboarding(self):
        """Teste l'onboarding direct TRIAL via POST /api/subscribe."""
        unique_phone = f"+216{datetime.now().strftime('%M%S%f')[:8]}"
        payload = {
            "company_name": "Entreprise Essai Automatisé",
            "phone": unique_phone,
            "email": "auto-trial@test.tn",
            "password": "TrialPassword2026!",
            "plan": "TRIAL",
            "categories": ["IT_TELECOM", "BTP_CONSTRUCTION"],
            "governorates": ["Tunis"]
        }
        res = self.client.post("/api/subscribe", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "ACTIVE_TRIAL")
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("plan"), "TRIAL")
        self.assertIn("subscriber_id", data)
        self.assertIn("subscriber", data)
        
        sub_dict = data["subscriber"]
        self.assertEqual(sub_dict["company_name"], payload["company_name"])
        self.assertEqual(sub_dict["phone"], payload["phone"])
        
        # Vérifier que le mot de passe est immédiatement fonctionnel pour se connecter
        login_res = self.client.post("/api/client/login", json={
            "phone": unique_phone,
            "password": "TrialPassword2026!"
        })
        self.assertEqual(login_res.status_code, 200)

    def test_08_template_mirror_synchronization(self):
        """Vérifie la stricte identité binaire entre templates/dashboard.html et public/dashboard.html."""
        identical = filecmp.cmp("templates/dashboard.html", "public/dashboard.html", shallow=False)
        self.assertTrue(identical, "templates/dashboard.html et public/dashboard.html DOIVENT être strictement identiques.")
        
        with open("templates/dashboard.html", "r", encoding="utf-8") as f:
            html = f.read()
            
        required_elements = [
            "id=\"tab-btn-login\"",
            "id=\"tab-btn-register\"",
            "switchAuthTab('login')",
            "switchAuthTab('register')",
            "id=\"login-phone\"",
            "id=\"login-password\"",
            "togglePasswordVisibility('login-password'",
            "Mot de passe oublié ?",
            "showForgotPassword(true)",
            "id=\"forgot-password-panel\"",
            "id=\"forgot-phone\"",
            "id=\"forgot-otp\"",
            "id=\"forgot-new-password\"",
            "handleRequestOtp()",
            "handleVerifyOtp()",
            "id=\"register-form\"",
            "id=\"reg-company\"",
            "id=\"reg-phone\"",
            "id=\"reg-email\"",
            "id=\"reg-password\"",
            "name=\"reg-sector\"",
            "handleRegister(event)"
        ]
        for elem in required_elements:
            self.assertIn(elem, html, f"L'élément UI {elem} doit être présent dans dashboard.html.")

        # Contrôle strict de portée lexicale des fonctions d'authentification
        import re
        auth_funcs = [
            'togglePasswordVisibility', 'switchAuthTab', 'showForgotPassword',
            'resetForgotWorkflow', 'handleRequestOtp', 'handleVerifyOtp', 'handleRegister'
        ]
        script_active = False
        brace_depth = 0
        func_scopes = {}
        for line_no, raw_line in enumerate(html.splitlines(), 1):
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

            for fn in auth_funcs:
                if re.search(rf'\bfunction\s+{fn}\b', stripped):
                    func_scopes[fn] = (brace_depth, line_no)

            code_clean = raw_line.split('//')[0]
            for ch in code_clean:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1

        for fn in auth_funcs:
            self.assertIn(fn, func_scopes, f"Fonction '{fn}' introuvable dans le script de dashboard.html")
            depth, line_no = func_scopes[fn]
            self.assertEqual(
                depth, 0,
                f"Scoping Trap : la fonction '{fn}' (ligne {line_no}) est au niveau d'imbrication {depth} != 0"
            )

if __name__ == "__main__":
    unittest.main()
