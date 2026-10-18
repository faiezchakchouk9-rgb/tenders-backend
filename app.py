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
import threading
import io
import csv
import zipfile
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from database import TenderDatabase, Subscriber
from notifier import TenderNotifier

load_dotenv()

# Configuration du logging structuré
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("OnboardingServer")

app = FastAPI(title="Tenders.tn - Portail Marchés Publics Automatisé")

# Configuration CORS basée sur l'environnement
cors_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware de protection des routes admin
ADMIN_SECRET = os.getenv("ADMIN_SECRET_KEY", "dev-admin-key")

@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    """Protection basique des routes d'administration."""
    if request.url.path.startswith("/admin") or request.url.path.startswith("/api/admin"):
        auth_header = request.headers.get("X-Admin-Key") or request.query_params.get("admin_key")
        if auth_header != ADMIN_SECRET and os.getenv('ENVIRONMENT') == 'production':
            return JSONResponse(
                status_code=401,
                content={"error": "Accès non autorisé. Clé d'administration requise."}
            )
    response = await call_next(request)
    return response

db = TenderDatabase(os.getenv("DB_PATH", "tenders.db"))
notifier = TenderNotifier(db=db)

def autonomous_scheduler_loop():
    """
    Boucle de fond autonome permanente (Zero-Ops) :
    1. Toutes les 30 min : Scan TUNEPS + enrichissement IA + dispatch alertes temps réel.
    2. Tous les jours à 08:00 (UTC+1 Tunis) : Briefing WhatsApp matinal aux abonnés actifs.
    """
    logger.info("Démarrage de la boucle autonome permanente Tenders.tn (Zero-Ops)...")
    last_briefing_date = None
    last_weekly_briefing_date = None

    while True:
        try:
            # 1. Veille TUNEPS
            from collector import TunepsCollector
            from enricher import TenderEnricher
            collector = TunepsCollector(db=db)
            enricher = TenderEnricher(db=db)
            sync_res = collector.sync_latest(max_items=30, only_open=True)
            if sync_res.get("new_inserted", 0) > 0:
                enricher.process_all_pending(limit=30)
                notifier.dispatch_alerts(limit=50)
                logger.info(f"Veille TUNEPS : {sync_res['new_inserted']} nouveaux marchés notifiés.")

            # 2. Briefing Matinal WhatsApp (08:00 UTC+1)
            tunis_now = datetime.now(timezone(timedelta(hours=1)))
            today_str = tunis_now.strftime("%Y-%m-%d")
            briefing_target_hour = int(os.getenv("MORNING_BRIEFING_HOUR", "8"))

            if tunis_now.hour == briefing_target_hour and last_briefing_date != today_str:
                logger.info(f"Déclenchement automatique du Briefing Matinal WhatsApp ({today_str} 08:00)...")
                active_subs = db.get_active_subscribers()
                for sub in active_subs:
                    try:
                        notifier.send_morning_briefing(sub.id)
                    except Exception as ex:
                        logger.error(f"Erreur envoi briefing sub #{sub.id}: {ex}")
                last_briefing_date = today_str
                logger.info("Briefing Matinal WhatsApp expédié avec succès à tous les abonnés actifs.")

            # 3. Briefing Hebdomadaire WhatsApp (Lundi à 08:30 UTC+1)
            if tunis_now.weekday() == 0 and tunis_now.hour == 8 and tunis_now.minute >= 30 and last_weekly_briefing_date != today_str:
                logger.info(f"Déclenchement automatique du Briefing Hebdomadaire WhatsApp ({today_str} 08:30)...")
                try:
                    notifier.send_weekly_briefing()
                    last_weekly_briefing_date = today_str
                    logger.info("Briefing Hebdomadaire WhatsApp expédié avec succès.")
                except Exception as ex:
                    logger.error(f"Erreur envoi briefing hebdomadaire: {ex}")

        except Exception as e:
            logger.error(f"Erreur dans la boucle de veille continue : {e}")

        interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "30")) * 60
        time.sleep(interval)

@app.on_event("startup")
def startup_event():
    """Au démarrage du serveur cloud, initialise la synchronisation et lance la veille continue en arrière-plan."""
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

    # Lancement du démon autonome permanent (Zero-Ops)
    sched_thread = threading.Thread(target=autonomous_scheduler_loop, daemon=True)
    sched_thread.start()
    logger.info("Scheduler autonome lancé en arrière-plan.")

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

# ==============================================================================
# ENDPOINTS DE MONITORING & SANTÉ
# ==============================================================================

@app.get("/ping")
@app.head("/ping")
@app.get("/api/ping")
def ping_keep_alive():
    """Endpoint ultra-léger pour les cron-jobs anti-veille (2 octets: OK)."""
    return Response(content="OK", media_type="text/plain", status_code=200)

