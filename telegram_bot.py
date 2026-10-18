"""
Module d'intégration et d'envoi Telegram Bot pour Tenders.tn.
Permet d'envoyer instantanément les alertes d'appels d'offres TUNEPS
sur votre téléphone via l'application Telegram (100% gratuit et sans limite).
"""
import os
import sys
import json
import logging
import requests
from typing import Optional, Dict, Any

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TelegramNotifier")

CONFIG_FILE = "telegram_config.json"

def load_telegram_config() -> Dict[str, str]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID", "")
    }

def save_telegram_config(bot_token: str, chat_id: str):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"bot_token": bot_token.strip(), "chat_id": str(chat_id).strip()}, f, indent=2)
    logger.info(f"Configuration Telegram enregistrée dans {CONFIG_FILE} !")

def send_telegram_message(text: str, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> bool:
    config = load_telegram_config()
    token = bot_token or config.get("bot_token")
    cid = chat_id or config.get("chat_id")

    if not token or not cid:
        logger.warning("Token ou Chat ID Telegram manquant. Impossible d'expédier le message.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("ok"):
            logger.info(f"Message Telegram transmis avec succès au chat #{cid} !")
            return True
        else:
            logger.error(f"Erreur API Telegram: {data.get('description')}")
            return False
    except Exception as e:
        logger.error(f"Exception lors de l'envoi Telegram: {e}")
        return False

def discover_chat_id(bot_token: str) -> Optional[str]:
    """
    Interroge l'API Telegram pour détecter automatiquement le Chat ID
    dès que l'utilisateur clique sur 'Démarrer' (Start) dans son bot.
    """
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        resp = requests.post(url, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Token invalide: {data.get('description')}")
            return None

        results = data.get("result", [])
        if not results:
            return None

        # Prendre le dernier message reçu
        last_update = results[-1]
        msg = last_update.get("message") or last_update.get("channel_post") or {}
        chat = msg.get("chat", {})
        cid = chat.get("id")
        user_name = chat.get("first_name", "") or chat.get("title", "")
        if cid:
            logger.info(f"Chat ID détecté : {cid} (Utilisateur: {user_name})")
            return str(cid)
    except Exception as e:
        logger.error(f"Erreur détection Chat ID: {e}")
    return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gestionnaire Telegram Bot Tenders.tn")
    parser.add_argument("--token", type=str, help="Token du bot Telegram obtenu sur @BotFather")
    parser.add_argument("--chat_id", type=str, help="Votre Chat ID personnel (optionnel)")
    parser.add_argument("--test", action="store_true", help="Envoyer un message test")
    parser.add_argument("--auto", action="store_true", help="Détecter automatiquement le Chat ID")

    args = parser.parse_args()

    config = load_telegram_config()
    token = args.token or config.get("bot_token")

    if not token:
        print("\n❌ Aucun token fourni. Veuillez fournir votre token avec :")
        print("   python telegram_bot.py --token <VOTRE_TOKEN_BOTFATHER>\n")
        sys.exit(1)

    chat_id = args.chat_id or config.get("chat_id")

    if args.auto or not chat_id:
        print(f"\n🔍 Recherche du Chat ID via le bot Telegram...")
        print("👉 Assurez-vous d'avoir ouvert votre bot sur Telegram et cliqué sur 'DÉMARRER' (Start) !")
        cid = discover_chat_id(token)
        if cid:
            chat_id = cid
            save_telegram_config(token, chat_id)
            print(f"✅ Chat ID {chat_id} associé et enregistré avec succès !")
        else:
            print("⚠️ Aucun message détecté. Veuillez ouvrir votre bot sur Telegram, cliquer sur 'Démarrer' et relancer.")
            sys.exit(1)

    if args.test or chat_id:
        save_telegram_config(token, chat_id)
        test_msg = (
            "🚀 <b>Connexion Réussie avec Tenders.tn !</b> 🇹🇳\n\n"
            "Votre bot Telegram est désormais relié au portail <b>TUNEPS</b>.\n"
            "Vous recevrez ici vos alertes de marchés publics qualifiées par IA en temps réel !"
        )
        print("\nEnvoi d'un message test en direct...")
        success = send_telegram_message(test_msg, bot_token=token, chat_id=chat_id)
        if success:
            print("🎉 Félicitations : vérifiez votre Telegram, le message vient d'arriver !")
        else:
            print("❌ Échec de l'envoi. Vérifiez le token et réessayez.")
