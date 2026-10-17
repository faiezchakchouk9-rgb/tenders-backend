"""
Portail Web d'Onboarding Self-Service et Intégration Passerelles de Paiement.
Gère :
- La landing page commerciale & démonstrateur d'appels d'offres en direct
- Le formulaire d'inscription et de personnalisation des filtres
- L'activation de l'essai gratuit 7 jours
- L'intégration de la passerelle de paiement tunisienne (Konnect.network / Flouci)
- Le webhook de validation automatique des abonnements
"""
import os
import json
import time
import logging
import requests
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from database import TenderDatabase, Subscriber
from notifier import TenderNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OnboardingServer")

app = FastAPI(title="Tenders.tn - Portail Marchés Publics Automatisé")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
db = TenderDatabase()
notifier = TenderNotifier(db=db)

@app.on_event("startup")
def startup_event():
    """Au démarrage du serveur cloud, vérifie et télécharge automatiquement les marchés TUNEPS."""
    try:
        from collector import TunepsCollector
        from enricher import TenderEnricher
        collector = TunepsCollector(db=db)
        enricher = TenderEnricher(db=db)
        logger.info("Synchronisation initiale des marchés TUNEPS au démarrage...")
        collector.sync_latest(max_items=30, only_open=True)
        enricher.process_all_pending(limit=30)
        logger.info("Synchronisation initiale terminée avec succès.")
    except Exception as e:
        logger.warning(f"Note startup sync: {e}")

@app.get("/api/sync")
def force_sync():
    """Endpoint déclenchant manuellement la collecte TUNEPS."""
    from collector import TunepsCollector
    from enricher import TenderEnricher
    collector = TunepsCollector(db=db)
    enricher = TenderEnricher(db=db)
    stats = collector.sync_latest(max_items=30, only_open=True)
    enr_count = enricher.process_all_pending(limit=30)
    db_stats = db.get_stats()
    return {
        "status": "SUCCESS",
        "scanned": stats["scanned"],
        "new": stats["new_inserted"],
        "enriched": enr_count,
        "total_in_db": db_stats["total_tenders"]
    }

# Configuration de la passerelle de paiement (Konnect.network / Flouci)
KONNECT_API_KEY = os.getenv("KONNECT_API_KEY", "test_key_sample")
KONNECT_RECEIVER_WALLET = os.getenv("KONNECT_WALLET_ID", "sample_wallet")
BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

class SubscriptionRequest(BaseModel):
    company_name: str
    phone: str
    email: str
    categories: List[str]
    governorates: List[str]
    keywords: Optional[List[str]] = []
    plan: str = "TRIAL"  # "TRIAL" (0 TND), "STARTER" (49 TND), "PRO" (129 TND)

class BotQueryRequest(BaseModel):
    query: str
    channel: str = "WHATSAPP"
    phone_or_chat_id: Optional[str] = None

@app.get("/api/tenders/search")
def search_tenders_api(
    q: Optional[str] = "",
    category: Optional[str] = "ALL",
    governorate: Optional[str] = "ALL",
    only_open: bool = True,
    limit: int = 12,
    offset: int = 0
):
    """Recherche instantanée plein-texte FTS5 avec filtres approfondis TUNEPS-3."""
    t0 = time.time()
    results = db.search_tenders(
        query=q or "",
        category=category,
        governorate=governorate,
        only_open=only_open,
        limit=limit,
        offset=offset
    )
    query_time_ms = round((time.time() - t0) * 1000, 2)

    tenders_data = []
    for t in results["tenders"]:
        tenders_data.append({
            "id": t.ep_bid_master_id,
            "bid_no": t.bid_no,
            "title": t.title_fr or t.title_ar,
            "buyer": t.buyer_name,
            "publication_date": t.publication_date,
            "deadline": t.deadline_date,
            "category": t.category,
            "governorate": t.governorate,
            "execution_place": t.execution_place,
            "eval_method": t.eval_method,
            "guarantee_type": t.guarantee_type,
            "doc_price": t.doc_price,
            "opening_date": t.opening_date,
            "is_online": t.is_online,
            "tags": json.loads(t.tags) if t.tags else [],
            "ai_summary": t.ai_summary,
            "url": t.url
        })

    return {
        "query": q,
        "query_time_ms": query_time_ms,
        "total": results["total"],
        "limit": results["limit"],
        "offset": results["offset"],
        "tenders": tenders_data
    }

