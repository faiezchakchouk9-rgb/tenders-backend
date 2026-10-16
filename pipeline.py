"""
Pipeline Global 100% Automatisé :
1. Collecte incrémentale TUNEPS (REST API)
2. Enrichissement & Qualification sémantique par IA (Secteurs, Gouvernorats, Synthèse)
3. Matching & Dispatch des alertes ciblées aux clients (WhatsApp / Email)

Ce script est autonome et peut tourner en boucle infinie ou via cron / Task Scheduler.
"""
import sys
import time
import logging
from collector import TunepsCollector
from enricher import TenderEnricher
from notifier import TenderNotifier, seed_demo_subscribers
from database import TenderDatabase

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("Pipeline")

def run_full_cycle(max_items: int = 50):
    logger.info("=== [PIPELINE AUTO] Démarrage du cycle complet ===")
    start_time = time.time()
    
    db = TenderDatabase()
    # seed_demo_subscribers(db)  # Désactivé pour préserver la liste réelle des abonnés
    
    collector = TunepsCollector(db=db)
    enricher = TenderEnricher(db=db)
    notifier = TenderNotifier(db=db)
    
    # 1. Collecte
    sync_stats = collector.sync_latest(max_items=max_items)
    
    # 2. Enrichissement IA
    enriched_count = enricher.process_all_pending(limit=max_items)
    
    # 3. Matching & Dispatch
    dispatch_stats = notifier.dispatch_alerts(limit=max_items)

    # 4. Traitement des requêtes interactives entrantes (WhatsApp & Telegram)
    try:
        from bot_responder import BotResponder
        bot = BotResponder(db=db)
        bot.poll_green_api_once()
        bot.poll_telegram_once()
    except Exception as e:
        logger.debug(f"Bot responder polling note: {e}")
    
    duration = round(time.time() - start_time, 2)
    stats = db.get_stats()
    
    # 5. Synchronisation automatique Cloud Firestore
    try:
        from firebase_sync import init_firestore, sync_tenders_to_firestore, sync_subscribers_to_firestore
        fs_client = init_firestore()
        if fs_client:
            sync_tenders_to_firestore(fs_client)
            sync_subscribers_to_firestore(fs_client)
    except Exception as e:
        logger.warning(f"Note synchronisation Firestore: {e}")

    print("\n" + "="*55)
    print(f"  BILAN DU CYCLE EXÉCUTÉ EN {duration}s :")
    print(f"  - Nouveaux avis récupérés        : {sync_stats['new_inserted']}")
    print(f"  - Avis qualifiés par IA          : {enriched_count}")
    print(f"  - Alertes transmises aux clients : {dispatch_stats['notifications_sent']}")
    print(f"  - Total historique en base       : {stats['total_tenders']}")
    print(f"  - Nombre de PME abonnées actives : {stats['active_subscribers']}")
    print(f"  - Cloud Firestore                : Synchronisé en direct ☁️")
    print("="*55 + "\n")

if __name__ == "__main__":
    run_full_cycle(max_items=30)
