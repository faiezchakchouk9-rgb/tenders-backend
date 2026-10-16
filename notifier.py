"""
Moteur de Matching et Dispatch de Notifications (WhatsApp & Telegram).
Associe chaque appel d'offres qualifié aux critères des PME abonnées
et transmet des alertes instantanées à forte valeur ajoutée.
"""
import os
import sys
import json
import logging
import requests
from typing import List, Dict, Any, Tuple
from datetime import datetime
from database import TenderDatabase, TenderNotice, Subscriber

# Import Telegram optionnel (plateforme 100% WhatsApp)
try:
    from telegram_bot import send_telegram_message, load_telegram_config
except ImportError:
    def send_telegram_message(*args, **kwargs): pass
    def load_telegram_config(): return {}

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("TenderNotifier")

class TenderNotifier:
    def __init__(self, db: TenderDatabase = None):
        self.db = db or TenderDatabase()
        # Clés API WhatsApp (Meta Cloud API)
        self.wa_token = os.getenv("WHATSAPP_API_TOKEN")
        self.wa_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        # Configuration Telegram
        self.tg_config = load_telegram_config()

    def is_match(self, tender: TenderNotice, sub: Subscriber) -> bool:
        """
        Vérifie si un appel d'offres correspond au profil de l'abonné :
        1. Catégorie sectorielle
        2. Portée géographique / Gouvernorat
        3. Mots-clés optionnels
        """
        # 1. Vérification Catégorie
        if "ALL" not in sub.categories and tender.category not in sub.categories:
            return False

        # 2. Vérification Géographique
        if "ALL" not in sub.governorates:
            allowed_govs = [g.lower() for g in sub.governorates]
            tender_gov = (tender.governorate or "").lower()
            if tender_gov not in allowed_govs and "national" not in tender_gov:
                return False

        # 3. Vérification Mots-clés (si l'abonné en a spécifié)
        if sub.keywords and len(sub.keywords) > 0:
            corpus = f"{tender.title_fr or ''} {tender.title_ar or ''} {tender.tags or ''}".lower()
            if not any(kw.lower() in corpus for kw in sub.keywords):
                return False

        return True

    def format_whatsapp_message(self, tender: TenderNotice, sub: Subscriber) -> str:
        """Génère le message WhatsApp formatté avec les conditions de soumission."""
        title = tender.title_fr or tender.title_ar or "Sans titre"
        tags_list = json.loads(tender.tags) if tender.tags else []
        tags_str = " ".join([f"#{t}" for t in tags_list]) if tags_list else "#MarchéPublic"

        # Conditions de soumission TUNEPS-3
        conditions = []
        if tender.eval_method:
            conditions.append(f"• *Critère :* {tender.eval_method}")
        if tender.guarantee_type:
            conditions.append(f"• *Cautionnement :* {tender.guarantee_type}")
        if tender.doc_price:
            conditions.append(f"• *Cahier des charges :* {tender.doc_price}")
        if tender.execution_place:
            conditions.append(f"• *Lieu officiel :* {tender.execution_place}")
        if tender.opening_date:
            conditions.append(f"• *Ouverture des plis :* {tender.opening_date}")
        if tender.is_online:
            conditions.append(f"• *Mode de dépôt :* {tender.is_online}")

        conditions_block = ""
        if conditions:
            conditions_block = "📋 *Conditions de soumission :*\n" + "\n".join(conditions) + "\n\n"

        msg = (
            f"🔔 *NOUVEL APPEL D'OFFRES TUNEPS* 🇹🇳\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 *Secteur :* {tender.category or 'Général'}\n"
            f"🏢 *Acheteur :* {tender.buyer_name}\n"
            f"📍 *Région :* {tender.governorate or 'National'}\n"
            f"📋 *Objet :* {title}\n"
            f"⏳ *Date limite dépôt :* {tender.deadline_date or 'Consulter l avis'}\n"
            f"🏷️ *Tags :* {tags_str}\n\n"
            f"{conditions_block}"
            f"💡 *Synthèse IA :*\n{tender.ai_summary or 'Avis officiel disponible'}\n\n"
            f"🔗 *Consulter l'avis sur TUNEPS :*\n{tender.url}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Alerte envoyée à {sub.company_name}_"
        )
        return msg

    def format_telegram_message(self, tender: TenderNotice, sub: Subscriber) -> str:
        """Génère le message HTML optimisé pour l'application Telegram."""
        title = tender.title_fr or tender.title_ar or "Sans titre"
        tags_list = json.loads(tender.tags) if tender.tags else []
        tags_str = " ".join([f"#{t}" for t in tags_list]) if tags_list else "#MarchePublic"

        conditions = []
        if tender.eval_method:
            conditions.append(f"• <b>Critère :</b> {tender.eval_method}")
        if tender.guarantee_type:
            conditions.append(f"• <b>Cautionnement :</b> {tender.guarantee_type}")
        if tender.doc_price:
            conditions.append(f"• <b>Cahier des charges :</b> {tender.doc_price}")
        if tender.execution_place:
            conditions.append(f"• <b>Lieu officiel :</b> {tender.execution_place}")
        if tender.opening_date:
            conditions.append(f"• <b>Ouverture des plis :</b> <code>{tender.opening_date}</code>")
        if tender.is_online:
            conditions.append(f"• <b>Mode de dépôt :</b> {tender.is_online}")

        conditions_block = ""
        if conditions:
            conditions_block = "📋 <b>Conditions de soumission :</b>\n" + "\n".join(conditions) + "\n\n"

        msg = (
            f"🔔 <b>NOUVEL APPEL D'OFFRES TUNEPS</b> 🇹🇳\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 <b>Secteur :</b> {tender.category or 'Général'}\n"
            f"🏢 <b>Acheteur :</b> {tender.buyer_name}\n"
            f"📍 <b>Région :</b> {tender.governorate or 'National'}\n"
            f"📋 <b>Objet :</b> {title}\n"
            f"⏳ <b>Date limite dépôt :</b> <code>{tender.deadline_date or 'Consulter l avis'}</code>\n"
            f"🏷️ <b>Tags :</b> {tags_str}\n\n"
            f"{conditions_block}"
            f"💡 <b>Synthèse IA :</b>\n<i>{tender.ai_summary or 'Avis officiel disponible'}</i>\n\n"
            f"🔗 <a href='{tender.url}'>Consulter la fiche officielle TUNEPS</a>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Alerte en direct transmise à {sub.company_name}</i>"
        )
        return msg

    def send_whatsapp(self, phone: str, message: str) -> bool:
        from whatsapp_gateway import send_whatsapp_message
        return send_whatsapp_message(phone, message)


    def dispatch_alerts(self, limit: int = 50) -> Dict[str, int]:
        tenders = self.db.get_unnotified_tenders(limit=limit)
        subscribers = self.db.get_active_subscribers()
        tg_conf = load_telegram_config()

        if not tenders:
            logger.info("Aucun nouvel appel d'offres en attente de notification.")
            return {"tenders_processed": 0, "notifications_sent": 0}

        if not subscribers:
            logger.warning("Aucun abonné actif trouvé en base de données.")
            return {"tenders_processed": len(tenders), "notifications_sent": 0}

        logger.info(f"Démarrage du matching : {len(tenders)} avis x {len(subscribers)} abonnés actifs...")
        sent_count = 0

        for tender in tenders:
            for sub in subscribers:
                if self.is_match(tender, sub):
                    sent_count += 1
                    
                    # 1. Envoi WhatsApp (réel si token configuré, sinon simulateur)
                    wa_msg = self.format_whatsapp_message(tender, sub)
                    self.send_whatsapp(sub.phone, wa_msg)
                    self.db.log_notification(tender.ep_bid_master_id, sub.id, "WHATSAPP", "SENT")

                    # 2. Envoi Telegram instantané (si token configuré)
                    if tg_conf.get("bot_token") and tg_conf.get("chat_id"):
                        tg_msg = self.format_telegram_message(tender, sub)
                        send_telegram_message(tg_msg, tg_conf["bot_token"], tg_conf["chat_id"])
                        self.db.log_notification(tender.ep_bid_master_id, sub.id, "TELEGRAM", "SENT")

                    logger.info(f"Alerte envoyée à [{sub.company_name}] pour l'avis N° {tender.bid_no}")

            self.db.mark_as_notified(tender.ep_bid_master_id)

        return {"tenders_processed": len(tenders), "notifications_sent": sent_count}

