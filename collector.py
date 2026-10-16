"""
Module de collecte automatisé des Appels d'Offres Tunisiens (TUNEPS-3).
Interroge directement l'API REST de TUNEPS en mode incrémental haute performance.
Capacités avancées :
- Filtrage côté serveur TUNEPS des marchés en cours (bdRecvEndDt >= now)
- Ingestion approfondie des métadonnées (Moins disant, cautionnement, CDC, ouverture des plis, lieu officiel)
- Recherche directe par mots-clés ou acheteur avec l'opérateur 'like'
"""
import requests
import urllib3
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from database import TenderDatabase, TenderNotice

# Désactiver les avertissements SSL liés aux certificats intermédiaires tunisiens (TunTrust / ANCE)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("TunepsCollector")

class TunepsCollector:
    API_URL = "https://www.tuneps.tn/api2/portail/bid/master/data"
    DETAIL_API_URL = "https://www.tuneps.tn/api2/portail/bid/master"
    BASE_DETAIL_URL = "https://www.tuneps.tn/portail/offres/details"
    
    DEFAULT_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Origin": "https://www.tuneps.tn",
        "Referer": "https://www.tuneps.tn/portail/offres"
    }

    def __init__(self, db: TenderDatabase = None):
        self.db = db or TenderDatabase()

    def fetch_tender_details(self, master_id: int) -> Dict[str, Any]:
        """
        Interroge l'endpoint de détail TUNEPS pour extraire les conditions clés du marché.
        """
        url = f"{self.DETAIL_API_URL}/{master_id}"
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, verify=False, timeout=12)
            if resp.status_code == 200:
                payload = resp.json().get("payload", {})
                
                # Formatage du prix du CDC
                doc_price_raw = payload.get("biddingDocPrice", 0)
                curr = payload.get("biddingDocPriceCurr", "TND")
                doc_price_str = "Gratuit (0 TND)" if (doc_price_raw == 0 or doc_price_raw is None) else f"{doc_price_raw} {curr}"

                return {
                    "eval_method": payload.get("evalMethodStrFr") or payload.get("evalMethodStrAr") or "Non spécifié",
                    "guarantee_type": payload.get("guaranteeTypeStrFr") or payload.get("guaranteeTypeStrAr") or "Non requis",
                    "doc_price": doc_price_str,
                    "execution_place": payload.get("executionPlaceStrFr") or payload.get("executionPlaceStrAr") or "National",
                    "opening_date": payload.get("bdOpenDt"),
                    "is_online": payload.get("onOffTypeStrFr") or "En ligne"
                }
        except Exception as e:
            logger.warning(f"Impossible d'extraire les détails pour l'avis #{master_id}: {e}")
        
        return {
            "eval_method": None,
            "guarantee_type": None,
            "doc_price": None,
            "execution_place": None,
            "opening_date": None,
            "is_online": None
        }

    def fetch_page(
        self,
        limit: int = 20,
        offset: int = 0,
        only_open: bool = True,
        keyword: Optional[str] = None,
        buyer: Optional[str] = None
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Récupère une page d'avis d'appels d'offres avec filtres côté serveur TUNEPS.
        """
        data_search = [
            {
                "key": "publicYn",
                "value": "Y",
                "specificSearch": "="
            }
        ]

        # Filtre marché en cours (non clôturé)
        if only_open:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_search.append({
                "key": "bdRecvEndDt",
                "value": now_str,
                "specificSearch": ">="
            })

        # Filtre mot-clé dans l'objet
        if keyword:
            data_search.append({
                "key": "bidNmFr",
                "value": f"%{keyword}%",
                "specificSearch": "like"
            })

        # Filtre nom de l'acheteur public
        if buyer:
            data_search.append({
                "key": "bidInstNm",
                "value": f"%{buyer}%",
                "specificSearch": "like"
            })

        payload = {
            "pagination": {
                "limit": limit,
                "offSet": offset
            },
            "sort": {
                "nameCol": "publicDt",
                "direction": "desc nulls last"
            },
            "listSort": [],
            "dataSearch": data_search,
            "listCol": []
        }

        try:
            resp = requests.post(
                self.API_URL,
                json=payload,
                headers=self.DEFAULT_HEADERS,
                verify=False,
                timeout=20
            )
            resp.raise_for_status()
            data = resp.json()
            payload_data = data.get("payload", {})
            total = payload_data.get("total", 0)
            items = payload_data.get("data", [])
            return total, items
        except Exception as e:
            logger.error(f"Erreur lors de la requête TUNEPS: {e}")
            return 0, []

    def sync_latest(self, max_items: int = 50, only_open: bool = True) -> Dict[str, int]:
        """
        Synchronise les derniers avis parus avec extraction approfondie des détails.
        Arrête dès que les avis connus sont rencontrés pour un temps d'exécution minimal.
        """
        mode_str = "en cours / ouverts" if only_open else "tous (y compris clôturés)"
        logger.info(f"Démarrage de la synchronisation ({mode_str}, max {max_items} avis)...")
        total_scanned = 0
        new_inserted = 0
        offset = 0
        batch_size = 20

        while total_scanned < max_items:
            current_limit = min(batch_size, max_items - total_scanned)
            total_available, items = self.fetch_page(limit=current_limit, offset=offset, only_open=only_open)

            if not items:
                logger.info("Aucun élément supplémentaire renvoyé par le portail.")
                break

            consecutive_existing = 0

            for raw in items:
                master_id = raw.get("epBidMasterId")
                bid_no = str(raw.get("bidNo", "")).strip()
                bid_seq = str(raw.get("bidModSeq", "00"))

                if not master_id or not bid_no:
                    continue

                total_scanned += 1
                detail_url = f"{self.BASE_DETAIL_URL}/{master_id}/{bid_no}/{bid_seq}"

                # Ingestion des métadonnées détaillées
                details = self.fetch_tender_details(master_id)

                tender = TenderNotice(
                    ep_bid_master_id=master_id,
                    bid_no=bid_no,
                    bid_mod_seq=bid_seq,
                    title_fr=raw.get("bidNmFr"),
                    title_ar=raw.get("bidNmAr"),
                    buyer_name=raw.get("bidInstNm", "Non spécifié"),
                    publication_date=raw.get("publicDt"),
                    deadline_date=raw.get("bdRecvEndDt"),
                    procedure_type=raw.get("procedureTypeStrFr") or raw.get("bizKindStrFr"),
                    url=detail_url,
                    raw_json=json.dumps(raw, ensure_ascii=False),
                    eval_method=details["eval_method"],
                    guarantee_type=details["guarantee_type"],
                    doc_price=details["doc_price"],
                    execution_place=details["execution_place"],
                    opening_date=details["opening_date"],
                    is_online=details["is_online"]
                )

                is_new = self.db.save_tender(tender)
                if is_new:
                    new_inserted += 1
                    logger.info(f"[NOUVEAU DÉTAILLÉ] N° {bid_no} | {tender.buyer_name} | {tender.eval_method} | {tender.execution_place}")
                else:
                    consecutive_existing += 1

            offset += current_limit

            if consecutive_existing >= len(items):
                logger.info("Historique synchronisé : tous les avis récents sont déjà indexés.")
                break

        stats = {
            "scanned": total_scanned,
            "new_inserted": new_inserted
        }
        logger.info(f"Synchronisation terminée : {stats}")
        return stats

if __name__ == "__main__":
    collector = TunepsCollector()
    collector.sync_latest(max_items=10, only_open=True)
    db_stats = collector.db.get_stats()
    print("\n--- État de la Base de Données Locale ---")
    print(f"Total avis indexés : {db_stats['total_tenders']}")
    print(f"Marchés actifs ouverts : {db_stats['active_open_tenders']}")