@app.get("/health")
@app.head("/health")
def health_check():
    """Endpoint de vérification de santé pour les load balancers et monitoring."""
    try:
        stats = db.get_stats()
        return {
            "status": "healthy",
            "version": "1.0.0",
            "database": "connected",
            "total_tenders": stats.get("total_tenders", 0),
            "total_subscribers": stats.get("active_subscribers", stats.get("total_subscribers", 0)),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return Response(
            content=json.dumps({"status": "unhealthy", "error": str(e)}),
            status_code=503,
            media_type="application/json"
        )

@app.get("/api/version")
def get_version():
    """Retourne la version de l'API et les informations système."""
    return {
        "name": "Tenders.tn API",
        "version": "1.0.0",
        "description": "Plateforme de Veille sur les Marchés Publics Tunisiens",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "documentation": "/docs"
    }

# ==============================================================================
# GESTIONNAIRES D'ERREURS GLOBAUX
# ==============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Gestionnaire global d'erreurs - capture toutes les exceptions non gérées."""
    logger.error(f"Erreur non gérée sur {request.method} {request.url}: {exc}", exc_info=True)
    is_prod = os.getenv("ENVIRONMENT", "development") == "production"
    return JSONResponse(
        status_code=500,
        content={
            "error": "Erreur interne du serveur",
            "detail": "Une erreur est survenue. Veuillez réessayer." if is_prod else str(exc)
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Gestionnaire d'erreurs HTTP personnalisé."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "detail": exc.detail,
            "status_code": exc.status_code
        }
    )

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
    password: Optional[str] = None

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

@app.get("/api/tenders/{tender_id}")
def get_tender_details_api(tender_id: int):
    """Renvoie la fiche complète officielle et détaillée d'un appel d'offres."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Appel d'offres introuvable.")
    return t

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
    if req.password and len(req.password.strip()) >= 4:
        db.set_subscriber_password(sub_id, req.password.strip())
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
        sub_obj = db.get_subscriber_by_id(sub_id)
        sub_dict = {
            "id": sub_id,
            "company_name": sub.company_name,
            "phone": sub.phone,
            "email": sub.email,
            "plan": sub.plan,
            "categories": sub.categories,
            "governorates": sub.governorates,
            "keywords": sub.keywords,
            "channel": sub.channel,
            "features": sub_obj.features if sub_obj else {}
        }
        return {
            "status": "ACTIVE_TRIAL",
            "success": True,
            "message": "Votre essai gratuit de 7 jours est activé avec succès !",
            "subscriber_id": sub_id,
            "plan": "TRIAL",
            "subscriber": sub_dict
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
    if os.getenv("ENVIRONMENT") == "production":
        raise HTTPException(status_code=403, detail="Endpoint de test désactivé en production.")
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

def _find_html_content(filename: str) -> Optional[str]:
    """Recherche un fichier HTML dans public/, templates/ ou à la racine."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "public", filename),
        os.path.join(os.path.dirname(__file__), "templates", filename),
        os.path.join(os.path.dirname(__file__), filename),
        os.path.join(os.getcwd(), "public", filename),
        os.path.join(os.getcwd(), "templates", filename),
        os.path.join(os.getcwd(), filename),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return None

@app.get("/", response_class=HTMLResponse)
def render_landing_page():
    """Sert le fichier HTML de la plateforme connectée à Firebase."""
    content = _find_html_content("index.html")
    if content:
        return content
    return "<h1>Bienvenue sur Tenders.tn</h1>"

@app.get("/cgu", response_class=HTMLResponse)
def render_cgu_page():
    """Sert la page des Conditions Générales d'Utilisation (CGU) conformes à la loi tunisienne."""
    content = _find_html_content("cgu.html")
    if content:
        return HTMLResponse(content=content, status_code=200, media_type="text/html; charset=utf-8")
    return HTMLResponse(content="<h1>Conditions Générales d'Utilisation non trouvées</h1>", status_code=404, media_type="text/html; charset=utf-8")

@app.get("/confidentialite", response_class=HTMLResponse)
def render_confidentialite_page():
    """Sert la Politique de Confidentialité conforme à la Loi organique n° 2004-63 (INPDP)."""
    content = _find_html_content("confidentialite.html")
    if content:
        return HTMLResponse(content=content, status_code=200, media_type="text/html; charset=utf-8")
    return HTMLResponse(content="<h1>Politique de Confidentialité non trouvée</h1>", status_code=404, media_type="text/html; charset=utf-8")

# --- Endpoints Dashboard Client Privé & Pipeline de Candidatures ---

class ClientLoginRequest(BaseModel):
    phone: str
    password: str

class ClientProfileUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    email: Optional[str] = None
    categories: Optional[List[str]] = None
    governorates: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    channel: Optional[str] = None
    password: Optional[str] = None

class BookmarkRequest(BaseModel):
    subscriber_id: int
    tender_id: int
    status: Optional[str] = "A_ETUDIER"
    notes: Optional[str] = ""

@app.post("/api/client/login")
def client_login(req: ClientLoginRequest):
    """Connexion sécurisée par numéro WhatsApp et mot de passe."""
    phone = req.phone.strip()
    password = req.password.strip() if req.password else ""
    if not phone:
        raise HTTPException(status_code=400, detail="Numéro de téléphone requis.")
    if not password:
        raise HTTPException(status_code=400, detail="Mot de passe requis.")

    is_valid, sub, msg = db.verify_subscriber_credentials(phone, password)
    if not is_valid or not sub:
        raise HTTPException(status_code=401, detail=msg or "Numéro ou mot de passe incorrect.")

    bookmarks = db.get_subscriber_bookmarks(sub.id)
    matched = db.get_subscriber_matched_tenders(sub.id, limit=30)

    return {
        "status": "SUCCESS",
        "message": msg,
        "subscriber": {
            "id": sub.id,
            "company_name": sub.company_name,
            "phone": sub.phone,
            "email": sub.email,
            "plan": sub.plan,
            "categories": sub.categories,
            "governorates": sub.governorates,
            "keywords": sub.keywords,
            "channel": sub.channel,
            "features": sub.features or {}
        },
        "stats": {
            "bookmarked_count": len(bookmarks),
            "opportunities_count": len(matched)
        }
    }

class ForgotPasswordRequest(BaseModel):
    phone: str

class ForgotPasswordVerifyRequest(BaseModel):
    phone: str
    otp_code: str
    new_password: str

@app.post("/api/client/forgot-password/request")
def forgot_password_request(req: ForgotPasswordRequest):
    """
    Génère un code OTP à 6 chiffres valable 10 minutes et l'expédie par WhatsApp officiel.
    """
    phone = req.phone.strip() if req.phone else ""
    if not phone:
        raise HTTPException(status_code=400, detail="Numéro de téléphone requis.")
    
    sub, otp_code = db.create_password_reset_otp(phone)
    if not sub or not otp_code:
        raise HTTPException(status_code=404, detail="Numéro de téléphone non associé à un compte Tenders.tn")
    
    msg = f"🔐 Tenders.tn - Votre code de réinitialisation est : {otp_code}. Valable 10 minutes. Ne le partagez avec personne."
    try:
        from whatsapp_gateway import send_whatsapp_message
        send_whatsapp_message(sub.phone, msg)
    except Exception as e:
        logger.error(f"Erreur envoi OTP WhatsApp : {e}")

    return {
        "success": True,
        "message": "Code OTP expédié via WhatsApp",
        "expires_in_minutes": 10
    }

@app.post("/api/client/forgot-password/verify")
def forgot_password_verify(req: ForgotPasswordVerifyRequest):
    """
    Vérifie l'OTP et met à jour le mot de passe de l'abonné via PBKDF2.
    """
    phone = req.phone.strip() if req.phone else ""
    otp_code = req.otp_code.strip() if req.otp_code else ""
    new_password = req.new_password.strip() if req.new_password else ""

    if not phone or not otp_code or not new_password:
        raise HTTPException(status_code=400, detail="Numéro, code OTP et nouveau mot de passe requis.")

    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Le mot de passe doit comporter au moins 4 caractères.")

    success, msg = db.verify_and_consume_password_reset_otp(phone, otp_code, new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Code OTP invalide ou expiré")

    return {
        "success": True,
        "message": "Mot de passe réinitialisé avec succès"
    }

@app.get("/api/client/profile/{sub_id}")
def get_client_profile(sub_id: int):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    bookmarks = db.get_subscriber_bookmarks(sub.id)
    matched = db.get_subscriber_matched_tenders(sub.id, limit=30)
    return {
        "subscriber": {
            "id": sub.id,
            "company_name": sub.company_name,
            "phone": sub.phone,
            "email": sub.email,
            "plan": sub.plan,
            "categories": sub.categories,
            "governorates": sub.governorates,
            "keywords": sub.keywords,
            "channel": sub.channel,
            "features": sub.features or {}
        },
        "stats": {
            "bookmarked_count": len(bookmarks),
            "opportunities_count": len(matched)
        }
    }

@app.put("/api/client/profile/{sub_id}")
def update_client_profile(sub_id: int, req: ClientProfileUpdateRequest):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    success = db.update_subscriber_profile(
        sub_id=sub_id,
        company_name=req.company_name,
        email=req.email,
        categories=req.categories,
        governorates=req.governorates,
        keywords=req.keywords,
        channel=req.channel,
        password=req.password
    )
    updated_sub = db.get_subscriber_by_id(sub_id)
    return {
        "status": "SUCCESS" if success else "UNCHANGED",
        "subscriber": {
            "id": updated_sub.id,
            "company_name": updated_sub.company_name,
            "phone": updated_sub.phone,
            "email": updated_sub.email,
            "plan": updated_sub.plan,
            "categories": updated_sub.categories,
            "governorates": updated_sub.governorates,
            "keywords": updated_sub.keywords,
            "channel": updated_sub.channel,
            "features": updated_sub.features or {}
        }
    }

@app.get("/api/client/opportunities/{sub_id}")
def get_client_opportunities(sub_id: int, limit: int = 50):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    tenders = db.get_subscriber_matched_tenders(sub_id, limit=limit)
    return {"total": len(tenders), "tenders": tenders, "subscriber_id": sub.id}


def generate_opportunities_csv(tenders: List[Dict[str, Any]]) -> bytes:
    """Génère un flux CSV avec en-têtes français et encodage UTF-8 BOM (utf-8-sig)."""
    headers = ["N° Avis", "Acheteur", "Objet", "Région", "Date limite", "Cautionnement", "Secteur", "Lien TUNEPS"]
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for t in tenders:
        row = [
            t.get("bid_no") or "",
            t.get("buyer_name") or "",
            t.get("title_fr") or t.get("title_ar") or "",
            t.get("governorate") or t.get("execution_place") or "",
            t.get("deadline_date") or "",
            t.get("guarantee_type") or "",
            t.get("category") or "",
            t.get("url") or "",
        ]
        writer.writerow(row)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def generate_opportunities_xlsx(tenders: List[Dict[str, Any]]) -> bytes:
    """Génère un classeur Excel natif (.xlsx) stylisé via openpyxl avec ajustement automatique des largeurs."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Opportunités Tenders.tn"
    ws.views.sheetView[0].showGridLines = True

    headers = ["N° Avis", "Acheteur", "Objet", "Région", "Date limite", "Cautionnement", "Secteur", "Lien TUNEPS"]

    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )
    header_border = Border(
        left=Side(style="thin", color="1E3A8A"),
        right=Side(style="thin", color="1E3A8A"),
        top=Side(style="thin", color="1E3A8A"),
        bottom=Side(style="medium", color="0F172A"),
    )
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    ws.append(headers)
    ws.row_dimensions[1].height = 26

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = header_border

    for row_idx, t in enumerate(tenders, start=2):
        row_vals = [
            t.get("bid_no") or "",
            t.get("buyer_name") or "",
            t.get("title_fr") or t.get("title_ar") or "",
            t.get("governorate") or t.get("execution_place") or "",
            t.get("deadline_date") or "",
            t.get("guarantee_type") or "",
            t.get("category") or "",
            t.get("url") or "",
        ]
        ws.append(row_vals)
        ws.row_dimensions[row_idx].height = 20
        is_zebra = (row_idx % 2 == 0)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if is_zebra:
                cell.fill = zebra_fill
            if col_idx in (1, 4, 5, 6):
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    for col_idx, header in enumerate(headers, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = len(header)
        for row in range(2, len(tenders) + 2):
            val = str(ws.cell(row=row, column=col_idx).value or "")
            if len(val) > max_len:
                max_len = len(val)
        ws.column_dimensions[col_letter].width = max(12, min(max_len + 3, 60))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@app.get("/api/client/opportunities/{sub_id}/export")
def export_client_opportunities(sub_id: int, format: str = Query("xlsx", pattern="^(xlsx|csv)$")):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")

    tenders = db.get_subscriber_matched_tenders(sub_id, limit=500)
    fmt = (format or "xlsx").lower()

    if fmt == "csv":
        csv_bytes = generate_opportunities_csv(tenders)
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="opportunites_tenders_tn_{sub_id}.csv"'
            }
        )
    else:
        xlsx_bytes = generate_opportunities_xlsx(tenders)
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="opportunites_tenders_tn_{sub_id}.xlsx"'
            }
        )


@app.get("/api/client/opportunities/{sub_id}/export.xlsx")
def export_client_opportunities_xlsx(sub_id: int):
    return export_client_opportunities(sub_id=sub_id, format="xlsx")


@app.get("/api/client/opportunities/{sub_id}/export.csv")
def export_client_opportunities_csv(sub_id: int):
    return export_client_opportunities(sub_id=sub_id, format="csv")


@app.get("/api/client/bookmarks/{sub_id}")
def get_client_bookmarks(sub_id: int):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    bookmarks = db.get_subscriber_bookmarks(sub_id)
    return {"total": len(bookmarks), "bookmarks": bookmarks, "subscriber_id": sub.id}

@app.post("/api/client/bookmark")
def add_or_update_client_bookmark(req: BookmarkRequest):
    sub = db.get_subscriber_by_id(req.subscriber_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    res = db.add_or_update_bookmark(
        subscriber_id=req.subscriber_id,
        tender_id=req.tender_id,
        status=req.status or "A_ETUDIER",
        notes=req.notes or ""
    )
    return res

@app.delete("/api/client/bookmark/{sub_id}/{tender_id}")
def delete_client_bookmark(sub_id: int, tender_id: int):
    deleted = db.remove_bookmark(sub_id, tender_id)
    return {"status": "SUCCESS" if deleted else "NOT_FOUND"}

@app.post("/api/client/test-alert/{sub_id}")
def test_client_whatsapp_alert(sub_id: int):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    
    opportunities = db.get_subscriber_matched_tenders(sub_id, limit=1)
    if not opportunities:
        recent = db.search_tenders(only_open=True, limit=1)["tenders"]
        sample_tender = recent[0] if recent else None
    else:
        sample_tender = opportunities[0]

    if not sample_tender:
        return {"status": "NO_TENDERS_FOUND"}

    from whatsapp_gateway import send_whatsapp_message
    if isinstance(sample_tender, dict):
        title = sample_tender.get("title_fr") or sample_tender.get("title_ar") or "Marché Public"
        buyer = sample_tender.get("buyer_name") or "Acheteur Public"
        deadline = (sample_tender.get("deadline_date") or "")[:16]
        url = sample_tender.get("url") or "https://www.tuneps.tn"
        cat = sample_tender.get("category") or "Général"
        gov = sample_tender.get("governorate") or "Tunisie"
        summary = sample_tender.get("ai_summary") or ""
    else:
        title = sample_tender.title_fr or sample_tender.title_ar or "Marché Public"
        buyer = sample_tender.buyer_name or "Acheteur Public"
        deadline = (sample_tender.deadline_date or "")[:16]
        url = sample_tender.url or "https://www.tuneps.tn"
        cat = sample_tender.category or "Général"
        gov = sample_tender.governorate or "Tunisie"
        summary = sample_tender.ai_summary or ""

    msg = (
        f"🔔 *[TEST ALERTE TENDERS.TN]*\n"
        f"Bonjour *{sub.company_name}*,\n\n"
        f"Voici un exemple d'opportunité ciblée selon vos critères :\n\n"
        f"📌 *{title}*\n"
        f"🏛️ *Acheteur :* {buyer}\n"
        f"📂 *Secteur :* {cat}\n"
        f"📍 *Gouvernorat :* {gov}\n"
        f"⏳ *Date Limite :* {deadline}\n"
    )
    if summary:
        msg += f"\n💡 *Analyse IA :* {summary[:180]}...\n"
    msg += f"\n🔗 *Lien Cahier des Charges :* {url}\n\n"
    msg += f"✅ *Votre Dashboard Client :* {BASE_URL}/dashboard"

    success = send_whatsapp_message(sub.phone, msg)
    return {"status": "SENT" if success else "FAILED", "phone": sub.phone}

@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/client", response_class=HTMLResponse)
def render_client_dashboard():
    """Sert l'interface du Dashboard Client Privé."""
    content = _find_html_content("dashboard.html")
    if content:
        return content
    return "<h1>Dashboard client en cours de génération... (dashboard.html introuvable)</h1>"

# --- Feature 1 : Checklist Administrative & Modèle d'Engagement Décret 2014-1039 ---

@app.get("/api/tenders/{tender_id}/checklist")
def get_tender_checklist_api(tender_id: int, company_name: Optional[str] = "L'ENTREPRISE SOUMISSIONNAIRE"):
    """Génère la checklist administrative et le modèle d'acte d'engagement officiel."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")

    bid_no = t.get("bid_no", "")
    buyer = t.get("buyer_name", "")
    title = t.get("title_fr") or t.get("title_ar") or ""
    guarantee = t.get("guarantee_type") or "Non requis"
    doc_price = t.get("doc_price") or "Gratuit"
    deadline = (t.get("deadline_date") or "")[:16]

    admin_items = [
        {"title": "Attestation de régularité CNSS", "desc": "En cours de validité (délivrée depuis moins de 3 mois)", "mandatory": True},
        {"title": "Quittance de déclaration fiscale", "desc": "Certificat de régularité fiscale de l'exercice en cours", "mandatory": True},
        {"title": "Extrait du Registre National des Entreprises (RNE)", "desc": "Extrait récent prouvant l'immatriculation légale de l'entreprise", "mandatory": True},
        {"title": "Déclaration sur l'honneur (Art. 54 du Décret)", "desc": "Attestation de non-faillite, non-redressement et non-interdiction de soumissionner", "mandatory": True},
    ]

    if "non requis" not in guarantee.lower():
        admin_items.append({
            "title": f"Cautionnement bancaire provisoire ({guarantee})",
            "desc": "Émis par un établissement bancaire tunisien agréé ou reçu de versement auprès de la trésorerie générale",
            "mandatory": True
        })

    if "gratuit" not in doc_price.lower() and "0" not in doc_price:
        admin_items.append({
            "title": f"Reçu de paiement du Cahier des Charges ({doc_price})",
            "desc": "Preuve d'achat du dossier d'appel d'offres",
            "mandatory": True
        })

    technical_items = [
        {"title": "Cahier des Clauses Administratives et Techniques (CCAP/CCTP)", "desc": "Paraphé sur chaque page, daté et revêtu du cachet et signature de l'entreprise", "mandatory": True},
        {"title": "Mémoire technique d'exécution", "desc": "Méthodologie détaillée, planning prévisionnel et moyens humains/matériels affectés", "mandatory": True},
        {"title": "Références professionnelles similaires", "desc": "Attestations de bonne fin d'exécution de marchés analogues", "mandatory": False}
    ]

    financial_items = [
        {"title": "Acte d'engagement et de soumission financière", "desc": "Chiffré en toutes lettres et chiffres hors taxes (HT) et toutes taxes comprises (TTC)", "mandatory": True},
        {"title": "Bordereau des Prix Unitaires (BPU)", "desc": "Complet avec prix fermes ou révisables selon stipulations du CDC", "mandatory": True},
        {"title": "Détail Quantitatif et Estimatif (DQE / Sous-détail)", "desc": "Sous-détail des prix pour chaque poste du bordereau", "mandatory": True}
    ]

    letter_template = (
        f"RÉPUBLIQUE TUNISIENNE\n"
        f"ACTE DE SOUMISSION ET D'ENGAGEMENT FINANCIER\n"
        f"(Conforme aux dispositions du Décret n° 2014-1039 portant réglementation des marchés publics)\n\n"
        f"À l'attention de : {buyer}\n"
        f"Objet du Marché : {title}\n"
        f"Référence TUNEPS : N° {bid_no}\n"
        f"Date limite de remise des plis : {deadline}\n\n"
        f"Je soussigné(e), agissant au nom et pour le compte de la société :\n"
        f"Raison Sociale : {company_name}\n"
        f"Matricule Fiscal / RNE : _____________________\n"
        f"Adresse du Siège Social : _____________________\n\n"
        f"Après avoir pris pleine et entière connaissance de l'ensemble des pièces composant le dossier d'appel d'offres susvisé ;\n"
        f"Après avoir apprécié à mon point de vue et sous ma seule responsabilité la nature et les difficultés des prestations à réaliser ;\n\n"
        f"M'ENGAGE à exécuter lesdites prestations conformément aux prescriptions du Cahier des Charges moyennant les prix unitaires et forfaitaires mentionnés au bordereau des prix.\n\n"
        f"Montant Total de la Soumission :\n"
        f"- En Chiffres (TTC) : ______________ Dinars Tunisiens (TND)\n"
        f"- En Toutes Lettres (TTC) : __________________________________ Dinars Tunisiens.\n\n"
        f"Je confirme que ma soumission demeure valable pendant un délai de 90 jours à compter du lendemain de la date limite de réception des offres.\n\n"
        f"Fait à _______________, le _______________\n"
        f"Signature et Cachet du Soumissionnaire"
    )

    return {
        "tender_id": tender_id,
        "bid_no": bid_no,
        "buyer_name": buyer,
        "admin_checklist": admin_items,
        "technical_checklist": technical_items,
        "financial_checklist": financial_items,
        "letter_template": letter_template
    }

# --- Rédacteur IA de Mémoire Technique & Proposition Commerciale (Décret 2014-1039) ---

def generate_technical_proposal(t: dict, company_name: str = "L'ENTREPRISE SOUMISSIONNAIRE") -> dict:
    title = t.get("title_fr") or t.get("title_ar") or "Prestations de Marché Public"
    buyer = t.get("buyer_name") or "L'Acheteur Public"
    bid_no = t.get("bid_no") or "N/A"
    cat = (t.get("category") or "Général").upper()
    gov = t.get("governorate") or "National"
    deadline = (t.get("deadline_date") or "")[:16]
    eval_m = t.get("eval_method") or "Moins disant"

    if any(k in cat.lower() for k in ["format", "educ", "pedag"]):
        sector_type = "TRAINING"
        phase2_title = "Ingénierie Pédagogique & Animation des Sessions de Formation"
        phase2_desc = (
            f"1. Conception sur-mesure des supports pédagogiques, manuels participants et cas pratiques contextualisés aux besoins de {buyer}.\n"
            f"2. Déploiement des ateliers de formation animés par des formateurs certifiés de {company_name}.\n"
            f"3. Modalités pédagogiques mixtes (théorie, ateliers interactifs, simulations et cas d'usage réels)."
        )
        resources_desc = (
            f"- Chef de Projet Formation Dédié : Coordination globale, suivi de l'assiduité et reporting hebdomadaire.\n"
            f"- Formateurs Experts Seniors : Spécialistes certifiés justifiant de plus de 7 ans d'expérience pratique dans le domaine.\n"
            f"- Plateforme Digitale d'Accompagnement : Mise à disposition des supports en ligne et ressources téléchargeables."
        )
        quality_desc = (
            f"- Évaluation à chaud à la fin de chaque module (taux de satisfaction cible > 90%).\n"
            f"- Évaluation des acquis et délivrance d'attestations nominatives de compétences conformes aux standards tunisiens.\n"
            f"- Rapport de clôture pédagogique remis à la direction de {buyer}."
        )
    elif any(k in cat.lower() for k in ["info", "logic", "telecom", "reseau", "syst", "matér"]):
        sector_type = "IT"
        phase2_title = "Architecture, Paramétrage & Déploiement de la Solution"
        phase2_desc = (
            f"1. Architecture technique et conception détaillée respectant les directives de sécurité de l'ANSI.\n"
            f"2. Intégration continue, paramétrage modulaire et sécurisation des flux de données pour {buyer}.\n"
            f"3. Campagne rigoureuse de tests unitaires, d'intégration et de charge avant recette provisoire."
        )
        resources_desc = (
            f"- Directeur de Projet Technique : Pilotage méthodologique (Agile/Scrum), interface unique avec la commission TUNEPS.\n"
            f"- Ingénieurs et Consultants Experts : Spécialistes certifiés garantissant l'adéquation aux standards technologiques.\n"
            f"- Environnement de Pré-production & Outils de versioning sécurisés."
        )
        quality_desc = (
            f"- Conformité au Plan d'Assurance Sécurité (PAS) et chiffrement des données sensibles.\n"
            f"- Garantie logicielle pièces et main d'œuvre de 12 mois minimum avec engagement de SLA d'intervention < 4 heures.\n"
            f"- Transfert de compétences complet auprès des équipes techniques de {buyer}."
        )
    elif any(k in cat.lower() for k in ["travaux", "batiment", "genie", "const"]):
        sector_type = "WORKS"
        phase2_title = "Exécution des Travaux, Logistique & Pilotage de Chantier"
        phase2_desc = (
            f"1. Installation de chantier, balisage sécurisé et mise en place du Plan d'Hygiène et de Sécurité (PHS).\n"
            f"2. Approvisionnement en matériaux conformes aux normes tunisiennes (NT) et homologués par le maître d'œuvre.\n"
            f"3. Exécution phasée des travaux avec réunions de chantier hebdomadaires et PV contradictoires."
        )
        resources_desc = (
            f"- Conducteur de Travaux / Ingénieur Génie Civil : Présence continue sur site ({gov}).\n"
            f"- Équipes techniques qualifiées et chefs d'équipes chevronnés.\n"
            f"- Matériel lourd et outillage moderne répondant aux normes de sécurité en vigueur."
        )
        quality_desc = (
            f"- Contrôles géotechniques et essais de laboratoire agréés pour chaque lot exécuté.\n"
            f"- Respect strict des délais contractuels avec calendrier d'avancement mis à jour en temps réel.\n"
            f"- Garantie décennale et parfaite conformité avant réception définitive."
        )
    elif any(k in cat.lower() for k in ["fourniture", "materiel", "equip"]):
        sector_type = "SUPPLIES"
        phase2_title = "Fabrication, Approvisionnement, Livraison & Mise en Service"
        phase2_desc = (
            f"1. Sélection rigoureuse d'équipements 100% neufs, d'origine constructeur certifiée et sous emballage d'origine.\n"
            f"2. Logistique sécurisée et livraison franco de port dans les magasins de {buyer} à {gov}.\n"
            f"3. Installation, branchement, configuration et tests de bon fonctionnement sur site."
        )
        resources_desc = (
            f"- Responsable Logistique & Déploiement : Suivi en temps réel de l'acheminement des commandes.\n"
            f"- Techniciens d'Installation & SAV : Spécialistes habilités pour la mise en service.\n"
            f"- Magasin central de pièces de rechange garantissant un réapprovisionnement immédiat."
        )
        quality_desc = (
            f"- Garantie totale constructeur et pièces de rechange garanties disponibles sur 5 ans.\n"
            f"- Procès-verbal de réception technique provisoire et définitive contradictoire.\n"
            f"- Assistance technique et hotline d'intervention rapide sur site."
        )
    else:
        sector_type = "SERVICES"
        phase2_title = "Déploiement Opérationnel & Réalisation des Prestations"
        phase2_desc = (
            f"1. Mobilisation immédiate des ressources et outils nécessaires dès notification de l'ordre de service.\n"
            f"2. Exécution rigoureuse des livrables selon les spécifications techniques du Cahier des Charges de {buyer}.\n"
            f"3. Restitution d'étapes et validation conjointe avec le comité de suivi."
        )
        resources_desc = (
            f"- Chef de Mission Dédié : Point de contact privilégié pour le suivi contractuel.\n"
            f"- Équipe de consultants et spécialistes qualifiés mobilisés selon les besoins.\n"
            f"- Outils de reporting automatisés pour un suivi transparent."
        )
        quality_desc = (
            f"- Charte de qualité stricte et conformité continue aux exigences du Décret 2014-1039.\n"
            f"- Traçabilité intégrale de chaque prestation réalisée.\n"
            f"- Bilan de fin de mission avec recommandations d'optimisation."
        )

    sections = [
        {
            "title": "1. Compréhension du Projet & Enjeux Stratégiques",
            "content": (
                f"Dans le cadre de l'avis de marché public N° {bid_no} émis par {buyer}, l'entreprise {company_name} a analysé minutieusement les exigences fonctionnelles et réglementaires.\n\n"
                f"L'objectif premier de notre offre est de garantir une exécution sans faille des prestations relatives à : \"{title}\".\n\n"
                f"Notre intervention est articulée pour assurer une parfaite continuité de service, une adéquation aux spécifications du cahier des charges et une optimisation des coûts dans le respect des règles de la commande publique tunisienne."
            ),
            "highlights": [
                f"Conformité intégrale au Décret n° 2014-1039 relatif aux marchés publics",
                f"Intervention ciblée sur le gouvernorat de {gov}",
                f"Optimisation du rapport qualité/prix évalué selon la méthode '{eval_m}'"
            ]
        },
        {
            "title": "2. Démarche Méthodologique & Phasage Opérationnel",
            "content": (
                f"Notre démarche est structurée en 4 phases complémentaires garantissant une maîtrise totale des livrables :\n\n"
                f"• PHASE 1 : Cadrage & Réunion de Lancement\n"
                f"Alignement avec la commission de suivi de {buyer}, validation du calendrier détaillé et formalisation du plan de gestion de projet.\n\n"
                f"• PHASE 2 : {phase2_title}\n"
                f"{phase2_desc}\n\n"
                f"• PHASE 3 : Recette Provisoire & Ajustements\n"
                f"Contrôles contradictoires, levée immédiate des éventuelles réserves et délivrance du procès-verbal provisoire.\n\n"
                f"• PHASE 4 : Clôture, Transfert & Recette Définitive\n"
                f"Remise du dossier technique final, bilan d'exécution et mise en place de la garantie contractuelle."
            ),
            "highlights": [
                "Pilotage transparent avec jalons d'approbation formels",
                "Gestion proactive des risques et aléas opérationnels",
                "Livrables documentés et archivables selon les normes TUNEPS"
            ]
        },
        {
            "title": "3. Organisation de l'Équipe & Moyens Affectés",
            "content": (
                f"Pour répondre aux exigences de {buyer}, la société {company_name} déploie une équipe experte dédiée :\n\n"
                f"{resources_desc}\n\n"
                f"Tous nos intervenants sont tenus par une clause de confidentialité stricte et s'engagent à respecter l'ensemble des règles de sécurité et de déontologie en vigueur."
            ),
            "highlights": [
                "Interlocuteur unique (Chef de Projet) joignable 24/7",
                "Remplacement garanti sous 48h en cas d'indisponibilité fortuite d'un intervenant",
                "CV et diplômes certifiés conformes disponibles dans l'offre technique"
            ]
        },
        {
            "title": "4. Calendrier d'Exécution & Respect des Délais",
            "content": (
                f"L'organisation temporelle du projet a été calibrée pour garantir un respect strict des délais fixés par le Cahier des Charges :\n\n"
                f"- T0 (Notification de l'Ordre de Service) : Démarrage sous 5 jours ouvrés.\n"
                f"- T0 + 10 jours : Remise de la note de cadrage et validation par {buyer}.\n"
                f"- Déploiement opérationnel échelonné selon le planning convenu.\n"
                f"- Clôture et remise des rapports préalablement à l'échéance contractuelle finale.\n\n"
                f"Un état d'avancement périodique sera transmis pour assurer une visibilité complète à la commission des marchés."
            ),
            "highlights": [
                "Zéro dépassement de délai garanti",
                "Tableau de bord de suivi partagé hebdomadairement",
                "Anticipation des jalons de validation intermédiaire"
            ]
        },
        {
            "title": "5. Plan d'Assurance Qualité (PAQ) & Engagements RSE",
            "content": (
                f"La politique qualité de {company_name} repose sur des contrôles permanents à chaque stade de production :\n\n"
                f"{quality_desc}\n\n"
                f"Sur le plan environnemental et sociétal (RSE), nos procédures favorisent la dématérialisation via TUNEPS, la réduction de l'empreinte carbone et l'éthique commerciale."
            ),
            "highlights": [
                "Traçabilité rigoureuse et archivage sécurisé",
                "Conformité aux normes nationales et internationales",
                "Engagement citoyen et éco-responsable"
            ]
        },
        {
            "title": "6. Garantie Contractuelle & Service Après-Vente (SLA)",
            "content": (
                f"Conformément aux stipulations du marché, {company_name} applique les garanties suivantes :\n\n"
                f"- Prise en charge immédiate de toute anomalie signalée par {buyer}.\n"
                f"- Assistance technique et support joignables par téléphone, email et canal d'urgence.\n"
                f"- Délai de prise en compte : sous 2 heures ouvrées.\n"
                f"- Délai d'intervention sur site ou résolution : sous 24 heures maximum."
            ),
            "highlights": [
                "Support réactif garanti sur toute la durée de validité du contrat",
                "Maintien en conditions opérationnelles sans surcoût",
                "Attestation de caution bancaire et engagement légal joints à l'offre"
            ]
        }
    ]

    raw_md_parts = [
        "# RÉPUBLIQUE TUNISIENNE",
        "## MARCHÉS PUBLICS (DÉCRET N° 2014-1039)",
        "### MÉMOIRE TECHNIQUE D'EXÉCUTION\n",
        f"**Objet du Marché :** {title}",
        f"**Acheteur Public :** {buyer}",
        f"**Référence Avis TUNEPS :** {bid_no}",
        f"**Soumissionnaire :** {company_name}",
        f"**Date Limite de Remise :** {deadline}\n",
        "---"
    ]
    for sec in sections:
        raw_md_parts.append(f"\n## {sec['title']}\n")
        raw_md_parts.append(sec["content"])
        if sec.get("highlights"):
            raw_md_parts.append("\n**Engagements clés :**")
            for h in sec["highlights"]:
                raw_md_parts.append(f"- {h}")
    raw_md_parts.append(f"\n---\n**Fait pour valoir engagement contractuel.**\n**Pour {company_name}**\nSignature et Cachet")
    raw_markdown = "\n".join(raw_md_parts)

    return {
        "tender_id": t.get("ep_bid_master_id") or t.get("id"),
        "bid_no": bid_no,
        "title": title,
        "buyer_name": buyer,
        "company_name": company_name,
        "sector_type": sector_type,
        "sections": sections,
        "raw_markdown": raw_markdown
    }

@app.get("/api/tenders/{tender_id}/technical-proposal")
def get_technical_proposal_api(tender_id: int, company_name: Optional[str] = "ADVANCIA TRAINING"):
    """Génère le mémoire technique complet personnalisé pour l'offre."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    return generate_technical_proposal(t, company_name=company_name or "ADVANCIA TRAINING")

@app.get("/tender/{tender_id}/proposal-print", response_class=HTMLResponse)
def render_proposal_printable(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    """Sert la version imprimable et exportable pour Word / PDF du Mémoire Technique."""
    import jinja2
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {
        "subscriber_id": sub.id if sub else None,
        "company_name": sub.company_name if sub else None,
        "logo_url": sub.logo_url if sub else None,
        "rne_id": sub.rne_id if sub else None,
        "address": sub.address if sub else None,
        "phone_office": sub.phone_office if sub else None,
        "bank_name": sub.bank_name if sub else None,
        "rib": sub.rib if sub else None
    } if sub else None
    proposal = generate_technical_proposal(t, company_name=comp_name)
    template_path = os.path.join(os.path.dirname(__file__), "templates", "print_proposal.html")
    with open(template_path, "r", encoding="utf-8") as f:
        tmpl = jinja2.Template(f.read())
    return tmpl.render(
        tender=t,
        company_name=comp_name,
        proposal=proposal,
        raw_markdown=proposal["raw_markdown"],
        company_profile=profile
    )

# --- Rédacteur IA d'Offre Commerciale & Financière (BPU / DQE / Décret 2014-1039) ---

def amount_to_french_words(amount: float) -> str:
    units = ['', 'un', 'deux', 'trois', 'quatre', 'cinq', 'six', 'sept', 'huit', 'neuf']
    teens = ['dix', 'onze', 'douze', 'treize', 'quatorze', 'quinze', 'seize', 'dix-sept', 'dix-huit', 'dix-neuf']
    tens = ['', 'dix', 'vingt', 'trente', 'quarante', 'cinquante', 'soixante', 'soixante-dix', 'quatre-vingt', 'quatre-vingt-dix']

    def convert_below_thousand(n):
        if n == 0: return ''
        res = []
        c = n // 100
        r = n % 100
        if c == 1:
            res.append('cent')
        elif c > 1:
            res.append(units[c] + ' cents' if r == 0 else units[c] + ' cent')
        if r < 10:
            if r > 0: res.append(units[r])
        elif r < 20:
            res.append(teens[r - 10])
        else:
            t = r // 10
            u = r % 10
            if t == 7:
                res.append('soixante-et-onze' if u == 1 else 'soixante-' + teens[u])
            elif t == 8:
                res.append('quatre-vingts' if u == 0 else 'quatre-vingt-' + units[u])
            elif t == 9:
                res.append('quatre-vingt-' + teens[u])
            else:
                res.append(tens[t] + ('-et-un' if u == 1 else ('-' + units[u] if u > 0 else '')))
        return ' '.join(res).strip()

    entier = int(amount)
    millions = entier // 1000000
    reste_mil = entier % 1000000
    mille = reste_mil // 1000
    reste = reste_mil % 1000

    parts = []
    if millions == 1: parts.append('un million')
    elif millions > 1: parts.append(convert_below_thousand(millions) + ' millions')
    if mille == 1: parts.append('mille')
    elif mille > 1: parts.append(convert_below_thousand(mille) + ' mille')
    if reste > 0: parts.append(convert_below_thousand(reste))

    millimes = int(round((amount - entier) * 1000))
    mots = ' '.join(parts).capitalize() or 'Zéro'
    res = f'{mots} Dinars'
    if millimes > 0:
        res += f' et {convert_below_thousand(millimes)} Millimes'
    return res

class CommercialItem(BaseModel):
    designation: str
    unit: str
    quantity: float
    unit_price: float
    total_price: Optional[float] = None

class CommercialProposalRequest(BaseModel):
    company_name: Optional[str] = "ADVANCIA TRAINING"
    tva_rate: Optional[float] = 0.19
    items: Optional[List[CommercialItem]] = None

def generate_commercial_proposal(t: dict, company_name: str = "ADVANCIA TRAINING", custom_items: list = None, tva_rate: float = 0.19) -> dict:
    title = t.get("title_fr") or t.get("title_ar") or "Prestations de Marché Public"
    buyer = t.get("buyer_name") or "L'Acheteur Public"
    bid_no = t.get("bid_no") or "N/A"
    cat = (t.get("category") or "Général").upper()
    deadline = (t.get("deadline_date") or "")[:16]

    items = []
    if custom_items and len(custom_items) > 0:
        for it in custom_items:
            q = float(it.get("quantity") if isinstance(it, dict) else it.quantity)
            pu = float(it.get("unit_price") if isinstance(it, dict) else it.unit_price)
            items.append({
                "designation": it.get("designation") if isinstance(it, dict) else it.designation,
                "unit": it.get("unit") if isinstance(it, dict) else it.unit,
                "quantity": q,
                "unit_price": round(pu, 3),
                "total_price": round(q * pu, 3)
            })
    else:
        if any(k in cat.lower() for k in ["format", "educ", "pedag"]):
            raw_items = [
                ("Conception de l'ingénierie pédagogique et élaboration des supports", "Forfait", 1, 2400.0),
                ("Animation des sessions de formation certifiée (Jour / Homme)", "J/H", 12, 650.0),
                ("Organisation logistique, plateforme en ligne et ateliers pratiques", "Forfait", 1, 1500.0),
                ("Évaluation des acquis, attestations nominatives et rapport final", "Forfait", 1, 1100.0)
            ]
        elif any(k in cat.lower() for k in ["info", "logic", "telecom", "reseau", "syst", "matér"]):
            raw_items = [
                ("Analyse préliminaire, architecture technique et spécifications", "Forfait", 1, 3500.0),
                ("Développement, paramétrage et intégration modulaire", "J/H", 18, 750.0),
                ("Recette technique, tests d'intrusion et mise en production", "Forfait", 1, 2800.0),
                ("Maintenance corrective, évolutive et support technique (1 an)", "Forfait", 1, 4200.0)
            ]
        elif any(k in cat.lower() for k in ["travaux", "batiment", "genie", "const"]):
            raw_items = [
                ("Installation de chantier, balisage et plan d'hygiène et sécurité", "Forfait", 1, 3500.0),
                ("Approvisionnement en matériaux conformes aux normes tunisiennes (NT)", "Lot", 1, 14500.0),
                ("Exécution des travaux selon prescriptions du Cahier des Charges", "Forfait", 1, 22000.0),
                ("Nettoyage de fin de chantier, épreuves et réceptions techniques", "Forfait", 1, 1800.0)
            ]
        elif any(k in cat.lower() for k in ["fourniture", "materiel", "equip"]):
            raw_items = [
                ("Fourniture d'équipements neufs d'origine constructeur homologuée", "Unité", 10, 1850.0),
                ("Transport, acheminement et livraison franco de port", "Forfait", 1, 800.0),
                ("Montage, configuration et mise en service sur site", "Forfait", 1, 1200.0),
                ("Garantie constructeur et pièces de rechange (2 ans)", "Forfait", 1, 950.0)
            ]
        else:
            raw_items = [
                ("Phase de cadrage, diagnostic méthodologique et note d'orientation", "Forfait", 1, 2800.0),
                ("Réalisation opérationnelle des prestations spécialisées", "J/H", 15, 600.0),
                ("Rapport de synthèse, livrables contractuels et restitution", "Forfait", 1, 1600.0)
            ]

        for des, un, q, pu in raw_items:
            items.append({
                "designation": des,
                "unit": un,
                "quantity": q,
                "unit_price": round(pu, 3),
                "total_price": round(q * pu, 3)
            })

    total_ht = round(sum(it["total_price"] for it in items), 3)
    tva_amount = round(total_ht * tva_rate, 3)
    timbre_fiscal = 1.000
    total_ttc = round(total_ht + tva_amount + timbre_fiscal, 3)
    retenue_source_rate = 0.015
    retenue_source_amount = round(total_ht * retenue_source_rate, 3)
    net_a_percevoir = round(total_ttc - retenue_source_amount, 3)
    caution_provisoire = round(total_ht * 0.01, 3)
    total_ttc_words = amount_to_french_words(total_ttc)

    md_lines = [
        f"# BORDEREAU DES PRIX UNITAIRES & OFFRE FINANCIÈRE",
        f"**Objet du Marché :** {title}",
        f"**Acheteur Public :** {buyer}",
        f"**Avis N° TUNEPS :** {bid_no}",
        f"**Soumissionnaire :** {company_name}",
        f"**Date Limite :** {deadline}\n",
        "| N° | Désignation des Prestations | Unité | Qté | Prix Unitaire HT (TND) | Total HT (TND) |",
        "|---|---|:---:|:---:|---:|---:|"
    ]
    for i, it in enumerate(items, 1):
        md_lines.append(f"| {i} | {it['designation']} | {it['unit']} | {it['quantity']} | {it['unit_price']:,.3f} | {it['total_price']:,.3f} |")

    md_lines.extend([
        "",
        f"- **Total Général Hors Taxes (HT) :** {total_ht:,.3f} TND",
        f"- **TVA ({int(tva_rate * 100)}%) :** {tva_amount:,.3f} TND",
        f"- **Droit de Timbre Fiscal :** {timbre_fiscal:,.3f} TND",
        f"- **MONTANT TOTAL TTC :** {total_ttc:,.3f} TND",
        f"- **Arrêté en toutes lettres :** {total_ttc_words} TTC.",
        f"- **Retenue à la source réglementaire (1.5%) :** {retenue_source_amount:,.3f} TND",
        f"- **Montant Net estimé à percevoir :** {net_a_percevoir:,.3f} TND",
        f"- **Cautionnement bancaire provisoire estimé (1%) :** {caution_provisoire:,.3f} TND"
    ])
    raw_markdown = "\n".join(md_lines)

    return {
        "tender_id": t.get("ep_bid_master_id") or t.get("id"),
        "bid_no": bid_no,
        "title": title,
        "buyer_name": buyer,
        "company_name": company_name,
        "items": items,
        "total_ht": total_ht,
        "tva_rate": tva_rate,
        "tva_amount": tva_amount,
        "timbre_fiscal": timbre_fiscal,
        "total_ttc": total_ttc,
        "retenue_source_rate": retenue_source_rate,
        "retenue_source_amount": retenue_source_amount,
        "net_a_percevoir": net_a_percevoir,
        "caution_provisoire": caution_provisoire,
        "total_ttc_words": total_ttc_words,
        "raw_markdown": raw_markdown
    }

@app.get("/api/tenders/{tender_id}/commercial-proposal")
def get_commercial_proposal_api(tender_id: int, company_name: Optional[str] = "ADVANCIA TRAINING", tva_rate: Optional[float] = 0.19):
    """Génère le bordereau des prix unitaires et le chiffrage financier officiel."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    return generate_commercial_proposal(t, company_name=company_name or "ADVANCIA TRAINING", tva_rate=tva_rate or 0.19)

@app.post("/api/tenders/{tender_id}/commercial-proposal")
def post_commercial_proposal_api(tender_id: int, req: CommercialProposalRequest):
    """Recalcule instantanément l'offre financière avec des prix ou quantités personnalisés."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    return generate_commercial_proposal(
        t,
        company_name=req.company_name or "ADVANCIA TRAINING",
        custom_items=[it.dict() for it in req.items] if req.items else None,
        tva_rate=req.tva_rate or 0.19
    )

@app.get("/tender/{tender_id}/commercial-print", response_class=HTMLResponse)
def render_commercial_printable(tender_id: int, company_name: Optional[str] = None, tva_rate: Optional[float] = 0.19, sub_id: Optional[int] = None):
    """Sert la version imprimable et exportable officielle du Bordereau des Prix (BPU / DQE)."""
    import jinja2
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {
        "subscriber_id": sub.id if sub else None,
        "company_name": sub.company_name if sub else None,
        "logo_url": sub.logo_url if sub else None,
        "rne_id": sub.rne_id if sub else None,
        "address": sub.address if sub else None,
        "phone_office": sub.phone_office if sub else None,
        "bank_name": sub.bank_name if sub else None,
        "rib": sub.rib if sub else None
    } if sub else None
    commercial = generate_commercial_proposal(t, company_name=comp_name, tva_rate=tva_rate or 0.19)
    template_path = os.path.join(os.path.dirname(__file__), "templates", "print_commercial.html")
    with open(template_path, "r", encoding="utf-8") as f:
        tmpl = jinja2.Template(f.read())
    return tmpl.render(
        tender=t,
        company_name=comp_name,
        commercial=commercial,
        company_profile=profile
    )

# --- Détecteur IA de Risques & Demande d'Éclaircissement HAICOP (Décret 2014-1039) ---

def analyze_tender_risks_and_clarification(t: dict, company_name: str = "ADVANCIA TRAINING") -> dict:
    title = t.get("title_fr") or t.get("title_ar") or "Marché Public"
    buyer = t.get("buyer_name") or "L'Acheteur Public"
    bid_no = t.get("bid_no") or "N/A"
    deadline_str = t.get("deadline_date") or ""
    guarantee = t.get("guarantee_type") or "Non requis"
    eval_m = t.get("eval_method") or "Moins disant"
    cat = (t.get("category") or "Général").upper()

    days_left = 15
    if deadline_str:
        try:
            dl = datetime.fromisoformat(deadline_str.replace("Z", "").split(".")[0])
            days_left = max(0, (dl - datetime.now()).days)
        except Exception:
            pass

    score = 25
    risk_factors = []

    if days_left < 8:
        score += 35
        risk_factors.append({
            "level": "HIGH",
            "badge": "🔴 Critique",
            "title": "Délai d'urgence extrême (< 8 jours)",
            "desc": f"Il ne reste que {days_left} jours avant la remise des plis. Risque élevé de rejet pour retard ou de dossier incomplet. Demande de report recommandée (Art. 50)."
        })
    elif days_left < 15:
        score += 15
        risk_factors.append({
            "level": "MEDIUM",
            "badge": "🟡 Vigilance",
            "title": "Délai de préparation serré (8-15 jours)",
            "desc": f"Délai restant de {days_left} jours. Exige d'engager sans délai la caution bancaire provisoire et le rassemblement des attestations fiscales."
        })
    else:
        risk_factors.append({
            "level": "LOW",
            "badge": "🟢 Favorable",
            "title": f"Délai d'étude confortable ({days_left} jours)",
            "desc": "Période suffisante pour structurer un mémoire technique approfondi et optimiser l'offre financière."
        })

    if "non requis" not in guarantee.lower() and "sans" not in guarantee.lower():
        score += 20
        risk_factors.append({
            "level": "MEDIUM",
            "badge": "🟡 Vigilance",
            "title": f"Cautionnement provisoire exigé ({guarantee})",
            "desc": "Obligation d'émettre une garantie bancaire sous peine de rejet irrévocable de l'offre à l'ouverture des plis (Art. 54)."
        })
    else:
        risk_factors.append({
            "level": "LOW",
            "badge": "🟢 Favorable",
            "title": "Procédure allégée sans caution bancaire",
            "desc": "Aucune garantie financière préalable requise. Allègement de trésorerie direct pour votre entreprise."
        })

    if "moins disant" in eval_m.lower():
        score += 10
        risk_factors.append({
            "level": "MEDIUM",
            "badge": "🟡 Vigilance",
            "title": "Évaluation au Moins Disant strict",
            "desc": "Forte concurrence prévisible sur les prix. Risque de compression des marges par des offres anormalement basses."
        })
    else:
        risk_factors.append({
            "level": "LOW",
            "badge": "🟢 Favorable",
            "title": "Évaluation sur la qualité technique (Mieux Disant)",
            "desc": "La qualité de votre mémoire technique et les compétences de vos experts pèseront lourdement sur la note finale."
        })

    if score >= 60:
        global_level = "ÉLEVÉ"
        global_badge = "🔴 Risque Élevé - Vigilance requise"
        global_color = "rose"
    elif score >= 35:
        global_level = "MODÉRÉ"
        global_badge = "🟡 Risque Modéré - Procédure standard"
        global_color = "amber"
    else:
        global_level = "FAIBLE"
        global_badge = "🟢 Risque Faible - Excellente opportunité"
        global_color = "emerald"

    clarification_points = [
        {
            "title": "1. Principe d'équivalence technique et conformité des normes",
            "question": (
                f"Le Cahier des Clauses Techniques Particulières (CCTP) mentionne des spécifications techniques précises. "
                f"Nous sollicitons la confirmation expresse que des solutions techniques ou certifications équivalentes, "
                f"offrant des performances similaires ou supérieures, seront admises conformément à l'article 6 du Décret n° 2014-1039."
            ),
            "legal_basis": "Article 6 du Décret n° 2014-1039 (Interdiction des clauses discriminatoires et principe d'équivalence)"
        },
        {
            "title": "2. Précision sur les modalités de délivrance de la caution provisoire",
            "question": (
                f"Concernant le cautionnement provisoire ({guarantee}), nous souhaitons obtenir confirmation que la remise d'un récépissé "
                f"d'une banque tunisienne agréée ou d'une caution personnelle et solidaire conforme aux modèles officiels TUNEPS "
                f"est pleinement recevable sans obligation de versement préalable en espèces."
            ),
            "legal_basis": "Articles 54 et 55 du Décret n° 2014-1039 (Garanties financières et cautions de soumission)"
        }
    ]

    if days_left < 12:
        clarification_points.append({
            "title": "3. Demande de report de la date limite de réception des plis",
            "question": (
                f"Eu égard à la complexité des prestations requises et au délai résiduel de {days_left} jours, "
                f"nous sollicitons respectueusement de bien vouloir reporter la date limite de soumission de sept (07) jours ouvrés "
                f"afin de garantir une saine et loyale concurrence entre tous les opérateurs économiques intéressés."
            ),
            "legal_basis": "Article 50 du Décret n° 2014-1039 (Faculté de prorogation des délais en cas d'éclaircissements)"
        })

    raw_md_lines = [
        f"# DEMANDE D'ÉCLAIRCISSEMENT OFFICIELLE (DÉCRET N° 2014-1039)",
        f"**À l'attention de :** Monsieur le Président de la Commission des Marchés - {buyer}",
        f"**Objet du Marché :** {title}",
        f"**Avis N° TUNEPS :** {bid_no}",
        f"**Entreprise Requérante :** {company_name}",
        f"**Date limite actuelle :** {deadline_str[:16]}\n",
        "---",
        "Monsieur le Président, Mesdames et Messieurs les Membres de la Commission,\n",
        f"Dans le cadre de la préparation de notre soumission pour l'avis cité en référence, nous vous soumettons respectueusement les demandes d'éclaircissements ci-après :\n"
    ]
    for idx, p in enumerate(clarification_points, 1):
        raw_md_lines.extend([
            f"### Point N° {idx} : {p['title']}",
            f"{p['question']}",
            f"_Base réglementaire : {p['legal_basis']}_\n"
        ])
    raw_md_lines.extend([
        "---",
        "Dans l'attente de votre publication officielle sur TUNEPS, nous vous prions d'agréer l'assurance de notre considération distinguée.\n",
        f"**Pour {company_name}**",
        "Direction Générale"
    ])
    raw_markdown = "\n".join(raw_md_lines)

    return {
        "tender_id": t.get("ep_bid_master_id") or t.get("id"),
        "bid_no": bid_no,
        "title": title,
        "buyer_name": buyer,
        "company_name": company_name,
        "days_left": days_left,
        "score": score,
        "global_level": global_level,
        "global_badge": global_badge,
        "global_color": global_color,
        "risk_factors": risk_factors,
        "points": clarification_points,
        "clarification_points": clarification_points,
        "raw_markdown": raw_markdown
    }

@app.get("/api/tenders/{tender_id}/risk-analysis")
def get_tender_risk_analysis_api(tender_id: int, company_name: Optional[str] = "ADVANCIA TRAINING"):
    """Analyse les risques de rejet et génère la demande d'éclaircissement HAICOP."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    return analyze_tender_risks_and_clarification(t, company_name=company_name or "ADVANCIA TRAINING")

@app.get("/tender/{tender_id}/clarification-print", response_class=HTMLResponse)
def render_clarification_printable(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    """Sert la version imprimable officielle de la Demande d'Éclaircissement HAICOP."""
    import jinja2
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {
        "subscriber_id": sub.id if sub else None,
        "company_name": sub.company_name if sub else None,
        "logo_url": sub.logo_url if sub else None,
        "rne_id": sub.rne_id if sub else None,
        "address": sub.address if sub else None,
        "phone_office": sub.phone_office if sub else None,
        "bank_name": sub.bank_name if sub else None,
        "rib": sub.rib if sub else None
    } if sub else None
    clarification = analyze_tender_risks_and_clarification(t, company_name=comp_name)
    template_path = os.path.join(os.path.dirname(__file__), "templates", "print_clarification.html")
    with open(template_path, "r", encoding="utf-8") as f:
        tmpl = jinja2.Template(f.read())
    return tmpl.render(
        tender=t,
        company_name=comp_name,
        clarification=clarification,
        company_profile=profile
    )

# --- Simulateur de Notation Concurrentielle & Score Mieux-Disant (Décret 2014-1039) ---

def simulate_tender_scoring(
    t: dict,
    company_name: str = "ADVANCIA TRAINING",
    tech_weight: float = 0.70,
    fin_weight: float = 0.30,
    tech_score: float = 85.0,
    proposed_price: Optional[float] = None,
    market_estimate: Optional[float] = None
) -> dict:
    title = t.get("title_fr") or t.get("title_ar") or "Marché Public"
    buyer = t.get("buyer_name") or "L'Acheteur Public"
    bid_no = t.get("bid_no") or "N/A"

    commercial = generate_commercial_proposal(t, company_name=company_name)
    bpu_total_ht = commercial.get("total_ht", 15000.0)
    
    if not proposed_price or proposed_price <= 0:
        proposed_price = bpu_total_ht
    
    if not market_estimate or market_estimate <= 0:
        market_estimate = round(proposed_price * 1.08, 3)

    # Décret 2014-1039 Art. 56 : Seuil d'Offre Anormalement Basse (80% du budget estimé)
    oab_threshold = round(market_estimate * 0.80, 3)
    sweet_spot_min = round(market_estimate * 0.85, 3)
    sweet_spot_max = round(market_estimate * 0.94, 3)
    sweet_spot_target = round((sweet_spot_min + sweet_spot_max) / 2, 3)

    competitor_lowest = max(oab_threshold, round(market_estimate * 0.84, 3))
    
    if proposed_price <= competitor_lowest:
        financial_score = 100.0
    else:
        financial_score = round(min(100.0, (competitor_lowest / proposed_price) * 100.0), 2)

    total_w = tech_weight + fin_weight
    w_tech_norm = (tech_weight / total_w) if total_w > 0 else 0.70
    w_fin_norm = (fin_weight / total_w) if total_w > 0 else 0.30

    global_score = round((w_tech_norm * tech_score) + (w_fin_norm * financial_score), 2)

    if proposed_price < oab_threshold:
        status = "OAB_ALERT"
        status_badge = "🔴 Alerte : Risque d'Offre Anormalement Basse (Art. 56)"
        status_color = "rose"
        advice = (
            f"Attention ! Votre prix ({proposed_price:,.3f} TND) est inférieur au seuil d'alerte OAB ({oab_threshold:,.3f} TND). "
            f"La commission des marchés risque d'exiger des sous-détails de prix ou de déclarer l'offre irrecevable."
        )
    elif sweet_spot_min <= proposed_price <= sweet_spot_max:
        status = "OPTIMAL_SWEET_SPOT"
        status_badge = "🎯 Zone Optimale Mieux-Disant (Recommandé)"
        status_color = "emerald"
        advice = (
            f"Positionnement optimal. Votre offre se situe dans le corridor idéal ({sweet_spot_min:,.3f} - {sweet_spot_max:,.3f} TND), "
            f"garantissant un score combiné de {global_score}/100 avec une marge nette saine (~22%) sans risque OAB."
        )
    elif proposed_price > market_estimate:
        status = "EXPENSIVE"
        status_badge = "🟡 Risque d'Éviction sur le Prix"
        status_color = "amber"
        advice = (
            f"Votre prix ({proposed_price:,.3f} TND) dépasse l'estimation budgétaire ({market_estimate:,.3f} TND). "
            f"La note financière est pénalisée ({financial_score}/100), réduisant vos chances face à un concurrent technique équivalent."
        )
    else:
        status = "COMPETITIVE"
        status_badge = "🟢 Offre Compétitive Sécurisée"
        status_color = "teal"
        advice = (
            f"Votre positionnement ({proposed_price:,.3f} TND) est bien étalonné. Pour maximiser la note finale sans réduire vos marges, "
            f"considérez un ajustement vers le prix cible recommandé de {sweet_spot_target:,.3f} TND HT."
        )

    simulations = [
        {
            "scenario": "Agressif (Proche limite OAB)",
            "price": round(sweet_spot_min, 3),
            "fin_score": 100.0 if round(sweet_spot_min, 3) <= competitor_lowest else round((competitor_lowest / sweet_spot_min) * 100.0, 2),
            "global_score": round((w_tech_norm * tech_score) + (w_fin_norm * (100.0 if round(sweet_spot_min, 3) <= competitor_lowest else (competitor_lowest / sweet_spot_min) * 100.0)), 2),
            "margin_est": "~15%",
            "risk": "Faible (sécurisé)"
        },
        {
            "scenario": "Cible Recommandée (Sweet Spot IA)",
            "price": sweet_spot_target,
            "fin_score": round(min(100.0, (competitor_lowest / sweet_spot_target) * 100.0), 2),
            "global_score": round((w_tech_norm * tech_score) + (w_fin_norm * min(100.0, (competitor_lowest / sweet_spot_target) * 100.0)), 2),
            "margin_est": "~22%",
            "risk": "Minimal"
        },
        {
            "scenario": "Votre Proposition Actuelle",
            "price": proposed_price,
            "fin_score": financial_score,
            "global_score": global_score,
            "margin_est": "~25%",
            "risk": "Selon diagnostic"
        },
        {
            "scenario": "Conservateur (Haute Marge)",
            "price": round(market_estimate * 1.02, 3),
            "fin_score": round((competitor_lowest / (market_estimate * 1.02)) * 100.0, 2),
            "global_score": round((w_tech_norm * tech_score) + (w_fin_norm * ((competitor_lowest / (market_estimate * 1.02)) * 100.0)), 2),
            "margin_est": "~32%",
            "risk": "Perte de points sur le prix"
        }
    ]

    return {
        "tender_id": t.get("ep_bid_master_id") or t.get("id"),
        "bid_no": bid_no,
        "title": title,
        "buyer_name": buyer,
        "company_name": company_name,
        "tech_weight_pct": int(w_tech_norm * 100),
        "fin_weight_pct": int(w_fin_norm * 100),
        "tech_score": tech_score,
        "financial_score": financial_score,
        "global_score": global_score,
        "proposed_price": proposed_price,
        "market_estimate": market_estimate,
        "oab_threshold": oab_threshold,
        "sweet_spot_min": sweet_spot_min,
        "sweet_spot_max": sweet_spot_max,
        "sweet_spot_target": sweet_spot_target,
        "status": status,
        "status_badge": status_badge,
        "status_color": status_color,
        "advice": advice,
        "simulations": simulations
    }

@app.get("/api/tenders/{tender_id}/scoring-simulation")
def get_tender_scoring_simulation_api(
    tender_id: int,
    company_name: Optional[str] = "ADVANCIA TRAINING",
    tech_weight: Optional[float] = 0.70,
    fin_weight: Optional[float] = 0.30,
    tech_score: Optional[float] = 85.0,
    proposed_price: Optional[float] = None,
    market_estimate: Optional[float] = None
):
    """Simulateur de notation globale et détection d'offre anormalement basse (Décret 2014-1039)."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    return simulate_tender_scoring(
        t=t,
        company_name=company_name or "ADVANCIA TRAINING",
        tech_weight=tech_weight or 0.70,
        fin_weight=fin_weight or 0.30,
        tech_score=tech_score or 85.0,
        proposed_price=proposed_price,
        market_estimate=market_estimate
    )

# --- Pack Soumission TUNEPS Complet en ZIP 1-Clic ---

def generate_tuneps_submission_pack_zip(
    tender_id: int, 
    company_name: str = "ADVANCIA TRAINING",
    selected_files: Optional[List[str]] = None,
    format_type: str = "both",
    company_profile: Optional[Dict[str, Any]] = None
) -> bytes:
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    
    bid_no = t.get("bid_no") or f"TENDER_{tender_id}"
    buyer = t.get("buyer_name") or "L'Acheteur Public"
    title = t.get("title_fr") or t.get("title_ar") or "Marché Public"
    deadline = (t.get("deadline_date") or "")[:16]

    include_all = not selected_files or len(selected_files) == 0
    sel = set(selected_files or [])

    checklist_data = get_tender_checklist_api(tender_id, company_name=company_name)
    tech_data = generate_technical_proposal(t, company_name=company_name)
    comm_data = generate_commercial_proposal(t, company_name=company_name)
    risk_data = analyze_tender_risks_and_clarification(t, company_name=company_name)
    scoring_data = simulate_tender_scoring(t, company_name=company_name)

    import docx_generator
    import pdf_generator

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if include_all or "readme" in sel:
            readme_content = f"""================================================================================
PACK OFFICIEL DE SOUMISSION TUNEPS (DÉCRET N° 2014-1039)
================================================================================
Avis TUNEPS N° : {bid_no}
Acheteur Public : {buyer}
Objet du Marché : {title}
Date Limite de Remise des Plis : {deadline}
Entreprise Soumissionnaire : {company_name}
Date de Génération du Pack : {datetime.now().strftime('%d/%m/%Y à %H:%M')}
Plateforme : Tenders.tn (B2B SaaS Intelligence Commande Publique Tunisie)
================================================================================

STRUCTURE DE CE DOSSIER DE SOUMISSION :
--------------------------------------------------------------------------------
📁 01_Offre_Administrative/
   - 01_Acte_Engagement_{bid_no}.docx / .pdf    : Acte d'engagement solennel pré-rempli
   - 02_Checklist_Conformite_Decret.txt        : Liste de pointage des pièces administratives
   - 03_Demande_Caution_Bancaire_{bid_no}.docx / .pdf : Demande de cautionnement bancaire

📁 02_Offre_Technique/
   - 01_Memoire_Technique_Execution_{bid_no}.docx / .pdf : Mémoire technique d'exécution
   - 02_Synthese_Methodologie_Equipe.txt      : Synthèse opérationnelle

📁 03_Offre_Financiere/
   - 01_Bordereau_Prix_Unitaires_{bid_no}.docx / .pdf : BPU & DQE officiel
   - 02_Lettre_Soumission_Financiere.doc      : Déclaration financière 120 jours

📁 04_Juridique_HAICOP/
   - 01_Demande_Eclaircissement_{bid_no}.docx / .pdf : Demande d'éclaircissement HAICOP
   - 02_Rapport_Analyse_Risques.txt           : Score de vigilance juridique

📁 05_Strategie_Notation/
   - 01_Rapport_Score_Mieux_Disant.txt        : Simulation de notation globale
--------------------------------------------------------------------------------

INSTRUCTIONS CRITIQUES DE DÉPÔT SUR TUNEPS (www.tuneps.tn) :
1. Connectez votre clé de signature électronique (Token USB TunTrust / ANCE).
2. Ouvrez la session de consultation de l'avis N° {bid_no} sur TUNEPS.
3. Téléversez les documents dans leurs enveloppes respectives (Admin, Tech, Finance).
4. Pour toute question technique ou administrative, utilisez le modèle du dossier 04.

Assistance & Support Tenders.tn : support@tenders.tn | +216 28 177 888
================================================================================
"""
            z.writestr("LISEZMOI_INSTRUCTIONS_TUNEPS.txt", readme_content.encode("utf-8"))

        want_docx = format_type in ["docx", "both"]
        want_pdf = format_type in ["pdf", "both"]

        # 01 - Offre Administrative
        if include_all or "acte_engagement" in sel:
            if want_docx:
                z.writestr(
                    f"01_Offre_Administrative/01_Acte_Engagement_{bid_no}.docx",
                    docx_generator.generate_engagement_letter_docx(t, company_name, checklist_data, company_profile=company_profile)
                )
            if want_pdf:
                z.writestr(
                    f"01_Offre_Administrative/01_Acte_Engagement_{bid_no}.pdf",
                    pdf_generator.generate_engagement_letter_pdf(t, company_name, checklist_data, company_profile=company_profile)
                )
        
        if include_all or "checklist_admin" in sel:
            admin_check_text = f"CHECKLIST DES PIÈCES ADMINISTRATIVES (DÉCRET N° 2014-1039)\nMarché N° : {bid_no}\nEntreprise : {company_name}\n\n"
            admin_check_text += "PIÈCES ADMINISTRATIVES OBLIGATOIRES :\n"
            for idx, item in enumerate(checklist_data.get("admin_checklist", []), 1):
                admin_check_text += f"[ ] {idx}. {item['title']}\n    Description : {item['desc']}\n    Obligatoire : {'OUI' if item.get('mandatory') else 'OPTIONNEL'}\n\n"
            admin_check_text += "PIÈCES TECHNIQUES REQUISES :\n"
            for idx, item in enumerate(checklist_data.get("technical_checklist", []), 1):
                admin_check_text += f"[ ] {idx}. {item['title']}\n    Description : {item['desc']}\n\n"
            z.writestr("01_Offre_Administrative/02_Checklist_Conformite_Decret.txt", admin_check_text.encode("utf-8"))

        if include_all or "caution_bancaire" in sel:
            if want_docx:
                z.writestr(
                    f"01_Offre_Administrative/03_Demande_Caution_Bancaire_{bid_no}.docx",
                    docx_generator.generate_bank_guarantee_docx(t, company_name, company_profile=company_profile)
                )
            if want_pdf:
                z.writestr(
                    f"01_Offre_Administrative/03_Demande_Caution_Bancaire_{bid_no}.pdf",
                    pdf_generator.generate_bank_guarantee_pdf(t, company_name, company_profile=company_profile)
                )

        # 02 - Offre Technique
        if include_all or "memoire_technique" in sel:
            if want_docx:
                z.writestr(
                    f"02_Offre_Technique/01_Memoire_Technique_Execution_{bid_no}.docx",
                    docx_generator.generate_technical_proposal_docx(t, company_name, tech_data, company_profile=company_profile)
                )
            if want_pdf:
                z.writestr(
                    f"02_Offre_Technique/01_Memoire_Technique_Execution_{bid_no}.pdf",
                    pdf_generator.generate_technical_proposal_pdf(t, company_name, tech_data, company_profile=company_profile)
                )
        
        if include_all or "synthese_technique" in sel:
            tech_summary = f"""SYNTHÈSE DE L'OFFRE TECHNIQUE & MÉTHODOLOGIE D'EXÉCUTION
Marché : {title} (Avis TUNEPS {bid_no})
Entreprise Soumissionnaire : {company_name}
Acheteur Public : {buyer}

1. ENGAGEMENT MÉTHODOLOGIQUE :
Notre proposition repose sur les standards de conformité au CCTP
garantissant le respect strict des délais contractuels.

2. STRUCTURE DES LIVRABLES :
"""
            for s in tech_data.get("sections", []):
                tech_summary += f"\n- {s.get('title')}\n  Points saillants :\n"
                for h in s.get("highlights", []):
                    tech_summary += f"    * {h}\n"
            z.writestr("02_Offre_Technique/02_Synthese_Methodologie_Equipe.txt", tech_summary.encode("utf-8"))

        # 03 - Offre Financière
        if include_all or "bpu_financier" in sel:
            if want_docx:
                z.writestr(
                    f"03_Offre_Financiere/01_Bordereau_Prix_Unitaires_BPU_{bid_no}.docx",
                    docx_generator.generate_commercial_bpu_docx(t, company_name, comm_data, company_profile=company_profile)
                )
            if want_pdf:
                z.writestr(
                    f"03_Offre_Financiere/01_Bordereau_Prix_Unitaires_BPU_{bid_no}.pdf",
                    pdf_generator.generate_commercial_bpu_pdf(t, company_name, comm_data, company_profile=company_profile)
                )
        
        if include_all or "lettre_financiere" in sel:
            fin_letter = f"""RÉPUBLIQUE TUNISIENNE
LETTRE DE SOUMISSION FINANCIÈRE OFFICIELLE (DÉCRET N° 2014-1039)

À l'attention de : Monsieur le Président de la Commission des Marchés
Acheteur Public : {buyer}
Avis TUNEPS N° : {bid_no}
Objet du Marché : {title}

Je soussigné, représentant légal de la société {company_name}, confirme par la présente :
1. Avoir examiné dans son intégralité le Cahier des Charges et en accepter sans réserve toutes les clauses financières.
2. Soumissionner pour l'exécution des prestations aux prix unitaires indiqués au Bordereau des Prix Unitaires ci-joint.
3. Montant total hors taxes (HT) : {comm_data.get('total_ht', 0):,.3f} TND
4. Montant de la TVA (19%) : {comm_data.get('tva_amount', 0):,.3f} TND
5. Montant total toutes taxes comprises (TTC) : {comm_data.get('total_ttc', 0):,.3f} TND
   (Soit en toutes lettres : {comm_data.get('total_ttc_words', '')})

Fait à Tunis, le {datetime.now().strftime('%d/%m/%Y')}
Pour {company_name}
Direction Générale
"""
            z.writestr(f"03_Offre_Financiere/02_Lettre_Soumission_Financiere_{bid_no}.doc", fin_letter.encode("utf-8"))

        # 04 - Juridique HAICOP
        if include_all or "clarification_haicop" in sel:
            if want_docx:
                z.writestr(
                    f"04_Juridique_HAICOP/01_Demande_Eclaircissement_HAICOP_{bid_no}.docx",
                    docx_generator.generate_clarification_docx(t, company_name, risk_data, company_profile=company_profile)
                )
            if want_pdf:
                z.writestr(
                    f"04_Juridique_HAICOP/01_Demande_Eclaircissement_HAICOP_{bid_no}.pdf",
                    pdf_generator.generate_clarification_pdf(t, company_name, risk_data, company_profile=company_profile)
                )
        
        if include_all or "rapport_risques" in sel:
            risk_summary = f"""RAPPORT D'AUDIT DES RISQUES JURIDIQUES & DE REJET (DÉCRET N° 2014-1039)
Avis TUNEPS : {bid_no}
Score Global de Risque : {risk_data.get('score')}/100 ({risk_data.get('global_badge')})
Entreprise : {company_name}

POINTS DE VIGILANCE IDENTIFIÉS :
"""
            for rf in risk_data.get("risk_factors", []):
                risk_summary += f"\n[{rf.get('badge')}] {rf.get('title')}\n  Détail : {rf.get('desc')}\n"
            z.writestr("04_Juridique_HAICOP/02_Rapport_Analyse_Risques.txt", risk_summary.encode("utf-8"))

        # 05 - Stratégie de Notation
        if include_all or "score_mieux_disant" in sel:
            strat_summary = f"""SIMULATION STRATÉGIQUE DE NOTATION & SCORE MIEUX-DISANT
Marché N° : {bid_no}
Pondération réglementaire : {scoring_data.get('tech_weight_pct')}% Technique / {scoring_data.get('fin_weight_pct')}% Financier

RÉSULTATS DE LA SIMULATION :
- Note Technique Estimée : {scoring_data.get('tech_score')}/100
- Note Financière Calculée : {scoring_data.get('financial_score')}/100
- NOTE GLOBALE COMBINÉE : {scoring_data.get('global_score')}/100
- Diagnostic : {scoring_data.get('status_badge')}

ANALYSE DES PRIX (TND HT) :
- Seuil d'Alerte Offre Anormalement Basse (Art. 56) : {scoring_data.get('oab_threshold'):,.3f} TND
- Corridor Optimal Mieux-Disant (Sweet Spot) : {scoring_data.get('sweet_spot_min'):,.3f} TND à {scoring_data.get('sweet_spot_max'):,.3f} TND
- Prix Cible Recommandé par l'IA : {scoring_data.get('sweet_spot_target'):,.3f} TND
- Votre Prix Proposé : {scoring_data.get('proposed_price'):,.3f} TND

CONSEIL STRATÉGIQUE :
{scoring_data.get('advice')}
"""
            z.writestr("05_Strategie_Notation/01_Rapport_Score_Mieux_Disant.txt", strat_summary.encode("utf-8"))

    buf.seek(0)
    return buf.getvalue()

@app.get("/api/tenders/{tender_id}/submission-pack.zip")
def download_submission_pack_zip_api(
    tender_id: int, 
    company_name: Optional[str] = None,
    files: Optional[str] = None,
    format: Optional[str] = "both",
    sub_id: Optional[int] = None,
    phone: Optional[str] = None
):
    """Génère et télécharge le Pack Complet ou Personnalisé de Soumission TUNEPS en archive .zip."""
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    bid_no = t.get("bid_no") or f"TENDER_{tender_id}"
    
    # Résolution de l'abonné pour le branding et les quotas
    sub = None
    if sub_id:
        sub = db.get_subscriber_by_id(sub_id)
    elif phone:
        sub = db.get_subscriber_by_phone(phone)
    if not sub:
        subs = db.get_active_subscribers() or db.get_all_subscribers_admin()
        if subs: sub = subs[0]

    # Contrôle & incrémentation des quotas SaaS
    if sub:
        quota_check = db.check_and_record_usage(sub.id)
        if not quota_check.get("allowed", True):
            raise HTTPException(
                status_code=403,
                detail=f"Quota mensuel atteint ({quota_check['used']}/{quota_check['quota']} packs). Passez au forfait supérieur !"
            )

    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {
        "logo_url": sub.logo_url if sub else None,
        "rne_id": sub.rne_id if sub else None,
        "address": sub.address if sub else None,
        "bank_name": sub.bank_name if sub else None,
        "rib": sub.rib if sub else None
    } if sub else None

    selected_files = [f.strip() for f in files.split(",") if f.strip()] if files else None
    fmt = format.lower() if format in ["docx", "pdf", "both"] else "both"
    zip_bytes = generate_tuneps_submission_pack_zip(
        tender_id,
        company_name=comp_name,
        selected_files=selected_files,
        format_type=fmt,
        company_profile=profile
    )
    
    # Enregistrement dans l'historique "Mes Dossiers"
    if sub:
        comm = generate_commercial_proposal(t, company_name=comp_name)
        db.record_submission_dossier(
            subscriber_id=sub.id,
            tender_id=tender_id,
            files_included=selected_files or ["pack_complet"],
            format_type=fmt.upper(),
            total_price=comm.get("total_ttc", 0.0),
            status="PREPARATION",
            notes=f"Pack généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )

    filename = f"Pack_TUNEPS_{bid_no}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )

# --- Téléchargements Individuels Word (.docx) ---

@app.get("/api/tenders/{tender_id}/proposal.docx")
def download_technical_proposal_docx_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    tech_data = generate_technical_proposal(t, company_name=comp_name)
    import docx_generator
    docx_bytes = docx_generator.generate_technical_proposal_docx(t, comp_name, tech_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="Memoire_Technique_{bid_no}.docx"'})

@app.get("/api/tenders/{tender_id}/engagement.docx")
def download_engagement_docx_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    checklist_data = get_tender_checklist_api(tender_id, company_name=comp_name)
    import docx_generator
    docx_bytes = docx_generator.generate_engagement_letter_docx(t, comp_name, checklist_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="Acte_Engagement_{bid_no}.docx"'})

@app.get("/api/tenders/{tender_id}/commercial.docx")
def download_commercial_bpu_docx_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    comm_data = generate_commercial_proposal(t, company_name=comp_name)
    import docx_generator
    docx_bytes = docx_generator.generate_commercial_bpu_docx(t, comp_name, comm_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="Offre_Financiere_BPU_{bid_no}.docx"'})

@app.get("/api/tenders/{tender_id}/clarification.docx")
def download_clarification_docx_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    risk_data = analyze_tender_risks_and_clarification(t, company_name=comp_name)
    import docx_generator
    docx_bytes = docx_generator.generate_clarification_docx(t, comp_name, risk_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="Demande_Eclaircissement_{bid_no}.docx"'})

@app.get("/api/tenders/{tender_id}/bank-guarantee.docx")
def download_bank_guarantee_docx_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    import docx_generator
    docx_bytes = docx_generator.generate_bank_guarantee_docx(t, comp_name, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="Demande_Caution_Bancaire_{bid_no}.docx"'})

# --- Téléchargements Individuels PDF Directs Prêts-à-Signer ---

@app.get("/api/tenders/{tender_id}/proposal.pdf")
def download_technical_proposal_pdf_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    tech_data = generate_technical_proposal(t, company_name=comp_name)
    import pdf_generator
    pdf_bytes = pdf_generator.generate_technical_proposal_pdf(t, comp_name, tech_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Memoire_Technique_{bid_no}.pdf"'})

@app.get("/api/tenders/{tender_id}/engagement.pdf")
def download_engagement_pdf_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    checklist_data = get_tender_checklist_api(tender_id, company_name=comp_name)
    import pdf_generator
    pdf_bytes = pdf_generator.generate_engagement_letter_pdf(t, comp_name, checklist_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Acte_Engagement_{bid_no}.pdf"'})

@app.get("/api/tenders/{tender_id}/bank-guarantee.pdf")
def download_bank_guarantee_pdf_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    import pdf_generator
    pdf_bytes = pdf_generator.generate_bank_guarantee_pdf(t, comp_name, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Demande_Caution_{bid_no}.pdf"'})

@app.get("/api/tenders/{tender_id}/commercial.pdf")
def download_commercial_pdf_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    comm_data = generate_commercial_proposal(t, company_name=comp_name)
    import pdf_generator
    pdf_bytes = pdf_generator.generate_commercial_bpu_pdf(t, comp_name, comm_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Bordereau_Prix_{bid_no}.pdf"'})

@app.get("/api/tenders/{tender_id}/clarification.pdf")
def download_clarification_pdf_api(tender_id: int, company_name: Optional[str] = None, sub_id: Optional[int] = None):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    comp_name = (sub and sub.company_name) or company_name or "ADVANCIA TRAINING"
    profile = {"logo_url": sub.logo_url, "rne_id": sub.rne_id, "address": sub.address, "bank_name": sub.bank_name, "rib": sub.rib} if sub else None
    risk_data = analyze_tender_risks_and_clarification(t, company_name=comp_name)
    import pdf_generator
    pdf_bytes = pdf_generator.generate_clarification_pdf(t, comp_name, risk_data, company_profile=profile)
    bid_no = t.get("bid_no") or tender_id
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Demande_Eclaircissement_{bid_no}.pdf"'})

# --- Calendrier & Rappels Intelligents (RFC 5545 iCal, Google, Outlook) ---

@app.get("/api/tenders/{tender_id}/calendar.ics")
def download_tender_calendar_ics(tender_id: int):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    import calendar_helper
    ics_text = calendar_helper.generate_ics(t)
    bid_no = t.get("bid_no") or f"tender_{tender_id}"
    return Response(
        content=ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="Rappel_TUNEPS_{bid_no}.ics"'}
    )

@app.get("/api/tenders/{tender_id}/calendar-links")
def get_tender_calendar_links(tender_id: int):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    import calendar_helper
    links = calendar_helper.get_calendar_web_links(t)
    links["bid_no"] = t.get("bid_no")
    links["deadline"] = t.get("deadline_date")
    return links

# --- Intelligence Acheteur & Marchés Récurrents ---

@app.get("/api/tenders/{tender_id}/buyer-analytics")
def get_tender_buyer_analytics_api(tender_id: int):
    t = db.get_tender_by_id(tender_id)
    if not t: raise HTTPException(status_code=404, detail="Marché introuvable.")
    buyer = t.get("buyer_name") or ""
    return db.get_buyer_stats(buyer)

# --- Dossiers Historiques ("Mes Dossiers") ---

@app.get("/api/client/dossiers/{sub_id}")
def get_client_dossiers_api(sub_id: int):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    dossiers = db.get_subscriber_dossiers(sub.id)
    return {"total": len(dossiers), "dossiers": dossiers, "subscriber_id": sub.id}

class DossierStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
    sub_id: Optional[int] = None

@app.post("/api/client/dossiers/{dossier_id}/status")
def update_client_dossier_status_api(dossier_id: int, req: DossierStatusUpdate, sub_id: Optional[int] = None):
    effective_sub = sub_id or req.sub_id
    if not effective_sub:
        with db._get_connection() as conn:
            row = conn.execute("SELECT subscriber_id FROM submission_dossiers WHERE id = ?", (dossier_id,)).fetchone()
            if row:
                effective_sub = row[0]
    updated = db.update_dossier_status(dossier_id, effective_sub or 0, req.status, req.notes)
    return {"status": "SUCCESS" if updated else "FAILED"}

# --- Identité & Branding Client (Logo, RNE, Coordonnées) ---

class BrandingUpdateRequest(BaseModel):
    subscriber_id: int
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    rne_id: Optional[str] = None
    address: Optional[str] = None
    phone_office: Optional[str] = None
    bank_name: Optional[str] = None
    rib: Optional[str] = None

@app.get("/api/client/branding/{sub_id}")
def get_client_branding_api(sub_id: int):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        subs = db.get_active_subscribers() or db.get_all_subscribers_admin()
        sub = subs[0] if subs else None
        if not sub: raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    return {
        "subscriber_id": sub.id,
        "company_name": sub.company_name,
        "logo_url": sub.logo_url,
        "rne_id": sub.rne_id,
        "address": sub.address,
        "phone_office": sub.phone_office,
        "bank_name": sub.bank_name,
        "rib": sub.rib,
        "plan": sub.plan,
        "monthly_pack_quota": sub.monthly_pack_quota
    }

@app.post("/api/client/branding")
def update_client_branding_api(req: BrandingUpdateRequest):
    sub = db.get_subscriber_by_id(req.subscriber_id)
    if not sub: raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    success = db.update_company_branding(
        sub_id=req.subscriber_id,
        company_name=req.company_name,
        logo_url=req.logo_url,
        rne_id=req.rne_id,
        address=req.address,
        phone_office=req.phone_office,
        bank_name=req.bank_name,
        rib=req.rib
    )
    return {"status": "SUCCESS" if success else "FAILED"}

# --- Quotas & Passerelles de Paiement Tunisiennes (Flouci & Konnect) ---

@app.get("/api/client/quota/{sub_id}")
def get_client_quota_api(sub_id: int):
    return db.get_subscriber_usage(sub_id)

@app.get("/api/payments/plans")
def get_payment_plans_api():
    from payment_gateway import payment_gateway
    return payment_gateway.get_available_plans()

class PaymentInitRequest(BaseModel):
    subscriber_id: int
    plan: str
    gateway: Optional[str] = "FLOUCI"

@app.post("/api/payments/initiate")
def initiate_payment_checkout_api(req: PaymentInitRequest):
    sub = db.get_subscriber_by_id(req.subscriber_id)
    if not sub: raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    from payment_gateway import payment_gateway
    res = payment_gateway.initiate_payment(
        subscriber_id=req.subscriber_id,
        plan_code=req.plan,
        gateway=req.gateway or "FLOUCI",
        client_phone=sub.phone
    )
    if res.get("success"):
        db.record_payment_transaction(
            subscriber_id=req.subscriber_id,
            gateway=res.get("gateway", "FLOUCI"),
            amount_tnd=res.get("amount_tnd", 0.0),
            plan=req.plan.upper(),
            payment_ref=res.get("payment_ref", ""),
            status="PENDING"
        )
    return res

@app.get("/api/payments/mock-checkout", response_class=HTMLResponse)
def render_mock_checkout(ref: str, plan: str, amount: float):
    """Page de simulation de paiement tunisien (Flouci / Konnect sandbox)."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Passerelle de Paiement Sécurisée - Tenders.tn</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-900 text-slate-100 flex items-center justify-center min-h-screen p-4">
    <div class="bg-slate-800 border border-slate-700 max-w-md w-full rounded-2xl p-6 shadow-2xl">
        <div class="flex items-center justify-between pb-4 border-b border-slate-700">
            <div class="flex items-center space-x-2">
                <span class="text-xl">🇹🇳</span>
                <span class="font-bold text-lg text-emerald-400">Paiement Sécurisé Tunisie</span>
            </div>
            <span class="px-2 py-0.5 text-xs bg-emerald-500/20 text-emerald-300 rounded font-semibold">Sandbox Test</span>
        </div>
        <div class="my-6 space-y-3">
            <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-700/50">
                <p class="text-xs text-slate-400">Abonnement Tenders.tn</p>
                <p class="text-xl font-bold text-white mt-1">Forfait {plan}</p>
                <div class="flex justify-between items-baseline mt-2">
                    <span class="text-xs text-slate-400">Référence : {ref}</span>
                    <span class="text-2xl font-black text-emerald-400">{amount:,.3f} <span class="text-sm font-bold">TND</span></span>
                </div>
            </div>
            <div class="space-y-2">
                <label class="text-xs text-slate-400 font-semibold uppercase tracking-wider">Moyen de règlement simulé</label>
                <div class="grid grid-cols-2 gap-2 text-xs">
                    <div class="p-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 flex items-center space-x-2">
                        <i class="fa-solid fa-mobile-screen-button text-emerald-400"></i>
                        <span>Flouci App Pay</span>
                    </div>
                    <div class="p-3 rounded-lg border border-slate-700 bg-slate-800 flex items-center space-x-2">
                        <i class="fa-regular fa-credit-card text-blue-400"></i>
                        <span>Carte Bancaire GPG</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="space-y-3">
            <button onclick="confirmPayment()" id="btn-pay" class="w-full py-3.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-lg shadow-emerald-900/30 transition flex items-center justify-center space-x-2">
                <i class="fa-solid fa-lock"></i>
                <span>Confirmer le Paiement ({amount:,.3f} TND)</span>
            </button>
            <a href="/dashboard" class="block text-center text-xs text-slate-400 hover:text-slate-200">Annuler et retourner au tableau de bord</a>
        </div>
    </div>
    <script>
    async function confirmPayment() {{
        const btn = document.getElementById('btn-pay');
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Traitement en cours...';
        btn.disabled = true;
        try {{
            const res = await fetch('/api/payments/mock-confirm', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ payment_ref: '{ref}' }})
            }});
            const data = await res.json();
            if (data.status === 'SUCCESS') {{
                window.location.href = '/dashboard?payment=success&plan={plan}';
            }} else {{
                alert('Erreur de confirmation');
                btn.disabled = false;
            }}
        }} catch(e) {{
            alert('Erreur réseau');
            btn.disabled = false;
        }}
    }}
    </script>
