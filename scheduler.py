"""
Service d'automatisation continue (Background Daemon).
Exécute le pipeline complet TUNEPS -> IA -> Telegram à intervalles réguliers (ex: toutes les 30 minutes).
Gère la résilience réseau, les reconnexions et le journal d'activité.
"""
import sys
import time
import logging
from datetime import datetime
from pipeline import run_full_cycle

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scheduler.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("TendersScheduler")

# Intervalle de vérification en secondes (30 minutes par défaut)
INTERVAL_SECONDS = 30 * 60

def start_daemon(interval: int = INTERVAL_SECONDS):
    logger.info("=======================================================")
    logger.info("  DEMARRAGE DU SERVICE AUTOMATIQUE TENDERS.TN 🇹🇳")
    logger.info(f"  Surveillance TUNEPS programmée toutes les {interval // 60} minutes.")
    logger.info("=======================================================")

    cycle_count = 1
    while True:
        logger.info(f"\n--- [CYCLE #{cycle_count}] Déclenchement automatique : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        try:
            run_full_cycle(max_items=30)
            logger.info(f"Cycle #{cycle_count} terminé avec succès.")
        except Exception as e:
            logger.error(f"Erreur lors du cycle #{cycle_count}: {e}", exc_info=True)

        cycle_count += 1
        logger.info(f"Mise en veille... Prochain contrôle dans {interval // 60} minutes.")
        time.sleep(interval)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daemon d'automatisation Tenders.tn")
    parser.add_argument("--interval", type=int, default=30, help="Intervalle en minutes (défaut: 30)")
    args = parser.parse_args()

    start_daemon(interval=args.interval * 60)
