"""
Tests Unitaires & Intégration Dédiés au Chantier M4 :
- Formatage enrichi des alertes WhatsApp (liens directs TUNEPS et Dossier de soumission)
- Briefing hebdomadaire du lundi matin (send_weekly_briefing)
- Endpoints client et admin
- Journalisation notification_logs avec le canal WHATSAPP_WEEKLY
"""

import os
import unittest
import sqlite3
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import database
import notifier
import app

DB_FILE = os.path.join(os.path.dirname(__file__), "tenders.db")

class TestM4AlertesEtBriefingHebdo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = database.TenderDatabase(db_path=DB_FILE)
        cls.client = TestClient(app.app)
        cls.notifier = notifier.TenderNotifier(db=cls.db)

    def test_whatsapp_alert_link_enrichment_format(self):
        """Vérifie que format_whatsapp_message contient bien les liens TUNEPS et dossier de soumission."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenders LIMIT 1")
            row = cursor.fetchone()
            tender = database.TenderNotice(**dict(row))

        sub = database.Subscriber(
            company_name="TEST ENRICHMENT SARL",
            phone="+21628177888",
            email="contact@test.tn",
            categories=["ALL"],
            governorates=["ALL"],
            keywords=[],
            id=1
        )

        msg = self.notifier.format_whatsapp_message(tender, sub)

        # Vérification des liens
        self.assertIn("🔗 *Fiche officielle TUNEPS :*", msg)
        self.assertIn(tender.url, msg)
        self.assertIn("📂 *Dossier de soumission Tenders.tn :*", msg)
        self.assertIn("tab=dossiers", msg)
        self.assertIn(f"tender={tender.ep_bid_master_id}", msg)
        self.assertIn("Dossier de soumission", msg)

    def test_send_weekly_briefing_single_subscriber(self):
        """Vérifie send_weekly_briefing pour un seul abonné avec journalisation WHATSAPP_WEEKLY."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True) as mock_send:
            res = self.notifier.send_weekly_briefing(subscriber_id=1)

        self.assertTrue(res.get("success"))
        self.assertGreaterEqual(res.get("briefings_sent", 0), 1)
        self.assertEqual(res.get("subscribers_targeted"), 1)
        self.assertTrue(mock_send.called)

        call_args = mock_send.call_args[0]
        sent_phone, sent_text = call_args[0], call_args[1]
        self.assertIn("BRIEFING HEBDOMADAIRE TENDERS.TN — LUNDI MATIN", sent_text)
        self.assertIn("Dossier de soumission", sent_text)
        self.assertIn("tab=dossiers", sent_text)

        # Vérifier l'insertion dans notification_logs
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM notification_logs WHERE subscriber_id = 1 AND channel = 'WHATSAPP_WEEKLY' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row, "Log manquant dans notification_logs pour WHATSAPP_WEEKLY")
            self.assertEqual(row["status"], "SENT")

    def test_send_weekly_briefing_all_subscribers(self):
        """Vérifie send_weekly_briefing pour l'ensemble des abonnés actifs."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            res = self.notifier.send_weekly_briefing()

        self.assertTrue(res.get("success"))
        self.assertGreaterEqual(res.get("subscribers_targeted", 0), 1)

    def test_send_weekly_briefing_invalid_subscriber_graceful(self):
        """Vérifie le comportement robuste si l'ID d'abonné est inexistant."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            res = self.notifier.send_weekly_briefing(subscriber_id=999999)

        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("briefings_sent"), 0)
        self.assertEqual(res.get("subscribers_targeted"), 0)

    def test_api_client_weekly_briefing_endpoint(self):
        """Vérifie l'endpoint HTTP POST /api/client/weekly-briefing/{sub_id}."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            response = self.client.post("/api/client/weekly-briefing/1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(data.get("briefings_sent", 0), 1)

    def test_api_admin_dispatch_weekly_briefing_endpoint(self):
        """Vérifie l'endpoint HTTP POST /api/admin/dispatch-weekly-briefing."""
        with patch("whatsapp_gateway.send_whatsapp_message", return_value=True):
            response = self.client.post("/api/admin/dispatch-weekly-briefing")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))


if __name__ == "__main__":
    unittest.main()