</body>
</html>"""

class MockConfirmRequest(BaseModel):
    payment_ref: Optional[str] = None
    subscriber_id: Optional[int] = None
    plan_code: Optional[str] = None

@app.post("/api/payments/mock-confirm")
def mock_confirm_payment_api(req: MockConfirmRequest):
    if os.getenv("ENVIRONMENT") == "production":
        raise HTTPException(status_code=403, detail="Endpoint de test désactivé en production.")
    if req.payment_ref:
        success = db.activate_plan_from_payment(req.payment_ref, status="SUCCESS")
        return {"status": "SUCCESS" if success else "FAILED"}
    elif req.subscriber_id and req.plan_code:
        quota_map = {"STARTER": 10, "PRO": 25, "ENTERPRISE": 100}
        quota = quota_map.get(req.plan_code.upper(), 25)
        # Record successful transaction
        db.record_payment_transaction(
            subscriber_id=req.subscriber_id,
            gateway="FLOUCI_DIRECT",
            amount_tnd=49.0 if req.plan_code == "STARTER" else (129.0 if req.plan_code == "PRO" else 299.0),
            plan=req.plan_code.upper(),
            payment_ref=f"DIRECT_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            status="SUCCESS"
        )
        # Update subscriber plan and quota
        with db._get_connection() as conn:
            conn.execute(
                "UPDATE subscribers SET plan = ?, monthly_pack_quota = ? WHERE id = ?",
                (req.plan_code.upper(), quota, req.subscriber_id)
            )
            conn.commit()
        return {"status": "SUCCESS", "plan": req.plan_code.upper(), "quota": quota}
    return {"status": "FAILED", "detail": "Missing payment_ref or subscriber_id"}

# --- Feature 3 : Version Imprimable & Export PDF Corporate ---

@app.get("/tender/{tender_id}/print", response_class=HTMLResponse)
def render_tender_printable(tender_id: int, sub_id: Optional[int] = None):
    """Génère la version imprimable et exportable en PDF du marché public."""
    import jinja2
    t = db.get_tender_by_id(tender_id)
    if not t:
        raise HTTPException(status_code=404, detail="Marché introuvable.")
    sub = db.get_subscriber_by_id(sub_id) if sub_id else (db.get_active_subscribers() or [None])[0]
    profile = {
        "subscriber_id": sub.id if sub else None,
        "company_name": sub.company_name if sub else None,
        "logo_url": sub.logo_url if sub else None,
        "rne_id": sub.rne_id if sub else None,
        "address": sub.address if sub else None,
        "bank_name": sub.bank_name if sub else None,
        "rib": sub.rib if sub else None
    } if sub else None
    template_path = os.path.join(os.path.dirname(__file__), "templates", "print_tender.html")
    with open(template_path, "r", encoding="utf-8") as f:
        tmpl = jinja2.Template(f.read())
    return tmpl.render(tender=t, company_profile=profile)

# --- Feature 4 : Backoffice Fondateur CRM & Briefing Matinal ---

@app.get("/admin", response_class=HTMLResponse)
def render_admin_dashboard():
    """Sert l'interface du Backoffice Administrateur Fondateur."""
    content = _find_html_content("admin.html")
    if content:
        return content
    return "<h1>Backoffice administrateur... (admin.html introuvable)</h1>"

