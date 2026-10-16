"""
Module de Réponses Interactives par Bot (WhatsApp & Telegram).
Permet aux entrepreneurs et PME de chercher des appels d'offres en temps réel :
- En envoyant un mot-clé par WhatsApp (ex: "informatique", "travaux", "Tunis", "santé")
- En interrogeant le bot Telegram
- En utilisant l'API REST de recherche
"""
import os
import sys
import json
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple
from database import TenderDatabase, TenderNotice
from whatsapp_gateway import send_whatsapp_message, load_whatsapp_config, clean_phone_number
from telegram_bot import send_telegram_message, load_telegram_config

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BotResponder")

class BotResponder:
    def __init__(self, db: Optional[TenderDatabase] = None):
        self.db = db or TenderDatabase()
        self.wa_config = load_whatsapp_config()
        self.tg_config = load_telegram_config()

    def search_and_format_reply(self, query: str, channel: str = "WHATSAPP", limit: int = 3) -> str:
        """
        Effectue une recherche plein texte FTS5 sur les marchés ouverts
        et formate la réponse selon le canal choisi.
        """
        clean_q = query.strip()
        if not clean_q or clean_q.lower() in ["bonjour", "salut", "start", "/start", "aide", "help", "menu"]:
            if channel == "WHATSAPP":
                return (
                    "👋 *Bienvenue sur Tenders.tn Bot* 🇹🇳\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Je suis votre assistant d'accès aux marchés publics tunisiens.\n\n"
                    "🔍 *Comment chercher ?*\n"
                    "Envoyez simplement vos mots-clés ou votre secteur. Exemples :\n"
                    "• `informatique` ou `caméra`\n"
                    "• `travaux` ou `peinture`\n"
                    "• `médical` ou `laboratoire`\n"
                    "• `Sousse` ou `Tunis`\n\n"
                    "⚡ Tous les avis retournés sont en cours de validité (non clôturés) avec conditions TUNEPS-3 !"
                )
            else:
                return (
                    "👋 <b>Bienvenue sur Tenders.tn Bot</b> 🇹🇳\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Je suis votre assistant d'accès aux marchés publics tunisiens.\n\n"
                    "🔍 <b>Comment chercher ?</b>\n"
                    "Envoyez vos mots-clés ou secteurs d'activité. Exemples :\n"
                    "• <code>informatique</code> ou <code>caméra</code>\n"
                    "• <code>travaux</code> ou <code>clôture</code>\n"
                    "• <code>médical</code> ou <code>Sfax</code>\n\n"
                    "⚡ Les avis retournés sont en cours avec conditions TUNEPS-3 !"
                )

        # Recherche des marchés ouverts
        results = self.db.search_tenders(query=clean_q, only_open=True, limit=limit)
        total = results["total"]
        tenders: List[TenderNotice] = results["tenders"]

        if total == 0:
            # Essayer sans restriction uniquement ouvert au cas où
            all_res = self.db.search_tenders(query=clean_q, only_open=False, limit=2)
            if all_res["total"] > 0:
                note_closed = f"\n⚠️ _{all_res['total']} avis correspondant(s) ont été trouvés mais sont déjà clôturés._"
            else:
                note_closed = ""

            if channel == "WHATSAPP":
                return (
                    f"🔍 *Recherche TUNEPS :* \"{clean_q}\"\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"❌ Aucun marché actuellement en cours n'a été trouvé.{note_closed}\n\n"
                    f"💡 *Conseil :* Essayez des termes plus larges comme `travaux`, `matériel`, `fourniture`, `Tunis`."
                )
            else:
                return (
                    f"🔍 <b>Recherche TUNEPS :</b> <i>\"{clean_q}\"</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"❌ Aucun marché actuellement en cours n'a été trouvé.{note_closed}\n\n"
                    f"💡 <b>Conseil :</b> Essayez des termes plus larges comme <code>travaux</code>, <code>fourniture</code>, <code>Tunis</code>."
                )

        if channel == "WHATSAPP":
            lines = [
                f"🎯 *RÉSULTATS DE RECHERCHE ({total} trouvés)* 🇹🇳",
                f"Mot-clé : _{clean_q}_ | {min(limit, total)} affichés",
                "━━━━━━━━━━━━━━━━━━━━"
            ]
            for idx, t in enumerate(tenders, 1):
                title = t.title_fr or t.title_ar or "Sans titre"
                crit = f" • Critère: *{t.eval_method}*" if t.eval_method else ""
                caution = f" • Caution: *{t.guarantee_type}*" if t.guarantee_type else ""
                cdc = f" • CDC: *{t.doc_price}*" if t.doc_price else ""
                lieu = f" • Lieu: *{t.execution_place or t.governorate}*" if (t.execution_place or t.governorate) else ""

                item_msg = (
                    f"📌 *{idx}. {t.buyer_name}*\n"
                    f"📄 {title[:110]}...\n"
                    f"⏳ *Limite dépôt :* {t.deadline_date or 'Consulter TUNEPS'}\n"
                    f"⚙️{crit}{caution}{cdc}{lieu}\n"
                    f"🔗 {t.url}"
                )
                lines.append(item_msg)
                lines.append("────────────────────")

            lines.append("💡 _Pour affiner, tapez un mot-clé plus précis ou une ville._")
            return "\n".join(lines)

        else:
            # Telegram HTML
            lines = [
                f"🎯 <b>RÉSULTATS DE RECHERCHE ({total} trouvés)</b> 🇹🇳",
                f"Mot-clé : <i>{clean_q}</i>",
                "━━━━━━━━━━━━━━━━━━━━"
            ]
            for idx, t in enumerate(tenders, 1):
                title = t.title_fr or t.title_ar or "Sans titre"
                crit = f" • Critère: <b>{t.eval_method}</b>" if t.eval_method else ""
                caution = f" • Caution: <b>{t.guarantee_type}</b>" if t.guarantee_type else ""
                cdc = f" • CDC: <b>{t.doc_price}</b>" if t.doc_price else ""
                lieu = f" • Lieu: <b>{t.execution_place or t.governorate}</b>" if (t.execution_place or t.governorate) else ""

                item_msg = (
                    f"📌 <b>{idx}. {t.buyer_name}</b>\n"
                    f"📄 {title[:110]}...\n"
                    f"⏳ <b>Limite dépôt :</b> <code>{t.deadline_date or 'Consulter TUNEPS'}</code>\n"
                    f"⚙️{crit}{caution}{cdc}{lieu}\n"
                    f"🔗 <a href='{t.url}'>Consulter sur TUNEPS</a>"
                )
                lines.append(item_msg)
                lines.append("────────────────────")

            lines.append("💡 <i>Tapez un mot-clé ou une ville pour relancer une recherche.</i>")
            return "\n".join(lines)

    def process_incoming_whatsapp(self, message_body: str, sender_phone: str) -> str:
        """
        Traite un message reçu par WhatsApp, effectue la recherche et répond.
        """
        logger.info(f"Message WhatsApp reçu de +{sender_phone} : '{message_body}'")
        reply = self.search_and_format_reply(message_body, channel="WHATSAPP", limit=3)
        send_whatsapp_message(sender_phone, reply)
        return reply

    def process_incoming_telegram(self, message_body: str, chat_id: str) -> str:
        """
        Traite un message reçu par Telegram, effectue la recherche et répond.
        """
        logger.info(f"Message Telegram reçu de chat_id {chat_id} : '{message_body}'")
        reply = self.search_and_format_reply(message_body, channel="TELEGRAM", limit=3)
        if self.tg_config.get("bot_token"):
            send_telegram_message(reply, self.tg_config["bot_token"], chat_id)
        return reply

    def poll_green_api_once(self) -> int:
        """
        Vérifie s'il y a des messages WhatsApp entrants en attente sur Green-API et y répond.
        """
        instance_id = self.wa_config.get("instance_id")
        token = self.wa_config.get("token")
        if not instance_id or not token:
            return 0

        url_recv = f"https://api.green-api.com/waInstance{instance_id}/receiveNotification/{token}"
        count = 0
        try:
            resp = requests.get(url_recv, timeout=5)
            if resp.status_code == 200 and resp.text.strip():
                data = resp.json()
                if not data:
                    return 0
                receipt_id = data.get("receiptId")
                body = data.get("body", {})
                type_webhook = body.get("typeWebhook")

                # Détecter un message entrant
                if type_webhook == "incomingMessageReceived":
                    sender_data = body.get("senderData", {})
                    chat_id = sender_data.get("chatId", "")
                    sender_phone = chat_id.replace("@c.us", "")

                    msg_data = body.get("messageData", {})
                    text_msg = (
                        msg_data.get("textMessageData", {}).get("textMessage") or
                        msg_data.get("extendedTextMessageData", {}).get("text") or ""
                    )

                    if text_msg and sender_phone:
                        logger.info(f"Reçu message WhatsApp de {sender_phone}: {text_msg}")
                        self.process_incoming_whatsapp(text_msg, sender_phone)
                        count += 1

                # Confirmer la réception pour vider la file
                if receipt_id:
                    url_del = f"https://api.green-api.com/waInstance{instance_id}/deleteNotification/{token}/{receiptId}"
                    requests.delete(url_del, timeout=5)
        except Exception as e:
            logger.debug(f"Green-API poll check: {e}")

        return count

    def poll_telegram_once(self, last_update_id: int = 0) -> Tuple[int, int]:
        """
        Vérifie les mises à jour Telegram et répond aux requêtes.
        """
        bot_token = self.tg_config.get("bot_token")
        if not bot_token:
            return 0, last_update_id

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 2}
        count = 0
        new_last_id = last_update_id

        try:
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    update_id = update.get("update_id", 0)
                    if update_id > new_last_id:
                        new_last_id = update_id

                    msg = update.get("message", {})
                    chat = msg.get("chat", {})
                    chat_id = str(chat.get("id", ""))
                    text = msg.get("text", "")

                    if text and chat_id:
                        self.process_incoming_telegram(text, chat_id)
                        count += 1
        except Exception as e:
            logger.debug(f"Telegram poll check: {e}")

        return count, new_last_id

if __name__ == "__main__":
    bot = BotResponder()
    test_queries = ["informatique", "travaux", "moins disant", "tunis"]
    for q in test_queries:
        print(f"\n=================== TEST RECHERCHE: '{q}' ===================")
        res_wa = bot.search_and_format_reply(q, channel="WHATSAPP", limit=2)
        print(res_wa)
