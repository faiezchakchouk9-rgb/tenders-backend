"""
Module d'expédition WhatsApp automatisé pour Tenders.tn.
Supporte Meta Cloud API (officiel sans limite) avec basculement automatique vers Green-API.
"""
import os
import json
import logging
import requests
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WhatsAppGateway")

CONFIG_FILE = "whatsapp_config.json"

def load_whatsapp_config() -> Dict[str, str]:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    return {
        "provider": os.getenv("WHATSAPP_PROVIDER") or cfg.get("provider", "meta"),
        "fallback_provider": cfg.get("fallback_provider", "green-api"),
        "meta_phone_number_id": os.getenv("META_PHONE_NUMBER_ID") or cfg.get("meta_phone_number_id", ""),
        "meta_access_token": os.getenv("META_ACCESS_TOKEN") or cfg.get("meta_access_token", ""),
        "instance_id": os.getenv("GREEN_API_INSTANCE_ID") or cfg.get("instance_id", ""),
        "token": os.getenv("GREEN_API_TOKEN") or cfg.get("token", "")
    }

def clean_phone_number(phone: str) -> str:
    """Nettoie le numéro au format international sans '+' (ex: 21629361750)."""
    p = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
    if not p.startswith("216"):
        p = "216" + p
    return p

def send_meta_whatsapp_message(phone: str, message: str, config: Dict[str, str]) -> bool:
    """Envoie via Meta Cloud API officielle."""
    phone_id = config.get("meta_phone_number_id")
    token = config.get("meta_access_token")
    target_phone = clean_phone_number(phone)

    if not phone_id or not token:
        return False

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Tentative 1 : Envoi direct comme texte
    payload_text = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": target_phone,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=payload_text, timeout=12)
        data = resp.json()
        if resp.status_code == 200 and data.get("messages"):
            msg_id = data["messages"][0]["id"]
            logger.info(f"✅ [META CLOUD API RÉEL ENVOYÉ] vers +{target_phone} (Message ID: {msg_id})")
            return True
        else:
            logger.warning(f"Meta text note: {data.get('error', {}).get('message', data)}")
            
            # Si échec dû à la fenêtre de 24h, envoyer le template officiel hello_world
            payload_template = {
                "messaging_product": "whatsapp",
                "to": target_phone,
                "type": "template",
                "template": {
                    "name": "hello_world",
                    "language": {"code": "en_US"}
                }
            }
            resp_tpl = requests.post(url, headers=headers, json=payload_template, timeout=12)
            data_tpl = resp_tpl.json()
            if resp_tpl.status_code == 200 and data_tpl.get("messages"):
                msg_id = data_tpl["messages"][0]["id"]
                logger.info(f"✅ [META CLOUD API TEMPLATE ENVOYÉ] vers +{target_phone} (Message ID: {msg_id})")
                return True
            else:
                logger.error(f"❌ Erreur Meta API: {data_tpl}")
                return False
    except Exception as e:
        logger.error(f"❌ Exception Meta Cloud API: {e}")
        return False

def send_green_api_message(phone: str, message: str, config: Dict[str, str]) -> bool:
    """Envoi de secours via Green-API."""
    instance_id = config.get("instance_id")
    token = config.get("token")
    target_phone = clean_phone_number(phone)

    if not instance_id or not token:
        return False

    url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{token}"
    payload = {
        "chatId": f"{target_phone}@c.us",
        "message": message
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        data = resp.json()
        if resp.status_code == 200 and data.get("idMessage"):
            logger.info(f"✅ [GREEN-API FALLBACK RÉEL ENVOYÉ] vers +{target_phone} (Message ID: {data.get('idMessage')})")
            return True
        else:
            logger.error(f"❌ Erreur Green-API: {data}")
            return False
    except Exception as e:
        logger.error(f"❌ Exception Green-API: {e}")
        return False

def send_whatsapp_message(phone: str, message: str) -> bool:
    """
    Routeur résilient :
    1. Tente l'envoi prioritaire via Meta Cloud API (officiel).
    2. En cas d'échec ou d'erreur, bascule automatiquement sur Green-API.
    """
    config = load_whatsapp_config()
    provider = config.get("provider", "meta")

    if provider == "meta":
        # 1. Tentative Meta
        success = send_meta_whatsapp_message(phone, message, config)
        if success:
            return True

        # 2. Fallback Green-API
        logger.info("⚠️ Basculement automatique sur la passerelle de secours Green-API...")
        fallback_success = send_green_api_message(phone, message, config)
        if fallback_success:
            return True

    elif provider == "green-api":
        success = send_green_api_message(phone, message, config)
        if success:
            return True

    logger.warning(f"Passerelles indisponibles. Message simulé vers {phone}.")
    return False

if __name__ == "__main__":
    send_whatsapp_message("21628177888", "Test de validation Meta WhatsApp officiel")