@app.get("/api/admin/metrics")
def get_admin_metrics():
    return db.get_admin_dashboard_metrics()

@app.get("/api/admin/subscribers")
def get_admin_subscribers():
    return db.get_all_subscribers_admin()

class SubscriberFeaturesRequest(BaseModel):
    features: Dict[str, bool]

@app.get("/api/admin/subscriber/{sub_id}/features")
def get_subscriber_features_admin(sub_id: int):
    """Retourne la configuration des fonctionnalités actives pour un abonné."""
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    return {
        "subscriber_id": sub.id,
        "company_name": sub.company_name,
        "features": sub.features or {}
    }

@app.post("/api/admin/subscriber/{sub_id}/features")
def update_subscriber_features_admin(sub_id: int, req: SubscriberFeaturesRequest):
    """Met à jour les fonctionnalités activées/désactivées pour un abonné."""
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    success = db.update_subscriber_features(sub_id, req.features)
    updated_sub = db.get_subscriber_by_id(sub_id)
    return {
        "status": "SUCCESS" if success else "FAILED",
        "subscriber_id": sub_id,
        "features": updated_sub.features or {}
    }

@app.post("/api/admin/subscriber/toggle/{sub_id}")
def toggle_admin_subscriber(sub_id: int):
    success = db.toggle_subscriber_status(sub_id)
    return {"status": "SUCCESS" if success else "NOT_FOUND"}