def seed_demo_subscribers(db: TenderDatabase):
    existing = db.get_active_subscribers()
    if existing:
        return

    demo_subs = [
        Subscriber(
            company_name="TechPro Solutions Tunisie",
            phone="+21698111222",
            email="contact@techpro.tn",
            categories=["IT_TELECOM"],
            governorates=["Tunis", "Ariana", "Ben Arous", "National"],
            keywords=["caméra", "serveur", "réseau", "firewall", "numérisation"],
            channel="WHATSAPP",
            plan="PRO"
        ),
        Subscriber(
            company_name="BatiNord Entreprise Générale",
            phone="+21622333444",
            email="direction@batinord.com.tn",
            categories=["BTP_CONSTRUCTION"],
            governorates=["Zaghouan", "Béja", "Jendouba", "Bizerte"],
            keywords=["construction", "clôture", "travaux", "école", "route"],
            channel="WHATSAPP",
            plan="STARTER"
        ),
        Subscriber(
            company_name="Maghreb Équipements Médicaux",
            phone="+21655444333",
            email="marches@maghreb-medical.tn",
            categories=["SANTE_MEDICAL"],
            governorates=["ALL"],
            keywords=[],
            channel="WHATSAPP",
            plan="PRO"
        )
    ]
    for sub in demo_subs:
        db.add_subscriber(sub)
    logger.info("3 profils d'entreprises tunisiennes abonnées ont été créés avec succès.")

if __name__ == "__main__":
    db = TenderDatabase()
    seed_demo_subscribers(db)
    notifier = TenderNotifier(db=db)
    notifier.dispatch_alerts(limit=10)
