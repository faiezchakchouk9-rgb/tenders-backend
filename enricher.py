"""
Module d'enrichissement et de catégorisation par IA des Appels d'Offres Tunisiens.
Analyse les objets d'avis (bilingues Français/Arabe) et extrait :
- Le secteur d'activité (BTP, IT, Énergie, Santé, etc.)
- Les tags clés
- Le gouvernorat ou la portée géographique
- Une synthèse exécutive pour le chef d'entreprise
"""
import re
import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from database import TenderDatabase, TenderNotice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("TenderEnricher")

class TenderEnricher:
    # 24 Gouvernorats de Tunisie + Grand Tunis et National
    GOVERNORATES = {
        "tunis": ["tunis", "تونس", "carthage", "el kram", "la marsa", "la goulette", "sidi bou said", "bardo", "الكرم", "المرسى", "حلق الوادي", "باردو"],
        "ariana": ["ariana", "أريانة", "raoued", "soukra", "قلعة الاندلس", "رواد", "السكرة"],
        "ben_arous": ["ben arous", "بن عروس", "radès", "hammam lif", "mornag", "megrine", "مقرين", "رادس", "حمام الأنف"],
        "manouba": ["manouba", "منوبة", "oued ellil", "tebourba", "denden", "طبربة", "وادي الليل"],
        "nabeul": ["nabeul", "نابل", "hammamet", "kelibia", "korba", "grombalia", "الحمامات", "قليبية", "قرمبالية"],
        "zaghouan": ["zaghouan", "زغوان", "el fahs", "nadhour", "الفحص", "الناظور", "jbal el ouest", "جبل الوسط"],
        "bizerte": ["bizerte", "بنزرت", "menzel bourguiba", "mateur", "sejnane", "ras jebel", "منزل بورقيبة", "ماطر", "سجنان"],
        "beja": ["béja", "beja", "باجة", "medjez el bab", "nefza", "teboursouk", "testour", "مجاز الباب", "نفزة", "تبرسق", "تستور"],
        "jendouba": ["jendouba", "جندوبة", "tabarka", "ain draham", "bou salem", "طبرقة", "عين دراهم", "بوسالم"],
        "kef": ["kef", "الكاف", "dahmani", "tajerouine", "sars", "الدهماني", "تاجروين"],
        "siliana": ["siliana", "سليانة", "makthar", "bou arada", "gaafour", "مكثر", "بوعرادة"],
        "sousse": ["sousse", "سوسة", "hammam sousse", "msaken", "kalaa kebira", "enfidha", "مساكن", "القلعة الكبيرة", "النفيضة"],
        "monastir": ["monastir", "المنستير", "moknine", "jemmel", "ksar hellal", "teboulba", "المكنين", "جمال", "قصر هلال"],
        "mahdia": ["mahdia", "المهدية", "ksour essef", "el djem", "rejouiche", "salakta", "قصور الساف", "الجم", "رجيش", "سلقطة"],
        "sfax": ["sfax", "صفاقس", "sakiet ezzit", "sakiet eddaier", "thyna", "kerkenah", "طينة", "ساقية الزيت", "ساقية الدائر", "قرقنة"],
        "kairouan": ["kairouan", "القيروان", "bouhajla", "sbikha", "nasrallah", "بوحجلة", "السبيخة"],
        "kasserine": ["kasserine", "القصرين", "sbeitla", "feriana", "thala", "سبيطلة", "فريانة", "تالة"],
        "sidi_bouzid": ["sidi bouzid", "سيدي بوزيد", "regueb", "meknassy", "jelma", "الرقاب", "المكناسي", "جلمة"],
        "gabes": ["gabès", "gabes", "قابس", "matmata", "mareth", "el hamma", "مطماطة", "مارث", "الحامة"],
        "medenine": ["médenine", "medenine", "مدنين", "djerba", "zarzis", "ben guerdane", "sidi makhlouf", "جرجيس", "جربة", "بن قردان", "سيدي مخلوف"],
        "tataouine": ["tataouine", "تطاوين", "ghomrassen", "remada", "غمراسن", "رمادة"],
        "gafsa": ["gafsa", "قفصة", "metlaoui", "mdeina", "redeyef", "المتلوي", "الرديف"],
        "tozeur": ["tozeur", "توزر", "nefta", "degache", "نفطة", "دقاش"],
        "kebili": ["kébili", "kebili", "قبلي", "douz", "souk lahad", "دوز", "سوق الأحد"]
    }

    # Taxonomie sectorielle tunisienne
    TAXONOMY = {
        "IT_TELECOM": {
            "label": "Informatique & Télécoms",
            "keywords": [
                "informatique", "ordinateur", "serveur", "réseau", "logiciel", "software", "licence",
                "ged", "numérisation", "firewall", "pare-feu", "caméra", "surveillance", "vidéosurveillance",
                "câblage", "switch", "scanner", "fibre optique", "data center", "cloud",
                "إعلامية", "حواسيب", "شبكة", "برمجيات", "رقمنة", "كاميرات مراقبة", "خادم", "موزع"
            ]
        },
        "BTP_CONSTRUCTION": {
            "label": "BTP, Génie Civil & Travaux",
            "keywords": [
                "travaux", "construction", "clôture", "bâtiment", "aménagement", "réfection",
                "étanchéité", "peinture", "voirie", "pavage", "goudronnage", "route", "piste",
                "pont", "démolition", "génie civil", "école", "menuiserie", "plomberie",
                "أشغال", "بناء", "تهيئة", "تعبيد", "طريق", "مسلك", "صيانة", "سياج", "مدرسة", "مستوصف", "ترميم"
            ]
        },
        "ENERGIE_EAU_ENVIRONNEMENT": {
            "label": "Énergie, Eau & Environnement",
            "keywords": [
                "électrique", "électricité", "énergie", "solaire", "photovoltaïque", "éolien",
                "transformateur", "câble électrique", "éclairage public", "eau", "sonede", "onas",
                "assainissement", "pompage", "forage", "station d'épuration", "déchets", "propreté",
                "كهرباء", "طاقة شمسية", "تطهير", "مياه", "إنارة عمومية", "حفر آبار", "نظافة", "بيئة", "محطة تصفية"
            ]
        },
        "SANTE_MEDICAL": {
            "label": "Santé & Équipement Médical",
            "keywords": [
                "médical", "hôpital", "santé", "médicament", "scanner médical", "échographe",
                "stérilisation", "laboratoire", "analyse", "pansement", "réactif", "dentaire",
                "صحة", "مستشفى", "تجهيزات طبية", "أدوية", "مخبر", "تحاليل", "طبية"
            ]
        },
        "TRANSPORT_MECANIQUE": {
            "label": "Transport, Véhicules & Mécanique",
            "keywords": [
                "véhicule", "voiture", "camion", "pneu", "pneumatique", "pièce de rechange",
                "carburant", "vidange", "transport", "tracteur", "engin", "mécanique",
                "سيارات", "شاحنات", "عجلات مطاطية", "قطع غيار", "وقود", "نقل", "ميكانيك"
            ]
        },
        "ETUDES_CONSEIL": {
            "label": "Études, Architecture & Contrôle",
            "keywords": [
                "étude", "audit", "expertise", "architecture", "plan", "suivi", "assistance technique",
                "contrôle technique", "formation", "conseil", "topographie",
                "دراسة", "متابعة فنية", "مخطط", "معمارية", "تدقيق", "استشارة", "مراقبة فنية"
            ]
        },
        "FOURNITURES_SERVICES": {
            "label": "Fournitures Générales & Services",
            "keywords": [
                "fourniture", "bureau", "papier", "mobilier", "impression", "gardiennage",
                "nettoyage", "restauration", "repas", "confection", "vêtements", "foire", "exposition",
                "أدوات مكتبية", "أثاث", "طباعة", "حراسة", "إعاشة", "ملابس", "تنظيم معارض"
            ]
        }
    }

    def __init__(self, db: TenderDatabase = None):
        self.db = db or TenderDatabase()
        self.gemini_key = os.getenv("GEMINI_API_KEY")

    def detect_governorate(self, text: str) -> str:
        """Détecte le gouvernorat mentionné dans l'acheteur public ou l'objet."""
        text_lower = text.lower()
        for gov, keywords in self.GOVERNORATES.items():
            for kw in keywords:
                if kw in text_lower:
                    return gov.replace("_", " ").title()
        return "National / Non spécifié"

    def classify_sector(self, text: str) -> Tuple[str, List[str]]:
        """
        Analyse morphologique et sémantique pour associer le marché à un secteur et extraire des tags.
        """
        text_lower = text.lower()
        scores: Dict[str, int] = {}
        matched_tags: Dict[str, List[str]] = {}

        for sector, data in self.TAXONOMY.items():
            scores[sector] = 0
            matched_tags[sector] = []
            for kw in data["keywords"]:
                if kw in text_lower:
                    scores[sector] += 1
                    matched_tags[sector].append(kw.title())

        # Déterminer la catégorie avec le meilleur score
        best_sector = "AUTRES"
        best_score = 0
        for sector, score in scores.items():
            if score > best_score:
                best_score = score
                best_sector = sector

        tags = matched_tags.get(best_sector, [])
        return best_sector, tags[:5]

    def generate_summary(self, tender: TenderNotice, category: str, gov: str) -> str:
        """
        Génère une synthèse exécutive structurée et vendeuse pour l'alerte client.
        """
        title = tender.title_fr or tender.title_ar or "Sans titre"
        buyer = tender.buyer_name or "Administration publique"
        deadline = tender.deadline_date or "À vérifier sur TUNEPS"

        cat_label = self.TAXONOMY.get(category, {}).get("label", "Marché Public")

        summary = (
            f"Opportunité [{cat_label}] émise par {buyer} ({gov}). "
            f"Prestation : {title}. Date limite de soumission : {deadline}."
        )
        return summary

    def enrich_tender(self, tender: TenderNotice) -> Dict[str, Any]:
        """
        Enrichit un appel d'offres : Détection Région, Secteur, Tags, Synthèse.
        """
        # Concaténer l'objet FR, l'objet AR et le nom de l'acheteur pour une détection maximale
        corpus = f"{tender.title_fr or ''} {tender.title_ar or ''} {tender.buyer_name or ''}"

        # 1. Région : Vérifier le lieu d'exécution officiel en priorité, sinon le corpus complet
        gov = None
        if tender.execution_place:
            gov = self.detect_governorate(tender.execution_place)
        if not gov or gov == "National / Non spécifié":
            gov = self.detect_governorate(corpus)

        # 2. Secteur et Tags
        category, tags = self.classify_sector(corpus)

        # 3. Synthèse
        ai_summary = self.generate_summary(tender, category, gov)

        return {
            "category": category,
            "tags": tags,
            "governorate": gov,
            "ai_summary": ai_summary
        }

    def process_all_pending(self, limit: int = 50) -> int:
        """
        Parcourt tous les avis non enrichis et met à jour la base de données.
        """
        pending = self.db.get_unenriched_tenders(limit=limit)
        if not pending:
            logger.info("Aucun appel d'offres en attente d'enrichissement.")
            return 0

        logger.info(f"Démarrage de l'enrichissement IA sur {len(pending)} avis...")
        count = 0

        for tender in pending:
            res = self.enrich_tender(tender)
            self.db.update_enrichment(
                ep_bid_master_id=tender.ep_bid_master_id,
                category=res["category"],
                tags=res["tags"],
                governorate=res["governorate"],
                ai_summary=res["ai_summary"]
            )
            count += 1
            logger.info(
                f"[ENRICHI] N° {tender.bid_no} -> Secteur: {res['category']} | "
                f"Région: {res['governorate']} | Tags: {res['tags']}"
            )

        logger.info(f"Enrichissement terminé : {count} avis qualifiés avec succès.")
        return count

if __name__ == "__main__":
    enricher = TenderEnricher()
    processed = enricher.process_all_pending(limit=50)
    
    # Affichage du bilan par secteur
    print("\n--- Bilan de la catégorisation ---")
    stats = enricher.db.get_stats()
    print(f"Total avis en base : {stats['total_tenders']}")
    print(f"Avis enrichis par IA : {stats['enriched']}")
    print(f"Marchés actifs ouverts : {stats.get('active_open_tenders', 0)}")