@app.delete("/api/admin/subscriber/{sub_id}")
def delete_subscriber_admin(sub_id: int):
    """Supprime définitivement un compte abonné depuis le CRM fondateur."""
    success = db.delete_subscriber(sub_id)
    return {"status": "SUCCESS" if success else "NOT_FOUND"}

@app.post("/api/admin/subscriber/remind/{sub_id}")
def remind_subscriber_trial_whatsapp(sub_id: int):
    sub = db.get_subscriber_by_id(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Abonné non trouvé.")
    from whatsapp_gateway import send_whatsapp_message
    msg = (
        f"👋 *Bonjour {sub.company_name},*\n\n"
        f"Votre période d'essai gratuit sur *Tenders.tn* arrive bientôt à expiration.\n"
        f"Pour continuer à recevoir en temps réel vos alertes ciblées TUNEPS et conserver votre classeur de candidatures :\n\n"
        f"👉 *Prolonger mon abonnement en 1 clic :*\n"
        f"{BASE_URL}/#tarifs\n\n"
        f"_L'équipe Tenders.tn reste à votre disposition 24/7._"
    )
    success = send_whatsapp_message(sub.phone, msg)
    return {"status": "SENT" if success else "FAILED", "phone": sub.phone}

@app.post("/api/admin/dispatch-morning-briefing")
def dispatch_morning_briefing_admin():
    """Déclenche le briefing matinal WhatsApp pour tous les abonnés."""
    stats = notifier.send_morning_briefing()
    return stats

@app.post("/api/client/morning-briefing/{sub_id}")
def dispatch_single_client_briefing(sub_id: int):
    """Déclenche le briefing matinal WhatsApp pour un abonné précis."""
    stats = notifier.send_morning_briefing(subscriber_id=sub_id)
    return {"status": "SENT" if stats["briefings_sent"] > 0 else "NO_ITEMS", "stats": stats}

@app.post("/api/admin/dispatch-weekly-briefing")
def dispatch_weekly_briefing_admin():
    """Déclenche le briefing hebdomadaire WhatsApp pour tous les abonnés actifs."""
    stats = notifier.send_weekly_briefing()
    return stats

@app.post("/api/client/weekly-briefing/{sub_id}")
def dispatch_single_client_weekly_briefing(sub_id: int):
    """Déclenche le briefing hebdomadaire WhatsApp pour un abonné précis."""
    stats = notifier.send_weekly_briefing(subscriber_id=sub_id)
    return stats

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