@app.post("/api/bot/query")
def bot_query_api(req: BotQueryRequest):
    """Permet de tester ou d'interroger le bot directement avec réponse temps réel."""
    from bot_responder import BotResponder
    bot = BotResponder(db=db)
    reply = bot.search_and_format_reply(req.query, channel=req.channel, limit=3)
    if req.phone_or_chat_id:
        if req.channel == "WHATSAPP":
            from whatsapp_gateway import send_whatsapp_message
            send_whatsapp_message(req.phone_or_chat_id, reply)
        elif req.channel == "TELEGRAM":
            from telegram_bot import send_telegram_message, load_telegram_config
            conf = load_telegram_config()
            if conf.get("bot_token"):
                send_telegram_message(reply, conf["bot_token"], req.phone_or_chat_id)
    return {"query": req.query, "reply": reply}

@app.get("/api/webhook/meta")
def meta_webhook_verify(request: Request):
    """Vérification du webhook par Meta (hub.challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    # Jeton de vérification secret
    VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "tenders_webhook_token_2026")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook Meta vérifié avec succès !")
        return int(challenge) if challenge.isdigit() else challenge
    raise HTTPException(status_code=403, detail="Verification token mismatch")

@app.post("/api/webhook/meta")
async def meta_webhook_handler(request: Request):
    """Reçoit les messages entrants des clients sur WhatsApp et répond avec les marchés en direct."""
    try:
        body = await request.json()
        entry = body.get("entry", [])
        if not entry:
            return {"status": "NO_ENTRY"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "NO_CHANGES"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            sender = msg.get("from")  # Numéro du client
            msg_type = msg.get("type")

            text_body = ""
            if msg_type == "text":
                text_body = msg.get("text", {}).get("body", "").strip()

            if sender and text_body:
                logger.info(f"Message reçu sur Meta WhatsApp de +{sender} : '{text_body}'")
                from bot_responder import BotResponder
                bot = BotResponder(db=db)
                reply = bot.search_and_format_reply(text_body, channel="WHATSAPP", limit=3)
                
                from whatsapp_gateway import send_whatsapp_message
                send_whatsapp_message(sender, reply)
                return {"status": "REPLIED", "sender": sender, "query": text_body}

    except Exception as e:
        logger.error(f"Erreur traitement webhook Meta: {e}")

    return {"status": "RECEIVED"}

@app.post("/api/webhook/green-api")
async def green_api_webhook(request: Request):
    """Reçoit les messages WhatsApp entrants de Green-API et y répond automatiquement."""
    try:
        body = await request.json()
        type_webhook = body.get("typeWebhook")
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
                from bot_responder import BotResponder
                bot = BotResponder(db=db)
                bot.process_incoming_whatsapp(text_msg, sender_phone)
                return {"status": "REPLIED"}
    except Exception as e:
        logger.error(f"Erreur Green-API webhook: {e}")
    return {"status": "IGNORED"}

@app.post("/api/subscribe")
def register_subscriber(req: SubscriptionRequest):
    """
    Inscrit une nouvelle entreprise :
    - Si plan TRIAL : active immédiatement 7 jours d'alertes gratuites.
    - Si plan payant (49 / 129 TND) : génère le lien de paiement Konnect.
    """
    clean_phone = req.phone.strip().replace(" ", "").replace("-", "")
    if not clean_phone.startswith("+"):
        if clean_phone.startswith("216"):
            clean_phone = "+" + clean_phone
        else:
            clean_phone = "+216" + clean_phone

    sub = Subscriber(
        company_name=req.company_name.strip(),
        phone=clean_phone,
        email=str(req.email).strip().lower(),
        categories=req.categories if req.categories else ["ALL"],
        governorates=req.governorates if req.governorates else ["ALL"],
        keywords=req.keywords or [],
        channel="WHATSAPP",
        plan=req.plan,
        is_active=1 if req.plan == "TRIAL" else 0
    )

    sub_id = db.add_subscriber(sub)
    logger.info(f"[ONBOARDING] Nouveau client inscrit : {sub.company_name} (ID: {sub_id}, Plan: {req.plan})")

    # 1. Si Essai Gratuit : Onboarding direct sans carte bancaire
    if req.plan == "TRIAL":
        welcome_msg = (
            f"🎉 *Bienvenue sur Tenders.tn, {sub.company_name} !*\n\n"
            f"Votre période d'essai gratuit de *7 jours* est active.\n"
            f"Vous recevrez désormais en temps réel les appels d'offres TUNEPS correspondant à vos critères :\n"
            f"📁 *Secteurs :* {', '.join(sub.categories)}\n"
            f"📍 *Régions :* {', '.join(sub.governorates)}\n\n"
            f"⚡ Vos premières alertes arriveront dès parution officielle !"
        )
        notifier.send_whatsapp(sub.phone, welcome_msg)
        return {
            "status": "ACTIVE_TRIAL",
            "message": "Votre essai gratuit de 7 jours est activé avec succès !",
            "subscriber_id": sub_id
        }

    # 2. Si Plan Payant : Génération du lien de paiement Konnect
    amount_tnd = 49 if req.plan == "STARTER" else 129
    amount_millimes = amount_tnd * 1000

    konnect_payload = {
        "receiverWalletId": KONNECT_RECEIVER_WALLET,
        "token": "TND",
        "amount": amount_millimes,
        "type": "immediate",
        "description": f"Abonnement Tenders.tn - {req.plan} ({sub.company_name})",
        "acceptedPaymentMethods": ["wallet", "bank_card", "e-dinar", "flouci"],
        "lifespan": 60,
        "checkoutForm": True,
        "addPaymentFeesToAmount": True,
        "firstName": sub.company_name,
        "lastName": "PME",
        "phoneNumber": clean_phone,
        "email": sub.email,
        "orderId": f"SUB-{sub_id}",
        "webhook": f"{BASE_URL}/api/webhook/konnect",
        "silentWebhook": True,
        "successUrl": f"{BASE_URL}/success?sub_id={sub_id}",
        "failUrl": f"{BASE_URL}/failed?sub_id={sub_id}"
    }

    # Simulation ou appel réel de l'API Konnect
    if KONNECT_API_KEY != "test_key_sample":
        try:
            k_resp = requests.post(
                "https://api.konnect.network/api/v2/payments/init-payment",
                headers={"x-api-key": KONNECT_API_KEY, "Content-Type": "application/json"},
                json=konnect_payload,
                timeout=10
            )
            data = k_resp.json()
            return {"status": "PAYMENT_REQUIRED", "payment_url": data.get("payUrl"), "subscriber_id": sub_id}
        except Exception as e:
            logger.error(f"Erreur Konnect: {e}")

    # En mode dev / test sandbox : URL de simulation de paiement immédiat
    sandbox_url = f"{BASE_URL}/mock-pay?sub_id={sub_id}&amount={amount_tnd}"
    return {
        "status": "PAYMENT_REQUIRED",
        "payment_url": sandbox_url,
        "amount_tnd": amount_tnd,
        "subscriber_id": sub_id
    }

@app.post("/api/webhook/konnect")
async def konnect_webhook(request: Request):
    """Reçoit la confirmation de paiement instantanée de Konnect/Flouci."""
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK REÇU] Données Konnect: {body}")
        order_id = body.get("orderId", "")

        if order_id.startswith("SUB-"):
            sub_id = int(order_id.replace("SUB-", ""))
            with db._get_connection() as conn:
                conn.execute("UPDATE subscribers SET is_active = 1 WHERE id = ?", (sub_id,))
                conn.commit()
            logger.info(f"[PAIEMENT CONFIRMÉ] Abonnement activé pour l'abonné #{sub_id}")
            return {"status": "SUCCESS"}
    except Exception as e:
        logger.error(f"Erreur webhook: {e}")
    return {"status": "IGNORED"}

@app.get("/mock-pay", response_class=HTMLResponse)
def mock_payment_page(sub_id: int, amount: int = 49):
    """Page de simulation du paiement bancaire pour les tests locaux."""
    with db._get_connection() as conn:
        conn.execute("UPDATE subscribers SET is_active = 1 WHERE id = ?", (sub_id,))
        conn.commit()
    return f"""
    <html>
        <head>
            <title>Paiement Réussi</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-900 text-white flex items-center justify-center min-h-screen">
            <div class="bg-slate-800 p-8 rounded-2xl max-w-md text-center shadow-2xl border border-emerald-500/30">
                <div class="text-6xl mb-4">✅</div>
                <h1 class="text-2xl font-bold text-emerald-400 mb-2">Paiement validé avec succès !</h1>
                <p class="text-slate-300 text-sm mb-6">Montant réglé : <b>{amount} TND</b> (Passerelle Konnect / Carte GIM-TEL).</p>
                <div class="p-4 bg-slate-900/80 rounded-xl text-left text-xs font-mono text-emerald-300 mb-6 border border-emerald-500/20">
                    Abonnement #{sub_id} : Statut ACTIF<br/>
                    Notifications WhatsApp : Démarrées en temps réel
                </div>
                <a href="/" class="inline-block w-full py-3 bg-emerald-500 hover:bg-emerald-600 font-bold rounded-xl text-white transition">
                    Retourner à l'accueil
                </a>
            </div>
        </body>
    </html>
    """

@app.get("/", response_class=HTMLResponse)
def render_landing_page():
    """Sert le fichier HTML de la plateforme connectée à Firebase."""
    pub_path = os.path.join(os.path.dirname(__file__), "public", "index.html")
    if os.path.exists(pub_path):
        with open(pub_path, "r", encoding="utf-8") as f:
            return f.read()
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
